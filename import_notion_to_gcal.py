import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta

# Load env variables from .env
env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

# Fix Windows console encoding issues
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except:
        pass

TOKEN_CACHE_FILE = ".gcal_token_cache.json"

def get_google_calendar_access_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                if cache.get("expires_at", 0) > time.time() + 60:
                    return cache.get("access_token")
        except:
            pass
            
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    
    if not client_id or not client_secret or not refresh_token:
        print("缺少 Google Calendar OAuth 憑證，無法取得 Access Token。")
        return None
        
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    try:
        res = requests.post(url, data=payload)
        res.raise_for_status()
        res_json = res.json()
        access_token = res_json.get("access_token")
        expires_in = res_json.get("expires_in", 3600)
        
        cache_data = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in
        }
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
            
        return access_token
    except Exception as e:
        print(f"更新 Google Calendar access token 失敗: {e}")
        return None

notion_token = os.environ.get("NOTION_TOKEN")
act_db_id = os.environ.get("NOTION_ACTIVITIES_DB_ID")
todo_db_id = os.environ.get("NOTION_TODO_ACTIVITIES_DB_ID")

if not notion_token or not act_db_id or not todo_db_id:
    print("錯誤: 缺少 Notion 驗證金鑰或資料庫 ID 設定！")
    sys.exit(1)

access_token = get_google_calendar_access_token()
if not access_token:
    print("錯誤: 無法取得 Google 日曆授權！")
    sys.exit(1)

# Helper to query Notion DB
notion_headers = {
    "Authorization": f"Bearer {notion_token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def query_notion_db(db_id):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    results = []
    has_more = True
    start_cursor = None
    
    while has_more:
        payload = {}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        res = requests.post(url, headers=notion_headers, json=payload)
        if res.status_code == 200:
            res_json = res.json()
            results.extend(res_json.get("results", []))
            has_more = res_json.get("has_more", False)
            start_cursor = res_json.get("next_cursor")
        else:
            print(f"查詢 Notion 資料庫失敗: {res.status_code} - {res.text}")
            break
    return results

def get_title(page, prop_name):
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    if prop.get("type") == "title" and prop.get("title"):
        return prop["title"][0]["text"]["content"]
    return ""

def get_select(page, prop_name):
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    if prop.get("type") == "select" and prop.get("select"):
        return prop["select"]["name"]
    return ""

def get_date(page, prop_name):
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    if prop.get("type") == "date" and prop.get("date"):
        start = prop["date"]["start"]
        end = prop["date"]["end"]
        return f"{start}/{end}" if end else start
    return None

def get_number(page, prop_name):
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    if prop.get("type") == "number":
        return prop.get("number")
    return None

# Google Calendar helpers
class_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_CLASS") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
study_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_STUDY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
task_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_TASK") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
activity_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
misc_calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_MISC") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"

gcal_headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

def clear_gcal_events(calendar_id, source_tag):
    print(f"正在清理日曆 {calendar_id} 中標記為 {source_tag} 的歷史行程...")
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    # Query future and recent events to clear
    time_min = (datetime.now() - timedelta(days=30)).isoformat() + "Z"
    params = {
        "timeMin": time_min,
        "singleEvents": "true",
        "maxResults": 250
    }
    try:
        res = requests.get(url, headers=gcal_headers, params=params)
        if res.status_code == 200:
            events = res.json().get("items", [])
            cleared = 0
            for ev in events:
                tag = ev.get("extendedProperties", {}).get("private", {}).get("source")
                if tag == source_tag:
                    del_url = f"{url}/{ev['id']}"
                    del_res = requests.delete(del_url, headers=gcal_headers)
                    if del_res.status_code in [200, 204]:
                        cleared += 1
            print(f"  成功清理 {cleared} 筆行程。")
        else:
            print(f"  清理日曆查詢失敗: {res.status_code}")
    except Exception as e:
        print(f"  清理行程異常: {e}")

# 1. 處理並匯入 Notion 活動/行程 (Activities DB) -> 活動日曆
clear_gcal_events(activity_calendar_id, "life-agent-activity")
act_pages = query_notion_db(act_db_id)
print(f"從 Notion 查詢到 {len(act_pages)} 筆活動項目...")

act_count = 0
for page in act_pages:
    name = get_title(page, "活動名稱")
    date_val = get_date(page, "日期")
    a_type = get_select(page, "類型") or "其他"
    
    if name and date_val:
        if "/" in date_val:
            parts = date_val.split("/")
            start_str = parts[0].strip()
            end_str = parts[1].strip()
        else:
            start_str = date_val.strip()
            end_str = start_str
            
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            end_dt = datetime.strptime(end_str, "%Y-%m-%d")
            end_plus_1 = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            
            payload = {
                "summary": name,
                "description": f"[Life-Agent 自動匯入] 類型: {a_type}",
                "start": {"date": start_str},
                "end": {"date": end_plus_1},
                "colorId": "10", # Basil
                "extendedProperties": {
                    "private": {
                        "source": "life-agent-activity"
                    }
                }
            }
            url_create = f"https://www.googleapis.com/calendar/v3/calendars/{activity_calendar_id}/events"
            res = requests.post(url_create, headers=gcal_headers, json=payload)
            if res.status_code == 200:
                print(f"  [活動] 成功匯入: {name} ({date_val})")
                act_count += 1
            else:
                print(f"  [活動] 匯入失敗 {name}: {res.status_code}")
        except Exception as e:
            print(f"  [活動] 處理異常 {name}: {e}")

# 2. 處理並匯入 Notion 待辦/作業 (To-Dos DB) -> 作業日曆 (僅匯入未完成者)
clear_gcal_events(task_calendar_id, "life-agent-todo-deadline")
todo_pages = query_notion_db(todo_db_id)
print(f"從 Notion 查詢到 {len(todo_pages)} 筆待辦項目...")

todo_count = 0
for page in todo_pages:
    name = get_title(page, "名稱")
    due_date = get_date(page, "截止或考試日期")
    t_type = get_select(page, "類型") or "作業"
    
    # 判斷是否已完成
    done = get_number(page, "已完成頁數/題數")
    total = get_number(page, "總頁數/題數")
    is_completed = (done is not None and total is not None and done >= total)
    
    if name and due_date and not is_completed:
        try:
            start_dt = datetime.strptime(due_date, "%Y-%m-%d")
            end_plus_1 = (start_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            
            payload = {
                "summary": f"⏰ 截止：{name}",
                "description": f"[Life-Agent 自動匯入待辦] 類型: {t_type}",
                "start": {"date": due_date},
                "end": {"date": end_plus_1},
                "colorId": "11", # Tomato
                "extendedProperties": {
                    "private": {
                        "source": "life-agent-todo-deadline"
                    }
                }
            }
            url_create = f"https://www.googleapis.com/calendar/v3/calendars/{task_calendar_id}/events"
            res = requests.post(url_create, headers=gcal_headers, json=payload)
            if res.status_code == 200:
                print(f"  [作業] 成功匯入: {name} (截止: {due_date})")
                todo_count += 1
            else:
                print(f"  [作業] 匯入失敗 {name}: {res.status_code}")
        except Exception as e:
            print(f"  [作業] 處理異常 {name}: {e}")

print(f"\n[匯入完成] 成功匯入 {act_count} 筆活動項目與 {todo_count} 筆未完成待辦截止日！")
