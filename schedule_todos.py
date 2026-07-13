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
import re

def auto_complete_past_tasks():
    print("正在檢查過去排程是否已完成 (沒說就是有完成)...")
    inc_file = "C:/Users/ST/.gemini/antigravity-ide/brain/f9de8527-920e-4eaf-ae2b-5a4061a0a8a6/incomplete_reported.json"
    reported_list = []
    if os.path.exists(inc_file):
        try:
            with open(inc_file, "r", encoding="utf-8") as f:
                reported_list = json.load(f)
        except:
            pass
            
    now_str = datetime.now().isoformat() + "+08:00"
    # 查詢過去 15 天至目前的所有 AI 排程事件
    time_min = (datetime.now() - timedelta(days=15)).isoformat() + "+08:00"
    params = {"timeMin": time_min, "timeMax": now_str, "singleEvents": "true", "maxResults": 250}
    r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events", headers=gcal_h, params=params)
    
    completed_count = 0
    if r.status_code == 200:
        events = r.json().get("items", [])
        for ev in events:
            if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
                pid = ev.get("extendedProperties", {}).get("private", {}).get("notion_page_id")
                if not pid:
                    continue
                
                # 如果使用者有回報「沒寫完」，跳過自動完成
                if pid in reported_list:
                    print(f"  [未完成保留] {ev.get('summary')} 已由 Telegram 回報未完成，跳過自動完成標記。")
                    continue
                
                # 自動到 Notion 標記為完成
                res = requests.get(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h)
                if res.status_code == 200:
                    page = res.json()
                    done_pg  = get_number(page, "已完成頁數/題數")
                    total_pg = get_number(page, "總頁數/題數") or 1
                    
                    if done_pg is None or done_pg < total_pg:
                        payload = {"properties": {"已完成頁數/題數": {"number": total_pg}}}
                        res_patch = requests.patch(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h, json=payload)
                        if res_patch.status_code == 200:
                            print(f"  [自動完成] {ev.get('summary')} (時間已過且無回報未完成)")
                            completed_count += 1
    print(f"完成昨日與過去排程檢查，自動標記 {completed_count} 筆完成。")

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
parser.add_argument("--days", type=int, default=7, help="Number of days to schedule")
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

def get_or_create_tasks_list(access_token, list_name):
    url = "https://tasks.googleapis.com/v1/users/@me/lists"
    h = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    try:
        r = requests.get(url, headers=h)
        if r.status_code == 200:
            lists = r.json().get("items", [])
            for lst in lists:
                if lst.get("title") == list_name:
                    return lst.get("id")
        r_create = requests.post(url, headers=h, json={"title": list_name})
        if r_create.status_code == 200:
            print(f"成功建立 Google Tasks 清單: {list_name}")
            return r_create.json().get("id")
    except Exception as e:
        print(f"查詢/建立 Tasks 清單失敗: {e}")
    return "@default"

def check_google_tasks_completion(access_token, list_id):
    print("正在檢查 Google Tasks 完成狀態並同步回 Notion...")
    url = f"https://tasks.googleapis.com/v1/lists/{list_id}/tasks"
    h = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    params = {
        "showCompleted": "true",
        "showHidden": "true",
        "maxResults": 100
    }
    completed_notion_ids = []
    try:
        r = requests.get(url, headers=h, params=params)
        if r.status_code == 200:
            tasks = r.json().get("items", [])
            for t in tasks:
                notes = t.get("notes", "")
                if "NotionID: [" in notes:
                    match = re.search(r"NotionID:\s*\[([a-f0-9\-]+)\]", notes)
                    if match:
                        pid = match.group(1)
                        if t.get("status") == "completed":
                            completed_notion_ids.append(pid)
    except Exception as e:
        print(f"從 Google Tasks 取得完成項目失敗: {e}")
        return
        
    synced_count = 0
    for pid in completed_notion_ids:
        try:
            res = requests.get(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h)
            if res.status_code == 200:
                page = res.json()
                done_pg  = get_number(page, "已完成頁數/題數")
                total_pg = get_number(page, "總頁數/題數") or 1
                if done_pg is None or done_pg < total_pg:
                    payload = {"properties": {"已完成頁數/題數": {"number": total_pg}}}
                    res_patch = requests.patch(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h, json=payload)
                    if res_patch.status_code == 200:
                        print(f"  [Tasks 同步] {get_text(page, '名稱')} 已由 Tasks App 標記完成")
                        synced_count += 1
        except Exception as ex:
            print(f"同步 Notion 待辦完成失敗 {pid}: {ex}")
    print(f"完成 Google Tasks 同步回 Notion，共更新 {synced_count} 筆。")

