"""
schedule_todos.py
-----------------
智慧學習排程助理。
- 讀取 Notion 中的未完成待辦項目。
- 讀取自習日曆 (study_cal) 中的可用空檔行程。
- 清除 Google Calendar 上所有舊的 AI 自動排程作業時間塊 (僅刪除日曆行程，完全不影響 Notion 資料！)。
- 使用 Gemini 分析，將未完成作業重新分配到最近 7 天的空檔 (緊急優先，大任務拆分，無註明時間者預設 30 分鐘)。
"""

import os
import sys
import json
import time
import requests
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

if not NOTION_TOKEN or not TODO_DB_ID or not GEMINI_API_KEY:
    print("缺少必要環境變數 NOTION_TOKEN / NOTION_TODO_ACTIVITIES_DB_ID / GEMINI_API_KEY")
    sys.exit(1)

# ── Parse Arguments ──────────────────────────────────────────────────
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--days", type=int, default=9, help="Number of days to schedule")
parser.add_argument("--offset", type=int, default=0, help="Days offset from today to start scheduling")
args, unknown = parser.parse_known_args()

PLAN_DAYS = args.days
OFFSET_DAYS = args.offset

print(f"排程天數: {PLAN_DAYS} 天，起始偏移量: {OFFSET_DAYS} 天")

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
class_cal = (os.environ.get("GOOGLE_CALENDAR_ID_CLASS") or
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

def parse_duration_from_name(name):
    import re
    match_min = re.search(r"\(需(\d+)分鐘\)", name)
    match_hr = re.search(r"\(需([\d\.]+)小時\)", name)
    if match_min:
        return float(match_min.group(1)) / 60.0
    elif match_hr:
        return float(match_hr.group(1))
    return None

def create_notion_todo(name, subject, due_date):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": TODO_DB_ID},
        "properties": {
            "名稱": {"title": [{"text": {"content": name}}]},
            "類型": {"select": {"name": "作業"}},
            "相關科目": {"rich_text": [{"text": {"content": subject}}]},
            "截止或考試日期": {"date": {"start": due_date}},
            "總頁數/題數": {"number": 1},
            "已完成頁數/題數": {"number": 0}
        }
    }
    r = requests.post(url, headers=notion_h, json=payload)
    if r.status_code == 200:
        print(f"  [Notion] 自動建立重複補習作業: {name} (截止: {due_date})")
        return True
    else:
        print(f"  [Notion] 建立補習作業失敗 {name}: {r.status_code} - {r.text}")
        return False

