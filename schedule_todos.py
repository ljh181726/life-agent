"""
schedule_todos.py
-----------------
智慧學習排程助理。
支援兩步驟運作：
1. 增量與衝突排程 (Step 1)：
   - 提取最近 7 天的空檔 (來自自習日曆 study_cal)，與現有 AI 排程的作業比對。
   - 若現有 AI 作業不完全處於空檔內 (即與新行程衝突)，則將其刪除並重新排程。
   - 找出 Notion 中全新、尚未安排的作業，將其排入剩餘可用空檔 (無指定時間的作業預設為 30 分鐘)。
2. 每日 24:00 全面重新優化 (Step 2)：
   - 清除未來 7 天所有 AI 排程的作業。
   - 讀取 Notion 所有未完成待辦與自習日曆的所有空檔。
   - 使用 Gemini 將最近 7 天的作業全新合理安排 (緊急優先，大任務拆分)。
"""

import os
import sys
import json
import time
import requests
import argparse
from datetime import datetime, timedelta

# Fix Windows console encoding
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except:
        pass

# ── Load .env ───────────────────────────────────────────────────────
env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

# ── Constants ───────────────────────────────────────────────────────
NOTION_TOKEN   = os.environ.get("NOTION_TOKEN", "")
TODO_DB_ID     = os.environ.get("NOTION_TODO_ACTIVITIES_DB_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TOKEN_CACHE    = ".gcal_token_cache.json"
SOURCE_TAG     = "life-agent-ai-scheduled"
TZ             = "Asia/Taipei"
PLAN_DAYS      = 7   # 最近 7 天

if not NOTION_TOKEN or not TODO_DB_ID or not GEMINI_API_KEY:
    print("缺少必要環境變數 NOTION_TOKEN / NOTION_TODO_ACTIVITIES_DB_ID / GEMINI_API_KEY")
    sys.exit(1)

# ── Parse arguments and determine mode ──────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--mode", choices=["step1", "step2", "auto"], default="auto")
args, unknown = parser.parse_known_args()

# Determine mode based on Taipei hour if "auto"
import pytz
tw_tz = pytz.timezone("Asia/Taipei")
now_tw = datetime.now(tw_tz)

mode = args.mode
if mode == "auto":
    # 24:00 (00:00 to 00:59) is Step 2
    if now_tw.hour == 0:
        mode = "step2"
    else:
        mode = "step1"

print(f"目前台灣時間: {now_tw.strftime('%Y-%m-%d %H:%M:%S')}，執行模式: {mode.upper()}")

# ── Google Calendar auth ────────────────────────────────────────────
def get_gcal_token():
    if os.path.exists(TOKEN_CACHE):
        try:
            with open(TOKEN_CACHE, "r", encoding="utf-8") as f:
                c = json.load(f)
            if c.get("expires_at", 0) > time.time() + 60:
                return c["access_token"]
        except:
            pass
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN"),
        "grant_type":    "refresh_token"
    })
    r.raise_for_status()
    d = r.json()
    with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
        json.dump({"access_token": d["access_token"],
                   "expires_at": time.time() + d.get("expires_in", 3600)}, f)
    return d["access_token"]

gcal_token = get_gcal_token()
if not gcal_token:
    print("無法取得 Google Calendar 授權，終止執行。")
    sys.exit(1)

study_cal = (os.environ.get("GOOGLE_CALENDAR_ID_STUDY") or
             os.environ.get("GOOGLE_CALENDAR_ID") or "primary")
task_cal = (os.environ.get("GOOGLE_CALENDAR_ID_TASK") or
            os.environ.get("GOOGLE_CALENDAR_ID") or "primary")

gcal_h = {"Authorization": f"Bearer {gcal_token}", "Content-Type": "application/json"}
notion_h = {"Authorization": f"Bearer {NOTION_TOKEN}",
             "Notion-Version": "2022-06-28",
             "Content-Type": "application/json"}

# ── Helpers ─────────────────────────────────────────────────────────
def get_text(page, prop):
    p = page.get("properties", {}).get(prop, {})
    t = p.get("type")
    if t == "title" and p.get("title"):
        return p["title"][0]["text"]["content"]
    if t == "rich_text" and p.get("rich_text"):
        return p["rich_text"][0]["text"]["content"]
    return ""