def sync_todos_to_google_tasks(access_token, list_id, active_todos):
    print("正在同步未完成的 Notion 待辦至 Google Tasks...")
    url = f"https://tasks.googleapis.com/v1/lists/{list_id}/tasks"
    h = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    existing_tasks = {}
    try:
        r = requests.get(url, headers=h, params={"showCompleted": "true", "showHidden": "true", "maxResults": 100})
        if r.status_code == 200:
            for t in r.json().get("items", []):
                notes = t.get("notes", "")
                if "NotionID: [" in notes:
                    match = re.search(r"NotionID:\s*\[([a-f0-9\-]+)\]", notes)
                    if match:
                        pid = match.group(1)
                        existing_tasks[pid] = (t.get("id"), t.get("status"))
    except Exception as e:
        print(f"取得現有 Tasks 失敗: {e}")
        return

    active_pids = set()
    for t in active_todos:
        pid = t["notion_page_id"]
        active_pids.add(pid)
        name = t["name"]
        due_str = t["due"]
        notes_content = f"NotionID: [{pid}]\n相關科目: {t['subject']}\n類型: {t['type']}"
        due_rfc = None
        if due_str and due_str != "無截止日":
            due_rfc = f"{due_str}T00:00:00.000Z"
        task_payload = {
            "title": name,
            "notes": notes_content,
        }
        if due_rfc:
            task_payload["due"] = due_rfc
            
        if pid in existing_tasks:
            gtid, status = existing_tasks[pid]
            try:
                requests.patch(f"{url}/{gtid}", headers=h, json=task_payload)
            except Exception as e:
                print(f"更新 Google Task 失敗 {gtid}: {e}")
        else:
            try:
                requests.post(url, headers=h, json=task_payload)
                print(f"  [Google Tasks] 已建立任務: {name}")
            except Exception as e:
                print(f"建立 Google Task 失敗 {name}: {e}")

    for pid, (gtid, status) in existing_tasks.items():
        if pid not in active_pids and status == "needsAction":
            try:
                res = requests.get(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h)
                if res.status_code == 200:
                    page = res.json()
                    done_pg  = get_number(page, "已完成頁數/題數")
                    total_pg = get_number(page, "總頁數/題數") or 1
                    if done_pg is not None and done_pg >= total_pg:
                        requests.patch(f"{url}/{gtid}", headers=h, json={"status": "completed"})
                        print(f"  [Google Tasks] 標記已完成: {get_text(page, '名稱')}")
                elif res.status_code == 404:
                    requests.delete(f"{url}/{gtid}", headers=h)
                    print(f"  [Google Tasks] 已刪除孤兒任務: {gtid}")
            except Exception as e:
                print(f"處理孤兒任務失敗 {pid}: {e}")

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
        payload = {
            "sorts": [
                {
                    "timestamp": "created_time",
                    "direction": "ascending"
                }
            ]
        }
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

tasks_list_name = os.environ.get("GOOGLE_TASKS_LIST_NAME") or "Life-Agent"
tasks_list_id = get_or_create_tasks_list(gcal_token, tasks_list_name)
check_google_tasks_completion(gcal_token, tasks_list_id)

