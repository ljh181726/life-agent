"""
schedule_todos.py
-----------------
用 Gemini 分析 Notion 中所有未完成的作業/待辦，
根據現有 Google Calendar 空檔，智慧拆分並安排到作業日曆。
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
PLAN_DAYS      = 14   # 往後排幾天

if not NOTION_TOKEN or not TODO_DB_ID or not GEMINI_API_KEY:
    print("缺少必要環境變數 NOTION_TOKEN / NOTION_TODO_ACTIVITIES_DB_ID / GEMINI_API_KEY")
    sys.exit(1)

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

task_cal = (os.environ.get("GOOGLE_CALENDAR_ID_TASK") or
            os.environ.get("GOOGLE_CALENDAR_ID") or "primary")
all_cals = [
    os.environ.get("GOOGLE_CALENDAR_ID_CLASS") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary",
    os.environ.get("GOOGLE_CALENDAR_ID_STUDY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary",
    task_cal,
    os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary",
]
all_cals = list(dict.fromkeys(all_cals))  # deduplicate

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

def get_checkbox(page, prop):
    p = page.get("properties", {}).get(prop, {})
    if p.get("type") == "checkbox":
        return p.get("checkbox", False)
    return False

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
for page in notion_todos:
    name     = get_text(page, "名稱")
    t_type   = get_select(page, "類型")
    subject  = get_text(page, "相關科目")
    due_str  = get_date(page, "截止或考試日期")
    est_hr   = get_number(page, "預估時間（小時）")
    done_pg  = get_number(page, "已完成頁數/題數")
    total_pg = get_number(page, "總頁數/題數")

    if not name:
        continue
    # Skip completed
    if done_pg is not None and total_pg is not None and done_pg >= total_pg:
        continue

    # Parse due date
    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
        except:
            pass

    # Default estimated hours by type
    if est_hr is None:
        if t_type in ["考試", "段考"]:
            est_hr = 3.0
        elif t_type in ["作業", "習題"]:
            est_hr = 1.0
        else:
            est_hr = 1.5

    todos.append({
        "name":    name,
        "type":    t_type or "作業",
        "subject": subject,
        "due":     due_str or "無截止日",
        "est_hr":  est_hr,
    })

print(f"共找到 {len(todos)} 筆未完成待辦。")
if not todos:
    print("沒有需要排程的作業，結束。")
    sys.exit(0)

# ── 2. Fetch existing calendar events (next PLAN_DAYS) ─────────────
print(f"正在讀取未來 {PLAN_DAYS} 天的 Google Calendar 行程...")
time_min = datetime.now().isoformat() + "+08:00"
time_max = (datetime.now() + timedelta(days=PLAN_DAYS)).isoformat() + "+08:00"

existing_events = []
for cal_id in all_cals:
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "maxResults": 500,
        "orderBy": "startTime"
    }
    r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
                     headers=gcal_h, params=params)
    if r.status_code == 200:
        for ev in r.json().get("items", []):
            s = ev.get("start", {})
            e = ev.get("end", {})
            if s.get("dateTime"):
                existing_events.append({
                    "summary": ev.get("summary", ""),
                    "start":   s["dateTime"][:16],   # "2026-07-13T08:00"
                    "end":     e.get("dateTime", "")[:16]
                })

existing_events.sort(key=lambda x: x["start"])
print(f"讀取到 {len(existing_events)} 筆現有行程。")

# ── 3. Build Gemini prompt ──────────────────────────────────────────
today_str  = today.strftime("%Y-%m-%d")
end_str    = (today + timedelta(days=PLAN_DAYS)).strftime("%Y-%m-%d")
weekday_zh = ["週一","週二","週三","週四","週五","週六","週日"]

existing_text = "\n".join(
    f"  {e['start']} ~ {e['end']} {e['summary']}"
    for e in existing_events
) or "  (無現有行程)"

todos_text = "\n".join(
    f"  - [{t['type']}] {t['name']} | 科目:{t['subject']} | 截止:{t['due']} | 預估:{t['est_hr']}小時"
    for t in todos
)

prompt = f"""你是一個智慧學習排程助理。今天是 {today_str}（{weekday_zh[today.weekday()]}）。