def get_select(page, prop):
    p = page.get("properties", {}).get(prop, {})
    if p.get("type") == "select" and p.get("select"):
        return p["select"]["name"]
    return ""

def get_date(page, prop):
    p = page.get("properties", {}).get(prop, {})
    if p.get("type") == "date" and p.get("date"):
        return p["date"]["start"]
    return None

def get_number(page, prop):
    p = page.get("properties", {}).get(prop, {})
    if p.get("type") == "number":
        return p.get("number")
    return None

def parse_iso(iso_str):
    if "+" in iso_str:
        s, _ = iso_str.split("+", 1)
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    return datetime.fromisoformat(iso_str).replace(tzinfo=None)

# ── 1. Fetch Notion todos ───────────────────────────────────────────
print("正在從 Notion 讀取未完成的作業/待辦...")
notion_todos = []
has_more = True
cursor = None
while has_more:
    payload = {}
    if cursor:
        payload["start_cursor"] = cursor
    res = requests.post(f"https://api.notion.com/v1/databases/{TODO_DB_ID}/query",
                        headers=notion_h, json=payload)
    if res.status_code != 200:
        print(f"Notion 查詢失敗: {res.status_code}")
        break
    d = res.json()
    notion_todos.extend(d.get("results", []))
    has_more = d.get("has_more", False)
    cursor   = d.get("next_cursor")

today = datetime.now().date()
todos = []
todos_map = {}
for page in notion_todos:
    name     = get_text(page, "名稱")
    t_type   = get_select(page, "類型")
    subject  = get_text(page, "相關科目")
    due_str  = get_date(page, "截止或考試日期")
    est_hr   = get_number(page, "預估時間（小時）")
    done_pg  = get_number(page, "已完成頁數/題數")
    total_pg = get_number(page, "總頁數/題數")
    page_id  = page["id"]

    if not name:
        continue
    if done_pg is not None and total_pg is not None and done_pg >= total_pg:
        continue

    # Default duration: if not specified, default to 30 minutes (0.5 hours)
    if est_hr is None:
        est_hr = 0.5

    todo_item = {
        "notion_page_id": page_id,
        "name":    name,
        "type":    t_type or "作業",
        "subject": subject or "無",
        "due":     due_str or "無截止日",
        "est_hr":  est_hr,
    }
    todos.append(todo_item)
    todos_map[page_id] = todo_item

print(f"共找到 {len(todos)} 筆未完成待辦。")

# ── 2. Query free slots (next PLAN_DAYS) ───────────────────────────
print(f"正在讀取未來 {PLAN_DAYS} 天自習日曆的「可用空檔」...")
time_min = datetime.now().isoformat() + "+08:00"
time_max = (datetime.now() + timedelta(days=PLAN_DAYS)).isoformat() + "+08:00"

params = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "maxResults": 250, "orderBy": "startTime"}
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{study_cal}/events", headers=gcal_h, params=params)
free_slots = []
if r.status_code == 200:
    for item in r.json().get("items", []):
        if item.get("extendedProperties", {}).get("private", {}).get("source") == "life-agent-free-slot":
            free_slots.append({
                "summary": item.get("summary", ""),
                "start": item["start"]["dateTime"],
                "end": item["end"]["dateTime"]
            })
print(f"讀取到 {len(free_slots)} 個可用空檔。")

# ── 3. Query existing AI-scheduled tasks ───────────────────────────
print(f"正在讀取未來 {PLAN_DAYS} 天已安排的 AI 作業行程...")
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events", headers=gcal_h, params=params)
ai_scheduled_events = []
if r.status_code == 200:
    for item in r.json().get("items", []):
        src = item.get("extendedProperties", {}).get("private", {}).get("source")
        if src == SOURCE_TAG:
            ai_scheduled_events.append({
                "id": item["id"],
                "summary": item.get("summary", ""),
                "start": item["start"]["dateTime"],
                "end": item["end"]["dateTime"],
                "notion_page_id": item.get("extendedProperties", {}).get("private", {}).get("notion_page_id", "")
            })
print(f"讀取到 {len(ai_scheduled_events)} 筆已安排 AI 行程。")