def auto_generate_cram_homeworks(existing_todos, target_date, days_range):
    print(f"正在檢查未來 {days_range} 天是否有補習班課程，以自動生成作業...")
    time_min = target_date.isoformat() + "T00:00:00+08:00"
    time_max = (target_date + timedelta(days=days_range)).isoformat() + "T23:59:59+08:00"
    params = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "maxResults": 250, "orderBy": "startTime"}
    r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{class_cal}/events", headers=gcal_h, params=params)
    
    if r.status_code != 200:
        print(f"無法讀取課程日曆: {r.status_code}")
        return False
        
    created_any = False
    existing_names = {get_text(p, "名稱") for p in existing_todos}
    
    for item in r.json().get("items", []):
        summary = item.get("summary", "")
        start_str = item.get("start", {}).get("dateTime", "") or item.get("start", {}).get("date", "")
        if not start_str:
            continue
            
        dt_str = start_str[:10]
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
        m_d = f"{dt.month}/{dt.day}"
        
        cram_info = None
        if "PC化學" in summary:
            cram_info = {
                "subject": "化學",
                "part1_dur": 1.5, "part2_dur": 1.5,
                "part1_due": (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                "part2_due": (dt + timedelta(days=7)).strftime("%Y-%m-%d") # 下一週上課前
            }
        elif "PC物理" in summary:
            cram_info = {
                "subject": "物理",
                "part1_dur": 0.5, "part2_dur": 0.5,
                "part1_due": (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                "part2_due": (dt + timedelta(days=7)).strftime("%Y-%m-%d") # 下一週上課前
            }
        elif "PC數學" in summary:
            cram_info = {
                "subject": "數學",
                "part1_dur": 1.25, "part2_dur": 1.25,
                "part1_due": (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                "part2_due": (dt + timedelta(days=7)).strftime("%Y-%m-%d") # 下一週上課前
            }
            
        if cram_info:
            sub = cram_info["subject"]
            name_1 = f"PC{sub}作業 Part 1 ({m_d}) (需{cram_info['part1_dur']}小時)"
            name_2 = f"PC{sub}作業 Part 2 ({m_d}) (需{cram_info['part2_dur']}小時)"
            
            if name_1 not in existing_names:
                if create_notion_todo(name_1, sub, cram_info["part1_due"]):
                    created_any = True
            if name_2 not in existing_names:
                if create_notion_todo(name_2, sub, cram_info["part2_due"]):
                    created_any = True
                    
    return created_any

# ── 1. Fetch Notion todos ───────────────────────────────────────────
def fetch_all_notion_todos():
    print("正在從 Notion 讀取未完成的作業/待辦...")
    results = []
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
        results.extend(d.get("results", []))
        has_more = d.get("has_more", False)
        cursor   = d.get("next_cursor")
    return results

notion_todos = fetch_all_notion_todos()

# Target date shifted by offset
today = datetime.now().date() + timedelta(days=OFFSET_DAYS)

# Auto-generate cram school homeworks
if auto_generate_cram_homeworks(notion_todos, today, PLAN_DAYS):
    # Re-fetch if any new todos were created
    notion_todos = fetch_all_notion_todos()

todos = []
for page in notion_todos:

    name     = get_text(page, "名稱")
    t_type   = get_select(page, "類型")
    subject  = get_text(page, "相關科目")
    due_str  = get_date(page, "截止或考試日期")
    done_pg  = get_number(page, "已完成頁數/題數")
    total_pg = get_number(page, "總頁數/題數")

    if not name:
        continue
    if done_pg is not None and total_pg is not None and done_pg >= total_pg:
        continue

    # Parse duration from name or fallback
    est_hr = parse_duration_from_name(name)
    if est_hr is None:
        est_hr = 0.5


    todos.append({
        "notion_page_id": page["id"],
        "name":    name,
        "type":    t_type or "作業",
        "subject": subject or "無",
        "due":     due_str or "無截止日",
        "est_hr":  est_hr,
    })

print(f"共找到 {len(todos)} 筆未完成待辦。")
if not todos:
    print("沒有需要排程的待辦作業。")
    # Clean up old events even if there are no todos
    time_min = datetime.combine(today, datetime.min.time()).isoformat() + "+08:00"
    time_max = datetime.combine(today + timedelta(days=PLAN_DAYS), datetime.max.time()).isoformat() + "+08:00"
    params = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "maxResults": 250}
    r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events", headers=gcal_h, params=params)
    if r.status_code == 200:
        for ev in r.json().get("items", []):
            if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
                requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}", headers=gcal_h)
    sys.exit(0)

# ── 2. Query free slots (next PLAN_DAYS) ───────────────────────────
print(f"正在讀取未來 {PLAN_DAYS} 天自習日曆的「可用空檔」...")
time_min = datetime.combine(today, datetime.min.time()).isoformat() + "+08:00"
time_max = datetime.combine(today + timedelta(days=PLAN_DAYS), datetime.max.time()).isoformat() + "+08:00"

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

if not free_slots:
    print("沒有可用的空檔行程！請確認自習日曆已成功更新。")
    sys.exit(0)

# ── 3. Clear old AI-scheduled events ───────────────────────────────
print(f"正在清除未來 {PLAN_DAYS} 天的舊 AI 作業排程 (僅刪除行事曆行程，Notion 資料安全無恙)...")
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events", headers=gcal_h, params=params)
cleared = 0
if r.status_code == 200:
    for ev in r.json().get("items", []):
        if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
            dr = requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}", headers=gcal_h)
            if dr.status_code in [200, 204]:
                cleared += 1
print(f"已清除 {cleared} 筆舊 AI 排程。")

# ── 4. Call Gemini to Plan ──────────────────────────────────────────
slots_text = "\n".join(
    f"  - {parse_iso(fs['start']).strftime('%Y-%m-%d %H:%M')} ~ {parse_iso(fs['end']).strftime('%H:%M')} (可用 {(parse_iso(fs['end']) - parse_iso(fs['start'])).seconds // 60} 分鐘)"
    for fs in free_slots
)

todos_text = "\n".join(
    f"  - ID: {t['notion_page_id']} | [{t['type']}] {t['name']} | 科目:{t['subject']} | 截止:{t['due']} | 預估:{t['est_hr']}小時"
    for t in todos
)

today_str = today.strftime("%Y-%m-%d")
end_str = (today + timedelta(days=PLAN_DAYS)).strftime("%Y-%m-%d")

prompt = f"""你是一個智慧學習排程助理。今天是 {today_str}。

## 規則
1. 排程範圍：未來 {PLAN_DAYS} 天，至 {end_str}。
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

# ── 5. Write to Google Calendar ─────────────────────────────────────
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