auto_complete_past_tasks()

notion_todos = fetch_all_notion_todos()

# Target date shifted by offset
today = datetime.now().date() + timedelta(days=OFFSET_DAYS)

# Auto-generate cram school homeworks
if auto_generate_cram_homeworks(notion_todos, today, PLAN_DAYS):
    # Re-fetch if any new todos were created
    auto_complete_past_tasks()

notion_todos = fetch_all_notion_todos()

todos = []
misc_todos = []
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

    # 判斷是否為雜項：類型為「雜項」，或名稱包含「雜項」或「解析失敗」，且沒有標註預估時間
    est_hr = parse_duration_from_name(name)
    is_misc = (t_type == "雜項" or "雜項" in name or "解析失敗" in name) and (est_hr is None)

    if est_hr is None:
        est_hr = 0.5

    todo_item = {
        "notion_page_id": page["id"],
        "name":    name,
        "type":    t_type or "作業",
        "subject": subject or "無",
        "due":     due_str or "無截止日",
        "est_hr":  est_hr,
    }

    if is_misc:
        misc_todos.append(todo_item)
    else:
        todos.append(todo_item)

def subtract_intervals(free_slots_list, busy_slots_list):
    res_list = []
    for fs in free_slots_list:
        fs_s = parse_iso(fs["start"])
        fs_e = parse_iso(fs["end"])
        
        curr_intervals = [(fs_s, fs_e)]
        for bs_s, bs_e in busy_slots_list:
            next_intervals = []
            for s, e in curr_intervals:
                if bs_e <= s or bs_s >= e:
                    next_intervals.append((s, e))
                else:
                    if bs_s > s:
                        next_intervals.append((s, bs_s))
                    if bs_e < e:
                        next_intervals.append((bs_e, e))
            curr_intervals = next_intervals
        
        for s, e in curr_intervals:
            if (e - s).seconds >= 600:
                res_list.append({
                    "summary": fs.get("summary", "可用空檔"),
                    "start": s.isoformat() + "+08:00",
                    "end": e.isoformat() + "+08:00"
                })
    return res_list

print(f"共找到 {len(todos)} 筆未完成排程作業，{len(misc_todos)} 筆未完成雜項待辦。")

# ── 2. Query free slots (next PLAN_DAYS) ──
print(f"正在讀取未來 {PLAN_DAYS} 天自習日曆的「可用空檔」...")
time_min = datetime.combine(today, datetime.min.time()).isoformat() + "+08:00"
time_max = (datetime.combine(today, datetime.min.time()) + timedelta(days=PLAN_DAYS+1)).isoformat() + "+08:00"

params_slots = {"timeMin": time_min, "timeMax": time_max, "singleEvents": "true", "maxResults": 250, "orderBy": "startTime"}
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{study_cal}/events", headers=gcal_h, params=params_slots)
free_slots = []
if r.status_code == 200:
    for item in r.json().get("items", []):
        if item.get("extendedProperties", {}).get("private", {}).get("source") == "life-agent-free-slot":
            free_slots.append({
                "summary": item.get("summary", ""),
                "start": item["start"]["dateTime"],
                "end": item["end"]["dateTime"]
            })
print(f"讀取到 {len(free_slots)} 個原始可用空檔。")

# ── 3. Check and clean GCal events with Conflict Detection & Locking ──
real_today = datetime.now().date()
time_min_query = datetime.combine(real_today - timedelta(days=1), datetime.min.time()).isoformat() + "+08:00"
time_max_query = datetime.combine(today + timedelta(days=PLAN_DAYS), datetime.max.time()).isoformat() + "+08:00"
params_events = {"timeMin": time_min_query, "timeMax": time_max_query, "singleEvents": "true", "maxResults": 500}