# ── 4. Main Scheduling Logic based on Mode ────────────────────────
to_schedule = []
available_intervals = []

if mode == "step2":
    # ══════ STEP 2: Full Re-optimization ══════
    print("\n[Step 2] 全面重新排程中。正在清除所有舊 AI 行程...")
    cleared = 0
    for ev in ai_scheduled_events:
        dr = requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}", headers=gcal_h)
        if dr.status_code in [200, 204]:
            cleared += 1
    print(f"已清除 {cleared} 筆舊 AI 排程。")
    
    to_schedule = todos
    for s in free_slots:
        available_intervals.append((parse_iso(s["start"]), parse_iso(s["end"])))

else:
    # ══════ STEP 1: Incremental Conflict Check & Resolve ══════
    print("\n[Step 1] 進行衝突比對與增量排程...")
    
    # Check for conflicts
    conflicting_ids = set()
    valid_tasks = []
    
    for ev in ai_scheduled_events:
        ev_start = parse_iso(ev["start"])
        ev_end   = parse_iso(ev["end"])
        
        # Check if ev is completely inside any of the free slots
        is_valid = False
        for s in free_slots:
            s_start = parse_iso(s["start"])
            s_end   = parse_iso(s["end"])
            if s_start <= ev_start and ev_end <= s_end:
                is_valid = True
                break
        
        if not is_valid:
            print(f"  發現衝突行程: {ev['summary']} ({ev['start']} - {ev['end']})，即將刪除並重排。")
            requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}", headers=gcal_h)
            if ev["notion_page_id"]:
                conflicting_ids.add(ev["notion_page_id"])
        else:
            valid_tasks.append(ev)
            
    # Find new / unscheduled todos
    scheduled_todo_ids = {ev["notion_page_id"] for ev in valid_tasks if ev["notion_page_id"]}
    unscheduled_todos = []
    for t in todos:
        pid = t["notion_page_id"]
        if pid in conflicting_ids or pid not in scheduled_todo_ids:
            unscheduled_todos.append(t)
            
    print(f"  衝突重排待辦: {len(conflicting_ids)} 筆，全新未安排待辦: {len(unscheduled_todos) - len(conflicting_ids)} 筆。")
    
    if not unscheduled_todos:
        print("  所有待辦均已在合理空檔中排定，無須重排或增量排程。")
        sys.exit(0)
        
    to_schedule = unscheduled_todos
    
    # Calculate remaining free slots = free_slots - valid_tasks
    all_free = [(parse_iso(s["start"]), parse_iso(s["end"])) for s in free_slots]
    busy_list = [(parse_iso(ev["start"]), parse_iso(ev["end"])) for ev in valid_tasks]
    
    result_intervals = list(all_free)
    for b_start, b_end in busy_list:
        next_res = []
        for s_start, s_end in result_intervals:
            if b_end <= s_start or b_start >= s_end:
                next_res.append((s_start, s_end))
            else:
                if s_start < b_start:
                    next_res.append((s_start, b_start))
                if b_end < s_end:
                    next_res.append((b_end, s_end))
        result_intervals = next_res
        
    available_intervals = [x for x in result_intervals if (x[1] - x[0]).total_seconds() >= 600] # Min 10 mins

# ── 5. Call Gemini to Place Tasks ──────────────────────────────────
if not to_schedule:
    print("沒有需要排程的任務。")
    sys.exit(0)

if not available_intervals:
    print("沒有可用的空檔區塊可供排程！")
    sys.exit(1)

# Format intervals and todos for prompt
slots_text = "\n".join(
    f"  - {fs.strftime('%Y-%m-%d')} {fs.strftime('%H:%M')} ~ {fe.strftime('%H:%M')} (可用 {(fe - fs).seconds // 60} 分鐘)"
    for fs, fe in sorted(available_intervals)
)

todos_text = "\n".join(
    f"  - ID: {t['notion_page_id']} | [{t['type']}] {t['name']} | 科目:{t['subject']} | 截止:{t['due']} | 預估:{t['est_hr']}小時"
    for t in to_schedule
)

today_str = today.strftime("%Y-%m-%d")
end_str = (today + timedelta(days=PLAN_DAYS)).strftime("%Y-%m-%d")