## 規則
1. 排程範圍：{today_str} 至 {end_str}（共 {PLAN_DAYS} 天）。
2. 可用時段：每日 18:00-22:30（非學校日可加上 13:00-17:30）。
3. 學校日（週一~週五）因有暑輔或補習，僅晚上可用。
4. 週六下午可能有補習，請保守估計僅 20:00-22:00。
5. 請避開以下已有行程（同一時段不可重疊）：
{existing_text}

6. 每個待辦事項可依預估時間拆分成多個 30~90 分鐘的工作塊。
7. 截止日越近、類型為考試/段考者，優先安排。
8. 每日最多排 2.5 小時的待辦工作（避免過度疲勞）。
9. 不要在深夜 22:30 之後安排任何事項。
10. 每個工作塊之間保留至少 10 分鐘休息。

## 待辦清單
{todos_text}

## 輸出格式
請以 JSON 回答，格式如下：
{{
  "schedule": [
    {{
      "name": "作業名稱（可加 Part 1/2 等）",
      "date": "YYYY-MM-DD",
      "start": "HH:MM",
      "end": "HH:MM",
      "subject": "科目",
      "type": "類型",
      "note": "備註（可留空）"
    }}
  ]
}}

只輸出 JSON，不要有任何額外說明文字。"""



# ── 4. Call Gemini via REST API ────────────────────────────────────
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
            # Parse retry_delay from response if available
            wait_secs = 60
            try:
                err_detail = r.json()
                for v in err_detail.get("error", {}).get("details", []):
                    if v.get("@type", "").endswith("RetryInfo"):
                        d = v.get("retryDelay", "60s")
                        wait_secs = int(d.replace("s", "")) + 5
            except:
                pass
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

print(f"Gemini 回應已接收，正在解析...")

# Strip markdown code block if present
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
    print("Gemini 原始回應（前 500 字）：")
    print(raw[:500])
    sys.exit(1)

print(f"Gemini 規劃出 {len(schedule)} 個工作塊。")

# ── 5. Clear old AI-scheduled events ───────────────────────────────
print("清除舊的 AI 自動排程行程...")
params = {"timeMin": time_min, "timeMax": time_max,
          "singleEvents": "true", "maxResults": 500}
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events",
                 headers=gcal_h, params=params)
cleared = 0
if r.status_code == 200:
    for ev in r.json().get("items", []):
        src = ev.get("extendedProperties", {}).get("private", {}).get("source")
        if src == SOURCE_TAG:
            dr = requests.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}",
                headers=gcal_h)
            if dr.status_code in [200, 204]:
                cleared += 1
print(f"已清除 {cleared} 筆舊 AI 排程行程。")

# ── 6. Write to Google Calendar ─────────────────────────────────────
print("正在寫入 Google Calendar...")
success = 0
for block in schedule:
    date_s   = block.get("date", "")
    start_s  = block.get("start", "")
    end_s    = block.get("end", "")
    name     = block.get("name", "")
    subj     = block.get("subject", "")
    t_type   = block.get("type", "")
    note     = block.get("note", "")

    if not (date_s and start_s and end_s and name):
        continue

    desc = f"[Life-Agent AI 自動排程]\n科目：{subj}\n類型：{t_type}"
    if note:
        desc += f"\n備註：{note}"

    payload = {
        "summary":     name,
        "description": desc,
        "start":  {"dateTime": f"{date_s}T{start_s}:00+08:00", "timeZone": TZ},
        "end":    {"dateTime": f"{date_s}T{end_s}:00+08:00",   "timeZone": TZ},
        "colorId": "11",  # Tomato - AI scheduled tasks
        "extendedProperties": {"private": {"source": SOURCE_TAG}}
    }
    r = requests.post(
        f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events",
        headers=gcal_h, json=payload)
    if r.status_code == 200:
        print(f"  OK {date_s} {start_s}-{end_s} {name}")
        success += 1
    else:
        print(f"  FAIL {date_s} {name}: {r.status_code}")

print(f"\n[排程完成] 成功寫入 {success}/{len(schedule)} 個作業時間塊！")