print("正在檢查與清理 Google Calendar 排程 (增量鎖定與衝突檢測)...")
already_scheduled_ids = set()
busy_slots = []
cleared = 0
locked = 0

uncompleted_pids = {t["id"] for t in notion_todos}
todo_due_map = {t["id"]: get_date(t, "截止或考試日期") for t in notion_todos}

def is_inside_free_slots(start_dt, end_dt, free_slots):
    for fs in free_slots:
        fs_start = parse_iso(fs["start"])
        fs_end = parse_iso(fs["end"])
        if fs_start <= start_dt and end_dt <= fs_end:
            return True
    return False

r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events", headers=gcal_h, params=params_events)
if r.status_code == 200:
    ai_events = []
    for ev in r.json().get("items", []):
        if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
            start_str = ev.get("start", {}).get("dateTime", "") or ev.get("start", {}).get("date", "")
            if start_str:
                ai_events.append(ev)
    
    ai_events.sort(key=lambda ev: ev.get("start", {}).get("dateTime", "") or ev.get("start", {}).get("date", ""))
    
    last_end_time = None
    for ev in ai_events:
        start_str = ev.get("start", {}).get("dateTime", "")
        end_str = ev.get("end", {}).get("dateTime", "")
        ev_date = datetime.strptime(start_str[:10], "%Y-%m-%d").date()
        pid = ev.get("extendedProperties", {}).get("private", {}).get("notion_page_id")
        
        is_trip_day = "2026-08-10" <= start_str[:10] <= "2026-08-12"
        is_past = ev_date < real_today
        
        conflict = False
        reason = ""
        
        if is_past or is_trip_day:
            conflict = True
            reason = "過期或參訪日"
        elif not pid or pid not in uncompleted_pids:
            conflict = True
            reason = "Notion 任務已完成或已刪除"
        else:
            start_dt = parse_iso(start_str)
            end_dt = parse_iso(end_str)
            
            if not is_inside_free_slots(start_dt, end_dt, free_slots):
                conflict = True
                reason = "不在可用自習空檔內 (可能已被手動修改或空檔變更)"
            else:
                due_str = todo_due_map.get(pid)
                if due_str and due_str != "無截止日":
                    try:
                        due_dt = datetime.strptime(due_str, "%Y-%m-%d")
                        if start_dt.date() > due_dt.date():
                            conflict = True
                            reason = "截止日期已提前至排程時間之前"
                    except:
                        pass
                
                if not conflict and last_end_time and start_dt < last_end_time:
                    conflict = True
                    reason = "與其他鎖定行程時間重疊"
                    
        if conflict:
            dr = requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{task_cal}/events/{ev['id']}", headers=gcal_h)
            if dr.status_code in [200, 204]:
                cleared += 1
                print(f"  [刪除衝突] {ev.get('summary')} ({reason})")
        else:
            already_scheduled_ids.add(pid)
            start_dt = parse_iso(start_str)
            end_dt = parse_iso(end_str)
            busy_slots.append((start_dt, end_dt))
            last_end_time = end_dt
            locked += 1
            print(f"  [鎖定行程] {ev.get('summary')} ({start_str[11:16]}~{end_str[11:16]})")
            
            try:
                res_notion = requests.get(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h)
                if res_notion.status_code == 200:
                    page_data = res_notion.json()
                    notion_date_prop = page_data.get("properties", {}).get("日期時間", {}).get("date")
                    notion_start = notion_date_prop.get("start") if notion_date_prop else None
                    if notion_start != start_str:
                        payload = {
                            "properties": {
                                "日期時間": {
                                    "date": {
                                        "start": start_str,
                                        "end": end_str
                                    }
                                }
                            }
                        }
                        requests.patch(f"https://api.notion.com/v1/pages/{pid}", headers=notion_h, json=payload)
                        print(f"  [Notion 更新時間] {ev.get('summary')} -> {start_str}")
            except Exception as ex:
                print(f"更新 Notion 日期時間失敗: {ex}")