prompt = f"""你是一個智慧學習排程助理。今天是 {today_str}。

## 規則
1. 排程範圍：最近 7 天，至 {end_str}。
2. 請只使用以下列出的「可用空檔」進行排程。不可在空檔之外的時間安排任何事項：
{slots_text}

3. 每個待辦事項可以依照預估時間拆分成多個 30~90 分鐘的工作塊。
4. 截止日越近、類型為考試/段考者，優先安排。
5. 每個工作塊之間保留至少 10 分鐘休息（亦即同一空檔內的連續工作塊不可重疊且需間隔）。
6. 請以 JSON 格式回覆，只輸出 JSON，不要有任何額外說明文字。

## 待辦清單
{todos_text}

## 輸出格式
{{
  "schedule": [
    {{
      "notion_page_id": "對應待辦清單中的 ID",
      "name": "工作名稱（可加 Part 1/2 等）",
      "date": "YYYY-MM-DD",
      "start": "HH:MM",
      "end": "HH:MM",
      "subject": "科目",
      "type": "類型"
    }}
  ]
}}
"""

print("正在呼叫 Gemini 進行智慧排程分析...")
GEMINI_MODEL = "gemini-3.1-flash-lite"
gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
gemini_payload = {
    "contents": [{"parts": [{"text": prompt}]}],
    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096}
}

raw = None
for attempt in range(4):
    try:
        r = requests.post(gemini_url, json=gemini_payload, timeout=60)
        if r.status_code == 429:
            wait_secs = 60
            try:
                err_detail = r.json()
                for v in err_detail.get("error", {}).get("details", []):
                    if v.get("@type", "").endswith("RetryInfo"):
                        d = v.get("retryDelay", "60s")
                        wait_secs = int(d.replace("s", "")) + 5
            except: pass
            print(f"  Gemini 429 速率限制，等待 {wait_secs} 秒後重試...")
            time.sleep(wait_secs)
            continue
        r.raise_for_status()
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        break
    except Exception as e:
        wait = 2 ** attempt * 5
        print(f"  Gemini 呼叫失敗 ({e})，{wait} 秒後重試...")
        time.sleep(wait)

if not raw:
    print("Gemini 呼叫失敗，終止執行。")
    sys.exit(1)

# Clean up raw output
if raw.startswith("```"):
    raw = raw.split("```", 2)[1]
    if raw.startswith("json"):
        raw = raw[4:]
    raw = raw.strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

try:
    result   = json.loads(raw)
    schedule = result.get("schedule", [])
except json.JSONDecodeError as e:
    print(f"JSON 解析失敗: {e}")
    print("Gemini 原始回應：")
    print(raw[:1000])
    sys.exit(1)

print(f"Gemini 規劃出 {len(schedule)} 個工作塊。")

# ── 6. Write New Schedule to Calendar ───────────────────────────────
print("正在寫入 Google Calendar...")
success = 0
for block in schedule:
    pid      = block.get("notion_page_id", "")
    date_s   = block.get("date", "")
    start_s  = block.get("start", "")
    end_s    = block.get("end", "")
    name     = block.get("name", "")
    subj     = block.get("subject", "")
    t_type   = block.get("type", "")

    if not (date_s and start_s and end_s and name):
        continue

    desc = f"[Life-Agent AI 自動排程]\n科目：{subj}\n類型：{t_type}"
    payload = {
        "summary":     name,
        "description": desc,
        "start":  {"dateTime": f"{date_s}T{start_s}:00+08:00", "timeZone": TZ},
        "end":    {"dateTime": f"{date_s}T{end_s}:00+08:00",   "timeZone": TZ},
        "colorId": "11",  # Tomato
        "extendedProperties": {
            "private": {
                "source": SOURCE_TAG,
                "notion_page_id": pid
            }
        }
    }
    r = requests.post(
        f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events",
        headers=gcal_h, json=payload)
    if r.status_code == 200:
        print(f"  OK {date_s} {start_s}-{end_s} {name}")
        success += 1
    else:
        print(f"  FAIL {date_s} {name}: {r.status_code} - {r.text}")

print(f"\n[排程完成] 成功寫入 {success}/{len(schedule)} 個作業時間塊！")