print(f"已清除 {cleared} 筆衝突/過期排程，鎖定保留 {locked} 筆未來排程。")

# 扣除未來已鎖定排程時間
free_slots = subtract_intervals(free_slots, busy_slots)
print(f"扣除鎖定排程時間後，剩餘 {len(free_slots)} 個可用空檔。")

# ── 4. Filter todos ──
filtered_todos = []
for t in todos:
    if t["notion_page_id"] in already_scheduled_ids:
        continue
    if t["due"] == "無截止日" or not t["due"]:
        if OFFSET_DAYS == 0:
            filtered_todos.append(t)
    else:
        try:
            due_dt = datetime.strptime(t["due"], "%Y-%m-%d").date()
            if today <= due_dt <= window_end_date:
                filtered_todos.append(t)
        except Exception:
            if OFFSET_DAYS == 0:
                filtered_todos.append(t)

print(f"可用空檔數={len(free_slots)}，新待排程作業數={len(filtered_todos)}")

if not filtered_todos and not misc_todos:
    print(f"在 {today.strftime('%m/%d')} 至 {window_end_date.strftime('%m/%d')} 區間內無待排程的作業或雜項。")
    sys.exit(0)

schedule = []
if filtered_todos:
    MAX_TASKS_PER_WINDOW = 35
    if len(filtered_todos) > MAX_TASKS_PER_WINDOW:
        def sort_key(t):
            if t["due"] and t["due"] != "無截止日":
                try:
                    return datetime.strptime(t["due"], "%Y-%m-%d").date()
                except: pass
            return today + timedelta(days=999)
        filtered_todos.sort(key=sort_key)
        filtered_todos = filtered_todos[:MAX_TASKS_PER_WINDOW]
        print(f"任務數過多，已依截止日優先取前 {MAX_TASKS_PER_WINDOW} 筆送入 AI 排程。")

    slots_text = "\n".join(
        f"  - {parse_iso(fs['start']).strftime('%Y-%m-%d %H:%M')} ~ {parse_iso(fs['end']).strftime('%H:%M')} (可用 {(parse_iso(fs['end']) - parse_iso(fs['start'])).seconds // 60} 分鐘)"
        for fs in free_slots
    )
    
    todos_text = "\n".join(
        f"  - ID: {t['notion_page_id']} | [{t['type']}] {t['name']} | 科目:{t['subject']} | 截止:{t['due']} | 預估:{t['est_hr']}小時"
        for t in filtered_todos
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
    6. **等比例空檔分配**：請依照「總作業需求時間」與「總可用空檔時間」的比例，將作業時間均勻分散在有可用空檔的日子。假設此區間總可用空檔為 S 分鐘，待安排作業總時數為 T 分鐘，比例 r = T / S。若某天有 D 分鐘的可用空檔，則該天安排的總作業時間應儘量接近 D * r 分鐘（例如：2000 分鐘總空檔，700 分鐘作業，若某天有 200 分鐘空檔，則該天應排大約 70 分鐘 of 作業，其餘空檔留白）。若某天沒有可用空檔，則該天不可安排任何事項。
    7. **補習班作業特殊規則**：
       - 帶有 **Part 1** 的補習班作業（如 PC數學/物理/化學作業 Part 1）：請儘量安排在該作業**上完課當天或隔天**（例如：PC化學上課是週二，則 Part 1 盡量排在週二或週三）。
       - 帶有 **Part 2** 的補習班作業（如 PC數學/物理/化學作業 Part 2）：請儘量安排在**截止日（下一堂課）的前 1 天或當天早上**（例如：截止日是週二，則 Part 2 盡量排在週一或週二早上）。
    8. **科目內學習順序（由底層到高層）**：對於同科目且同主題的任務，在下方待辦清單中**排列在前面的項目（建立時間早，例如：單元1、基礎例題）必須比排列在後面的項目（建立時間晚，例如：練習、實驗題）先安排在較早的時間或日期**。請嚴格遵守這個先後學習順序。
    9. **科目交替穿插**：為了避免乏味，請儘量交替安排不同科目的作業（例如：化學 -> 數學 -> 物理 -> 化學），避免同一天連續好幾個工作塊或連續數天只排同一門科目。
    10. 請以 JSON 格式回覆，只輸出 JSON，不要有任何額外說明文字。
    11. **物理空檔限制 (嚴格限制)**：任何安排在特定可用空檔內的工作塊，其排程時長（結束時間減去開始時間）**絕對不可以大於該可用空檔的總長度**！例如，一個 30 分鐘的可用空檔絕不能塞入 50 分鐘的作業。如果作業所需時間大於空檔，你必須將其在 JSON 中拆分為較小的多個工作塊（例如拆分為一個 30 分鐘的子任務，其餘放在其他天），或改排到其他更大的空檔中。
    
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
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 16384,
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "object",
                "properties": {
                    "schedule": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "notion_page_id": {"type": "string"},
                                "name": {"type": "string"},
                                "date": {"type": "string"},
                                "start": {"type": "string"},
                                "end": {"type": "string"},
                                "subject": {"type": "string"},
                                "type": {"type": "string"}
                            },
                            "required": ["notion_page_id", "name", "date", "start", "end", "subject", "type"]
                        }
                    }
                },
                "required": ["schedule"]
            }
        }
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
else:
    print(f"在 {today.strftime('%m/%d')} 至 {window_end_date.strftime('%m/%d')} 區間內無待排程的作業，跳過 AI 規劃。")

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

# ── 6. Write Miscellaneous Deadlines directly to GCal ──────────────────
misc_success = 0
for t in misc_todos:
    pid = t["notion_page_id"]
    if pid in already_scheduled_ids:
        continue
    due_str = t["due"]
    if due_str != "無截止日" and due_str:
        try:
            due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
            if today <= due_dt <= window_end_date:
                end_dt = due_dt + timedelta(days=1)
                payload = {
                    "summary": t["name"],
                    "description": "[Life-Agent 雜項截止標記]",
                    "start": {"date": due_dt.strftime("%Y-%m-%d")},
                    "end": {"date": end_dt.strftime("%Y-%m-%d")},
                    "colorId": "8",  # Grey
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
                    print(f"  OK [雜項截止] {due_str} {t['name']}")
                    misc_success += 1
        except Exception as ex:
            print(f"  解析雜項截止日期失敗: {ex}")

print(f"\n[排程完成] 成功寫入 {success}/{len(schedule)} 個作業時間塊，以及 {misc_success} 個雜項截止標記！")

# ── 7. 清理已排程任務的 Telegram 沒寫完回報快取 ──
future_scheduled_ids = {block.get("notion_page_id") for block in schedule if block.get("notion_page_id")}
future_scheduled_ids.update(already_scheduled_ids)

inc_file = "C:/Users/ST/.gemini/antigravity-ide/brain/f9de8527-920e-4eaf-ae2b-5a4061a0a8a6/incomplete_reported.json"
if os.path.exists(inc_file):
    try:
        with open(inc_file, "r", encoding="utf-8") as f:
            reported_list = json.load(f)
        new_reported = [pid for pid in reported_list if pid not in future_scheduled_ids]
        with open(inc_file, "w", encoding="utf-8") as f:
            json.dump(new_reported, f, ensure_ascii=False, indent=2)
        print(f"已清理沒寫完回報快取，剩餘 {len(new_reported)} 筆追蹤中。")
    except Exception as ex:
        print(f"清理回報快取失敗: {ex}")

# ── 8. Sync active todos to Google Tasks ──
all_active_todos = todos + misc_todos
sync_todos_to_google_tasks(gcal_token, tasks_list_id, all_active_todos)
