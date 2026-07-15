import os
import sys
import requests
import json
import io
import time
import pytz
from datetime import datetime, timedelta, date
from PIL import Image
import google.generativeai as genai
import re

TOKEN_CACHE_FILE = "d:/antigravity/life-agent/.gcal_token_cache.json"

def request_with_retry(method, url, retries=3, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504), **kwargs):
    for attempt in range(retries):
        try:
            res = requests.request(method, url, **kwargs)
            if res.status_code in status_forcelist:
                print(f"HTTP {res.status_code} 錯誤，進行第 {attempt + 1} 次重試...")
                time.sleep(backoff_factor * (2 ** attempt))
                continue
            return res
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"網路連線異常 {e}，進行第 {attempt + 1} 次重試...")
            time.sleep(backoff_factor * (2 ** attempt))
    return requests.request(method, url, **kwargs)

def safe_generate_content(model, *args, **kwargs):
    retries = 3
    backoff_factor = 1.0
    for attempt in range(retries):
        try:
            return model.generate_content(*args, **kwargs)
        except Exception as e:
            print(f"Gemini API 呼叫失敗 ({e})，進行第 {attempt + 1} 次重試...")
            time.sleep(backoff_factor * (2 ** attempt))
    return model.generate_content(*args, **kwargs)

def get_todo_duration(name, default_dur):
    import re
    match_min = re.search(r"\(需(\d+)分鐘\)", name)
    match_hr = re.search(r"\(需(\d+)小時\)", name)
    if match_min:
        return int(match_min.group(1))
    elif match_hr:
        return int(match_hr.group(1)) * 60
    return default_dur

def write_activity_to_gcal(name, date_val, a_type):
    _, _, _, activity_cal, _ = get_calendar_ids()
    calendar_id = activity_cal
    url_create = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
    
    if not date_val:
        return
        
    if "/" in date_val:
        parts = date_val.split("/")
        start_str = parts[0].strip()
        end_str = parts[1].strip()
    else:
        start_str = date_val.strip()
        end_str = start_str
        
    try:
        from datetime import datetime, timedelta
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d")
        end_plus_1 = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
        payload = {
            "summary": name,
            "description": f"[Life-Agent 自動生成] 類型: {a_type}",
            "start": {"date": start_str},
            "end": {"date": end_plus_1},
            "colorId": "10",  # Basil (Green) for activities
            "extendedProperties": {
                "private": {
                    "source": "life-agent-activity"
                }
            }
        }
        res = make_gcal_request("POST", url_create, json=payload)
        if res and res.status_code == 200:
            print(f"已同步活動至 Google Calendar: {name}")
        else:
            print(f"同步活動至 Google Calendar 失敗: {res.status_code if res else 'No Response'}")
    except Exception as e:
        print(f"同步活動至 Google Calendar 異常: {e}")

def get_calendar_ids():
    class_id = os.environ.get("GOOGLE_CALENDAR_ID_CLASS") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    study_id = os.environ.get("GOOGLE_CALENDAR_ID_STUDY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    task_id = os.environ.get("GOOGLE_CALENDAR_ID_TASK") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    activity_id = os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    misc_id = os.environ.get("GOOGLE_CALENDAR_ID_MISC") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
    return class_id, study_id, task_id, activity_id, misc_id

def write_misc_to_gcal(name, date_val):
    _, _, _, _, misc_cal = get_calendar_ids()
    url_create = f"https://www.googleapis.com/calendar/v3/calendars/{misc_cal}/events"
    
    try:
        from datetime import datetime, timedelta
        dt = datetime.strptime(date_val, "%Y-%m-%d")
        tomorrow_str = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
        payload = {
            "summary": name,
            "description": "[Life-Agent 自動生成] 雜項提醒",
            "start": {"date": date_val},
            "end": {"date": tomorrow_str},
            "colorId": "8", # Graphite for misc
            "extendedProperties": {
                "private": {
                    "source": "life-agent-misc"
                }
            }
        }
        res = make_gcal_request("POST", url_create, json=payload)
        if res and res.status_code == 200:
            print(f"已同步雜項提醒至 Google Calendar: {name}")
        else:
            print(f"同步雜項至 Google Calendar 失敗: {res.status_code if res else 'No Response'}")
    except Exception as e:
        print(f"同步雜項至 Google Calendar 異常: {e}")


def get_google_calendar_access_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("expires_at", 0) > time.time() + 300:
                return cache.get("access_token")
        except Exception as e:
            print(f"讀取 Token 快取失敗: {e}")
            
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    
    if not client_id or not client_secret or not refresh_token:
        print("未完整設定 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 或 GOOGLE_REFRESH_TOKEN，將跳過 Google Calendar。")
        return None
        
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    try:
        res = request_with_retry("POST", url, data=payload)
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
            
        print("已重新整理並快取 Google Calendar access token。")
        return access_token
    except Exception as e:
        print(f"更新 Google Calendar access token 失敗: {e}")
        return None

def make_gcal_request(method, url, headers=None, **kwargs):
    if headers is None:
        headers = {}
        
    token = get_google_calendar_access_token()
    if not token:
        return None
        
    headers["Authorization"] = f"Bearer {token}"
    
    try:
        res = request_with_retry(method, url, headers=headers, **kwargs)
        if res.status_code in [400, 401]:
            print(f"Google Calendar API 回傳 {res.status_code}，嘗試清除快取並重新整理 Token...")
            if os.path.exists(TOKEN_CACHE_FILE):
                try:
                    os.remove(TOKEN_CACHE_FILE)
                except:
                    pass
            token = get_google_calendar_access_token()
            if not token:
                return res
            headers["Authorization"] = f"Bearer {token}"
            res = request_with_retry(method, url, headers=headers, **kwargs)
        return res
    except Exception as e:
        print(f"Google Calendar HTTP 請求失敗: {e}")
        return None

def delete_google_calendar_event(access_token, calendar_id, event_id):
    url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"
    try:
        res = make_gcal_request("DELETE", url)
        return res and res.status_code == 204
    except Exception as e:
        print(f"刪除 Google Calendar 事件失敗 {event_id}: {e}")
        return False

def safe_load_json(text):
    if not text:
        return {}
    text_clean = text.strip()
    if text_clean.startswith("```"):
        lines = text_clean.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text_clean = "\n".join(lines).strip()
    if text_clean.startswith("```json"):
        text_clean = text_clean[7:].strip()
    if text_clean.startswith("```"):
        text_clean = text_clean[3:].strip()
    if text_clean.endswith("```"):
        text_clean = text_clean[:-3].strip()
    return json.loads(text_clean)


# 解決 Windows 控制台編碼問題
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# 嘗試自本地的 .env 檔案載入環境變數
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
# Initialize holiday cache on startup
import holiday_utils
holiday_utils.refresh_cache_sync()
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip()

# 讀取環境變數
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# Helper for Taipei timezone
_TAIPEI_TZ = pytz.timezone('Asia/Taipei')

# Notion Database IDs
FIXED_SCHEDULE_DB_ID = os.environ.get("NOTION_FIXED_SCHEDULE_DB_ID")
TODO_ACTIVITIES_DB_ID = os.environ.get("NOTION_TODO_ACTIVITIES_DB_ID")
ACTIVITIES_DB_ID = os.environ.get("NOTION_ACTIVITIES_DB_ID")
BOOK_TRACKER_DB_ID = os.environ.get("NOTION_BOOK_TRACKER_DB_ID")
LEDGER_DB_ID = os.environ.get("NOTION_LEDGER_DB_ID")
WEEKLY_CALENDAR_DB_ID = os.environ.get("NOTION_WEEKLY_CALENDAR_DB_ID")
TEMP_INBOX_DB_ID = os.environ.get("NOTION_TEMP_INBOX_DB_ID")

# Notion API Headers
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# 預估時間基準值 (分鐘)
DEFAULT_DURATION = {
    "作業": 30,
    "小考": 60,
    "段考": 120,
    "回條": 10,
    "報名表": 15,
    "活動": 90
}

# 初始化 Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ==================== Notion API 輔助函式 ====================

def query_database_all(database_id, filter_payload=None):
    if not database_id:
        print("警告: 查詢的資料庫 ID 為空！")
        return []
    results = []
    has_more = True
    next_cursor = None
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    
    while has_more:
        payload = filter_payload.copy() if filter_payload else {}
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        res = request_with_retry("POST", url, headers=HEADERS, json=payload)
        res.raise_for_status()
        data = res.json()
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        
    return results

def create_page(database_id, properties):
    if not database_id:
        print("警告: 建立頁面的資料庫 ID 為空！")
        return {}
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"database_id": database_id},
        "properties": properties
    }
    res = request_with_retry("POST", url, headers=HEADERS, json=data)
    res.raise_for_status()
    return res.json()

def update_page(page_id, properties):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": properties
    }
    res = request_with_retry("PATCH", url, headers=HEADERS, json=data)
    res.raise_for_status()
    return res.json()

def delete_page(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {"archived": True}
    res = request_with_retry("PATCH", url, headers=HEADERS, json=data)
    res.raise_for_status()
    return res.json()

# ==================== Notion 欄位解析輔助函式 ====================

def get_title(page, property_name):
    prop = page.get("properties", {}).get(property_name, {})
    title_list = prop.get("title", [])
    if title_list:
        return title_list[0].get("text", {}).get("content", "")
    return ""

def get_rich_text(page, property_name):
    prop = page.get("properties", {}).get(property_name, {})
    text_list = prop.get("rich_text", [])
    if text_list:
        return text_list[0].get("text", {}).get("content", "")
    return ""

def get_select(page, property_name):
    prop = page.get("properties", {}).get(property_name, {})
    select_obj = prop.get("select")
    if select_obj:
        return select_obj.get("name")
    return None

def get_number(page, property_name):
    return page.get("properties", {}).get(property_name, {}).get("number")

def get_checkbox(page, property_name):
    return page.get("properties", {}).get(property_name, {}).get("checkbox", False)

def get_date(page, property_name):
    prop = page.get("properties", {}).get(property_name, {})
    date_obj = prop.get("date")
    if date_obj:
        return date_obj.get("start")
    return None

def get_first_file_url(page, property_name):
    prop = page.get("properties", {}).get(property_name, {})
    files = prop.get("files", [])
    if not files:
        return None
    first_file = files[0]
    if first_file.get("type") == "file":
        return first_file.get("file", {}).get("url")
    elif first_file.get("type") == "external":
        return first_file.get("external", {}).get("url")
    return None

def get_bot_user_id():
    if not NOTION_TOKEN:
        return None
    try:
        url = "https://api.notion.com/v1/users/me"
        res = request_with_retry("GET", url, headers=HEADERS)
        if res.status_code == 200:
            return res.json().get("id")
    except Exception as e:
        print(f"取得 Bot User ID 失敗: {e}")
    return None

def is_task_completed(page):
    completed_val = get_number(page, "已完成頁數/題數")
    total_val = get_number(page, "總頁數/題數")
    
    if completed_val is None:
        completed_val = 0
    if total_val is None:
        total_val = 1
        
    return completed_val >= total_val

# ==================== Telegram Bot ====================

def send_telegram_message(message, reply_markup=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，無法發送 Telegram 通知。")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = request_with_retry("POST", url, json=payload)
        res.raise_for_status()
        print("Telegram 訊息發送成功。")
    except Exception as e:
        print(f"Telegram 訊息發送失敗: {e}")

def run_github_action(workflow_file, ref='main'):
    token = os.getenv('GITHUB_TOKEN')
    repo = os.getenv('GITHUB_REPOSITORY')
    if not token or not repo:
        return 'Missing GITHUB_TOKEN or GITHUB_REPOSITORY env vars.'
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow_file}/dispatches"
    payload = {
        'ref': ref
    }
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    }
    try:
        res = request_with_retry("POST", url, json=payload, headers=headers)
        res.raise_for_status()
        return f'Success (status {res.status_code})'
    except Exception as e:
        return f'Error: {e}'

def get_telegram_file_url(file_id):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
    res = request_with_retry("GET", url)
    res.raise_for_status()
    file_path = res.json().get("result", {}).get("file_path")
    if file_path:
        return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    return None

def parse_hw_command(text, today_str):
    raw_content = text[3:].strip()
    if not raw_content or raw_content == "#" or raw_content.replace("#", "").strip() == "":
        return {"name": "#", "subject": "#", "due_date": "#"}
    
    try:
        prompt = f"""
        請幫我從以下功課/待辦事項敘述中，提取出指定格式的欄位值：
        1. name: 功課名稱或描述（使用繁體中文）。如果敘述中有包含科目名稱，請將科目從名稱中抽離（例如「英文閱讀報告」-> name為「閱讀報告」）。如果內容只包含 "#"，請填寫 "#"。
        2. subject: 相關科目（例如：數學、英文、化學、國文、物理等。若無或無法辨識請填 "無"。若只包含 "#"，請填寫 "#"）。
        3. due_date: 截止日期（格式必須為 YYYY-MM-DD）。
           - 如果敘述中提到的是月份/日期（如 6/21、6/22 晚上 6:00 前、6/28 晚上 12:00 等），請結合今天日期 {today_str} 來推理出正確的西元年月日。
           - 如果提到相對日期（如明天、下週一），也請結合今天日期 {today_str} 推理出正確的西元年月日。
           - 若未提及截止日期，或者內容只包含 "#"，請填寫 "#"。

        待解析敘述：
        "{raw_content}"

        請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
        {{
          "name": "功課名稱",
          "subject": "數學",
          "due_date": "2026-06-22"
        }}
        """
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json"})
        return safe_load_json(response.text)
    except Exception as e:
        print(f"Gemini parse_hw_command 失敗: {e}")
        parts = raw_content.split()
        sub = "無"
        if len(parts) >= 2:
            sub = parts[-1]
            nm = " ".join(parts[:-1])
        else:
            nm = raw_content
        return {"name": nm, "subject": sub, "due_date": "#"}

def parse_finish_command(text):
    raw_content = text[7:].strip()
    if not raw_content or raw_content == "#" or raw_content.replace("#", "").strip() == "":
        return {"name": "#", "actual_time": "#"}
    
    try:
        prompt = f"""
        請幫我從以下完成事項的敘述中，提取出：
        1. name: 待辦事項名稱或關鍵字（用以在資料庫中比對尋找。若只包含 "#"，請填寫 "#"）。
        2. actual_time: 實際耗時（必須是表示分鐘的整數數字字串，例如 "60"）。若敘述中提到時間（如「耗時 1 小時」、「寫了 90 分鐘」），請換算成以分鐘為單位的整數。若敘述中沒有提及耗時，請填寫 "#"。

        待解析敘述：
        "{raw_content}"

        請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
        {{
          "name": "事項名稱",
          "actual_time": "60"
        }}
        """
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json"})
        return safe_load_json(response.text)
    except Exception as e:
        print(f"Gemini parse_finish_command 失敗: {e}")
        parts = raw_content.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            return {"name": " ".join(parts[:-1]), "actual_time": parts[-1]}
        return {"name": raw_content, "actual_time": "#"}

def parse_act_command(text, today_str):
    raw_content = text[4:].strip()
    if not raw_content or raw_content == "#" or raw_content.replace("#", "").strip() == "":
        return {"name": "#", "date": "#"}
    
    try:
        prompt = f"""
        請幫我從以下活動敘述中，提取出：
        1. name: 活動名稱（使用繁體中文。若只包含 "#"，請填寫 "#"）。
        2. date: 活動日期（格式必須為 YYYY-MM-DD）。
           - 如果敘述中提到的是月份/日期（如 7/7、8/1 等），請結合今天日期 {today_str} 來推理出正確的西元年月日。
           - 如果提到相對日期（如明天、下週一），也請結合今天日期 {today_str} 推理出正確的西元年月日。
           - 若未提及活動日期，或者內容只包含 "#"，請填寫 "#"。

        待解析敘述：
        "{raw_content}"

        請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
        {{
          "name": "活動名稱",
          "date": "2026-07-07"
        }}
        """
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json"})
        return safe_load_json(response.text)
    except Exception as e:
        print(f"Gemini parse_act_command 失敗: {e}")
        return {"name": raw_content, "date": "#"}

def is_valid_date_format(date_str):
    if not date_str:
        return False
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return True
    except:
        return False

SUBJECT_WRITE_BUDGETS = {
    "國文": 30,
    "數學": 10,
    "英文": 0,
    "物理": 20,
    "化學": 20
}

def get_subject_budget(event_name):
    if not event_name:
        return 0
    for sub in SUBJECT_WRITE_BUDGETS:
        if sub in event_name:
            return SUBJECT_WRITE_BUDGETS[sub]
    return 0

def get_subject_budget_key(event_name):
    if not event_name:
        return None
    for sub in ["國文", "數學", "英文", "物理", "化學"]:
        if sub in event_name:
            return sub
    return None

def process_telegram_commands(today_dt):
    if not TELEGRAM_BOT_TOKEN:
        print("未設定 TELEGRAM_BOT_TOKEN，跳過指令處理。")
        return
        
    print("正在檢查 Telegram 新指令...")
    today_str = today_dt.strftime("%Y-%m-%d")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        res = request_with_retry("GET", url)
        res.raise_for_status()
        updates = res.json().get("result", [])
    except Exception as e:
        print(f"取得 Telegram 更新失敗: {e}")
        return

    if not updates:
        print("沒有新的 Telegram 指令。")
        return

    max_update_id = 0
    for update in updates:
        update_id = update["update_id"]
        if update_id > max_update_id:
            max_update_id = update_id
            
        callback_query = update.get("callback_query")
        if callback_query:
            cq_id = callback_query.get("id")
            data = callback_query.get("data", "")
            if data.startswith("bh:") or data.startswith("bs:"):
                short_id = data.split(":", 1)[1]
                page_id = f"{short_id[:8]}-{short_id[8:12]}-{short_id[12:16]}-{short_id[16:20]}-{short_id[20:]}"
                try:
                    res_notion = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS)
                    if res_notion.status_code == 200:
                        page_data = res_notion.json()
                        current_loc = get_select(page_data, "目前位置")
                        target_loc = "在家裡" if data.startswith("bh:") else "在學校"
                        if current_loc == target_loc:
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                                "callback_query_id": cq_id,
                                "text": f"狀態已更新過囉！目前已是「{current_loc}」"
                            })
                            continue
                        update_page(page_id, {"目前位置": {"select": {"name": target_loc}}})
                        update_page(page_id, {"Currently_At": {"select": {"name": target_loc}}})
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                            "callback_query_id": cq_id,
                            "text": f"已將課本位置更新為：{target_loc}"
                        })
                        send_telegram_message(f"已確認更新：{get_title(page_data, '科目/物品名稱')} -> {target_loc}")
                    else:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                            "callback_query_id": cq_id,
                            "text": "查無此書籍項目"
                        })
                except Exception as ex:
                    print(f"更新失敗: {ex}")
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                        "callback_query_id": cq_id,
                        "text": f"更新出錯: {ex}"
                    })
            elif data.startswith("td:"):
                short_id = data.split(":", 1)[1]
                page_id = f"{short_id[:8]}-{short_id[8:12]}-{short_id[12:16]}-{short_id[16:20]}-{short_id[20:]}"
                try:
                    res_notion = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=HEADERS)
                    if res_notion.status_code == 200:
                        page_data = res_notion.json()
                        done_val = get_number(page_data, "已完成頁數/題數")
                        total_val = get_number(page_data, "總頁數/題數") or 1
                        if done_val is not None and done_val >= total_val:
                            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                                "callback_query_id": cq_id,
                                "text": "此作業早已完成了！"
                            })
                            continue
                        update_page(page_id, {"已完成頁數/題數": {"number": total_val}})
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                            "callback_query_id": cq_id,
                            "text": "已將作業標記為完成！"
                        })
                        send_telegram_message(f"已確認完成作業：{get_title(page_data, '名稱')}")
                    else:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                            "callback_query_id": cq_id,
                            "text": "查無此作業項目"
                        })
                except Exception as ex:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery", json={
                        "callback_query_id": cq_id,
                        "text": f"更新出錯: {ex}"
                    })
            continue

        message = update.get("message")
        if not message:
            continue
            
        text = message.get("text") or message.get("caption") or ""
        text = text.strip()
        if not text:
            continue
        # Handle manual refresh command
        if text.startswith('/refresh_holidays'):
            holiday_utils.refresh_cache_sync()
            send_telegram_message('Holiday cache refreshed.')
            continue
                # GitHub Action trigger disabled
            
        # Extract optional time (HH:MM) from the command text
        time_match = re.search(r"(\d{1,2}:\d{2})", text)
        time_str = time_match.group(1) if time_match else None
        cmd_type = None
        if text.startswith("@hw"):
            cmd_type = "hw"
        elif text.startswith("@finish"):
            cmd_type = "finish"
        elif text.startswith("@act"):
            cmd_type = "act"
        elif text.startswith("@calendar") or text.startswith("@schedule"):
            cmd_type = "calendar"
        else:
            # Generic entry handling: Call Gemini to route and parse the message!
            try:
                res_route = route_and_parse_natural_text(text, today_str)
                action = res_route.get("action")
                data = res_route.get("data", {})
                
                if action == "add_todo":
                    name = data.get("name")
                    subject = data.get("subject") or "無"
                    due_date = data.get("due_date")
                    t_type = data.get("type") or "作業"
                    
                    if not name or name == "#":
                        name = "未命名待辦"
                    if t_type not in ["作業", "小考", "段考", "回條", "報名表"]:
                        t_type = "作業"
                    
                    properties = {
                        "名稱": {"title": [{"text": {"content": name}}]},
                        "類型": {"select": {"name": t_type}},
                        "相關科目": {"rich_text": [{"text": {"content": subject}}]}
                    }
                    if due_date and is_valid_date_format(due_date):
                        properties["截止或考試日期"] = {"date": {"start": due_date.strip()}}
                        
                    create_page(TODO_ACTIVITIES_DB_ID, properties)
                    due_msg = f"，截止日期：{due_date}" if (due_date and is_valid_date_format(due_date)) else ""
                    send_telegram_message(f"已自動分析並新增待辦：{name} (科目: {subject}{due_msg})")
                    
                elif action == "complete_todo":
                    name = data.get("name") or text
                    target = find_notion_todo_fuzzy(name)
                    if target:
                        total_pages = get_number(target, "總頁數/題數") or 1
                        time_spent = None
                        if data.get("actual_time") and data.get("actual_time") != "#":
                            try:
                                time_spent = int(data.get("actual_time"))
                            except:
                                pass
                        update_properties = {
                            "已完成頁數/題數": {"number": total_pages}
                        }
                        if time_spent is not None:
                            update_properties["實際耗時"] = {"number": time_spent}
                        update_page(target["id"], update_properties)
                        time_msg = f"，耗時 {time_spent} 分鐘" if time_spent is not None else ""
                        send_telegram_message(f"已將待辦【{get_title(target, '名稱')}】標記為完成{time_msg}。")
                    else:
                        send_telegram_message(f"找不到符合「{name}」的未完成待辦事項。")
                        
                elif action == "incomplete_todo":
                    name = data.get("name") or text
                    target = find_notion_todo_fuzzy(name)
                    if target:
                        pid = target["id"]
                        inc_file = "C:/Users/ST/.gemini/antigravity-ide/brain/f9de8527-920e-4eaf-ae2b-5a4061a0a8a6/incomplete_reported.json"
                        import os, json
                        reported_list = []
                        if os.path.exists(inc_file):
                            try:
                                with open(inc_file, "r", encoding="utf-8") as f:
                                    reported_list = json.load(f)
                            except:
                                pass
                        
                        if pid not in reported_list:
                            reported_list.append(pid)
                            with open(inc_file, "w", encoding="utf-8") as f:
                                json.dump(reported_list, f, ensure_ascii=False, indent=2)
                        
                        update_page(pid, {"已完成頁數/題數": {"number": 0}})
                        send_telegram_message(f"已記錄待辦【{get_title(target, '名稱')}】為未完成，將為您重新排入之後的行程！")
                    else:
                        send_telegram_message(f"找不到符合「{name}」的待辦事項。")
                        
                elif action == "add_activity":
                    name = data.get("name") or "未命名活動"
                    date_val = data.get("date") or today_str
                    a_type = data.get("type") or "其他"
                    
                    start_date = date_val.strip()
                    end_date = None
                    if "/" in date_val:
                        parts = date_val.split("/")
                        start_date = parts[0].strip()
                        end_date = parts[1].strip()
                        
                    if not is_valid_date_format(start_date):
                        start_date = today_str
                    if end_date and not is_valid_date_format(end_date):
                        end_date = None
                        
                    date_prop = {"start": start_date}
                    if end_date:
                        date_prop["end"] = end_date
                        
                    properties = {
                        "活動名稱": {"title": [{"text": {"content": name}}]},
                        "日期": {"date": date_prop},
                        "類型": {"select": {"name": a_type}}
                    }
                    create_page(ACTIVITIES_DB_ID, properties)
                    write_activity_to_gcal(name, date_val, a_type)
                    range_msg = f"{start_date} 至 {end_date}" if end_date else start_date
                    send_telegram_message(f"已自動分析並新增活動：{name} (日期: {range_msg}, 類型: {a_type})，且已同步至 Google Calendar。")
                    
                elif action == "add_expense":
                    name = data.get("name") or "未分類消費"
                    amount = data.get("amount") or 0
                    cat = data.get("category") or "飲食"
                    
                    try:
                        amount = int(amount)
                    except:
                        amount = 0
                    if cat not in ["飲食", "交通", "娛樂", "學習"]:
                        cat = "飲食"
                    
                    properties = {
                        "項目名稱": {"title": [{"text": {"content": name}}]},
                        "金額": {"number": amount},
                        "分類": {"select": {"name": cat}},
                        "日期": {"date": {"start": today_str}}
                    }
                    create_page(LEDGER_DB_ID, properties)
                    send_telegram_message(f"已自動記帳：{name}，金額：{amount} 元 (分類: {cat})")
                    
                else:
                    # generic_todo or fallback (雜項備忘)
                    name = data.get("name") or text
                    if TEMP_INBOX_DB_ID:
                        properties = {
                            "內容": {"title": [{"text": {"content": f"雜項:{name}"}}]},
                            "日期": {"date": {"start": today_str}}
                        }
                        create_page(TEMP_INBOX_DB_ID, properties)
                        send_telegram_message(f"已記下雜項提醒：{name}。將於深夜通知時提醒您！")
                    else:
                        send_telegram_message(f"暫存區未設定，無法記錄雜項：{name}")
                    
            except Exception as e:
                print(f"自動路由分析失敗: {e}")
                # Fallback to simple title extraction
                properties = {
                    "名稱": {"title": [{"text": {"content": text}}]},
                    "類型": {"select": {"name": "作業"}}
                }
                create_page(TODO_ACTIVITIES_DB_ID, properties)
                send_telegram_message(f"已新增通用待辦（解析失敗備份）：{text}")
            continue
            
        print(f"收到指令: {text}")
        
        file_id = None
        file_url = None
        file_bytes = None
        
        if "photo" in message:
            file_id = message["photo"][-1]["file_id"]
        elif "document" in message:
            file_id = message["document"]["file_id"]
            
        if file_id:
            try:
                file_url = get_telegram_file_url(file_id)
                if file_url:
                    resp = request_with_retry("GET", file_url)
                    resp.raise_for_status()
                    file_bytes = resp.content
            except Exception as e:
                print(f"下載 Telegram 附件失敗: {e}")

        try:
            if cmd_type == "hw":
                # Extract optional time at end of command
                time_match = None
                if text.strip().endswith(')') is False:
                    time_match = re.search(r"(\d{1,2}:\d{2})$", text.strip())
                time_str = time_match.group(1) if time_match else None
                cmd_data = parse_hw_command(text, today_str)
                if cmd_data:
                    name = cmd_data["name"].strip()
                    subject = cmd_data["subject"].strip()
                    due_date = cmd_data["due_date"].strip()
                    time_str = None
                    
                    if (name == "#" or subject == "#" or due_date == "#") and file_bytes:
                        try:
                            res_json = analyze_todo_photo_bytes(file_bytes, today_str)
                            if name == "#": name = res_json.get("name", "未命名事項")
                            if subject == "#": subject = res_json.get("subject", "無")
                            if due_date == "#": due_date = res_json.get("due_date", today_str)
                        except Exception as gem_err:
                            print(f"Gemini 輔助提取待辦失敗: {gem_err}")
                            if name == "#": name = "未命名事項"
                            if subject == "#": subject = "無"
                            if due_date == "#": due_date = today_str
                    else:
                        if name == "#": name = "未命名事項"
                        if subject == "#": subject = "無"
                        if due_date == "#": due_date = today_str
                    
                    properties = {
                        "名稱": {"title": [{"text": {"content": name}}]},
                        "類型": {"select": {"name": "作業"}},
                        "截止或考試日期": {"date": {"start": iso_datetime if time_str else due_date}},
                        "相關科目": {"rich_text": [{"text": {"content": subject}}]},
                        "總頁數/題數": {"number": 1},
                        "已完成頁數/題數": {"number": 0}
                    }
                    if file_url:
                        properties["照片上傳"] = {"files": [{"name": "Telegram Photo", "type": "external", "external": {"url": file_url}}]}
                    create_page(TODO_ACTIVITIES_DB_ID, properties)
                    send_telegram_message(f"已成功新增待辦：{name} (科目: {subject}, 截止: {due_date}, 時間: {time_str if time_str else '無'} )")

            elif cmd_type == "finish":
                cmd_data = parse_finish_command(text)
                if cmd_data:
                    name = cmd_data["name"]
                    actual_time = cmd_data["actual_time"]
                    
                    target_row = find_notion_todo_fuzzy(name)
                    if target_row:
                        total_pages = get_number(target_row, "總頁數/題數") or 1
                        time_spent = 30
                        if actual_time.isdigit():
                            time_spent = int(actual_time)
                            
                        update_properties = {
                            "已完成頁數/題數": {"number": total_pages},
                            "實際耗時": {"number": time_spent}
                        }
                        update_page(target_row["id"], update_properties)
                        send_telegram_message(f"已將待辦【{get_title(target_row, '名稱')}】標記為完成，耗時 {time_spent} 分鐘。")
                    else:
                        send_telegram_message(f"找不到符合「{name}」的未完成待辦事項。")

            elif cmd_type == "act":
                cmd_data = parse_act_command(text, today_str)
                if cmd_data:
                    name = cmd_data["name"]
                    date_val = cmd_data["date"]
                    
                    if (name == "#" or date_val == "#") and file_bytes:
                        try:
                            res_json = analyze_activity_brochure_bytes(file_bytes, name if name != "#" else "")
                            events = res_json.get("events", [])
                            if events:
                                first_event = events[0]
                                act_name = first_event.get("name", "未命名活動")
                                act_type = first_event.get("type", "其他")
                                act_date = first_event.get("date", today_str)
                                act_note = first_event.get("note", "")
                                
                                properties = {
                                    "活動名稱": {"title": [{"text": {"content": act_name}}]},
                                    "類型": {"select": {"name": act_type}},
                                    "日期": {"date": {"start": act_date}},
                                    "備註": {"rich_text": [{"text": {"content": act_note}}]}
                                }
                                if file_url:
                                    properties["簡章上傳"] = {"files": [{"name": "Telegram Brochure", "type": "external", "external": {"url": file_url}}]}
                                    
                                create_page(ACTIVITIES_DB_ID, properties)
                                send_telegram_message(f"已成功由簡章解析並新增主活動：{act_name} (日期: {act_date})")
                                
                                for event in events[1:]:
                                    new_row_properties = {
                                        "活動名稱": {"title": [{"text": {"content": event.get("name", "未命名活動")}}]},
                                        "類型": {"select": {"name": event.get("type", "其他")}},
                                        "日期": {"date": {"start": event.get("date", today_str)}},
                                        "備註": {"rich_text": [{"text": {"content": f"由 {act_name} 簡章自動生成\n---\n系統提取資訊：{event.get('note', '')}"}}]}
                                    }
                                    create_page(ACTIVITIES_DB_ID, new_row_properties)
                                    print(f"已新增活動事件: {event.get('name')}")
                            else:
                                send_telegram_message("未能從簡章中提取出任何符合身分之活動。")
                        except Exception as gem_err:
                            print(f"Gemini 輔助提取簡章失敗: {gem_err}")
                            send_telegram_message("由簡章分析活動失敗。")
                    else:
                        if name == "#": name = "未命名活動"
                        if date_val == "#": date_val = today_str
                        
                        properties = {
                            "活動名稱": {"title": [{"text": {"content": name}}]},
                            "日期": {"date": {"start": date_val}},
                            "類型": {"select": {"name": "其他"}}
                        }
                        if file_url:
                            properties["簡章上傳"] = {"files": [{"name": "Telegram Brochure", "type": "external", "external": {"url": file_url}}]}
                            
                        create_page(ACTIVITIES_DB_ID, properties)
                        send_telegram_message(f"已成功新增活動：{name} (日期: {date_val})")
            
            elif cmd_type == "calendar":
                res_json = None
                if file_bytes:
                    try:
                        res_json = analyze_calendar_image_bytes(file_bytes, today_str)
                    except Exception as gem_err:
                        print(f"Gemini analyze_calendar_image_bytes 失敗: {gem_err}")
                        send_telegram_message(f"分析行事曆圖片失敗: {gem_err}")
                else:
                    # Strip command prefix
                    raw_content = text
                    if raw_content.startswith("@calendar"):
                        raw_content = raw_content[9:].strip()
                    elif raw_content.startswith("@schedule"):
                        raw_content = raw_content[9:].strip()
                    if raw_content:
                        try:
                            res_json = analyze_calendar_text(raw_content, today_str)
                        except Exception as gem_err:
                            print(f"Gemini analyze_calendar_text 失敗: {gem_err}")
                            send_telegram_message(f"分析行事曆文字失敗: {gem_err}")
                            
                if res_json:
                    fixed_list = res_json.get("fixed_schedule", [])
                    events_list = res_json.get("weekly_events", [])
                    
                    fixed_added = 0
                    events_added = 0
                    
                    # 1. 寫入固定課表
                    for item in fixed_list:
                        sub = item.get("subject")
                        w = item.get("weekday")
                        t_range = item.get("time_range")
                        vac = item.get("is_vacation") or "暑假"
                        if sub and w and t_range:
                            # 檢查是否已存在
                            check_query = {
                                "filter": {
                                    "and": [
                                        {"property": "科目名稱", "title": {"equals": sub}},
                                        {"property": "星期", "number": {"equals": int(w)}},
                                        {"property": "作息類型", "select": {"equals": vac}}
                                    ]
                                }
                            }
                            existing = query_database_all(FIXED_SCHEDULE_DB_ID, check_query)
                            if not existing:
                                create_page(FIXED_SCHEDULE_DB_ID, {
                                    "科目名稱": {"title": [{"text": {"content": sub}}]},
                                    "星期": {"number": int(w)},
                                    "時間段": {"rich_text": [{"text": {"content": t_range}}]},
                                    "作息類型": {"select": {"name": vac}},
                                    "是否可寫作業": {"checkbox": False}
                                })
                                fixed_added += 1
                                
                    # 2. 寫入一次性行程與請假/補課 to Google Calendar
                    access_token = get_google_calendar_access_token()
                    if not access_token:
                        print("無法取得 Google Calendar Access Token，跳過匯入。")
                    else:
                        class_calendar_id, study_calendar_id, task_calendar_id, _, _ = get_calendar_ids()
                        dates_to_clear = {e.get("date") for e in events_list if e.get("date")}
                        cals_to_clear = {class_calendar_id, study_calendar_id, task_calendar_id}
                        for d in dates_to_clear:
                            time_min = f"{d}T00:00:00+08:00"
                            time_max = f"{d}T23:59:59+08:00"
                            params = {
                                "timeMin": time_min,
                                "timeMax": time_max,
                                "singleEvents": "true"
                            }
                            for cal_id in cals_to_clear:
                                url_list = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
                                res_list = make_gcal_request("GET", url_list, params=params)
                                if res_list and res_list.status_code == 200:
                                    for ev_gcal in res_list.json().get("items", []):
                                        is_bot = (
                                            ev_gcal.get("extendedProperties", {}).get("private", {}).get("source") in ["life-agent", "life-agent-ai-scheduled"] or
                                            "[Life-Agent 自動生成]" in (ev_gcal.get("description") or "")
                                        )
                                        if is_bot:
                                            delete_google_calendar_event(access_token, cal_id, ev_gcal["id"])
                                        
                        for ev in events_list:
                            ev_date = ev.get("date")
                            ev_name = ev.get("name")
                            ev_start = ev.get("start")
                            ev_end = ev.get("end")
                            ev_type = ev.get("type") or "上課"
                            if ev_date and ev_name and ev_start and ev_end:
                                start_iso = f"{ev_date}T{ev_start}:00+08:00"
                                end_iso = f"{ev_date}T{ev_end}:00+08:00"
                                
                                color_id = "9"
                                if ev_type in ["自習寫功課", "段考複習", "考試準備"]:
                                    color_id = "10"
                                    
                                if ev_type == "上課":
                                    target_cal_id = class_calendar_id
                                elif ev_type in ["自習寫功課", "段考複習", "考試準備"]:
                                    target_cal_id = task_calendar_id
                                else:
                                    target_cal_id = study_calendar_id
                                url_create = f"https://www.googleapis.com/calendar/v3/calendars/{target_cal_id}/events"
                                payload = {
                                    "summary": ev_name,
                                    "description": "[Life-Agent 自動生成]\n由 Telegram 指令自動匯入",
                                    "start": {
                                        "dateTime": start_iso,
                                        "timeZone": "Asia/Taipei"
                                    },
                                    "end": {
                                        "dateTime": end_iso,
                                        "timeZone": "Asia/Taipei"
                                    },
                                    "colorId": color_id,
                                    "extendedProperties": {
                                        "private": {
                                            "source": "life-agent"
                                        }
                                    }
                                }
                                try:
                                    res_create = make_gcal_request("POST", url_create, json=payload)
                                    if res_create and res_create.status_code == 200:
                                        events_added += 1
                                    else:
                                        print(f"匯入 Google Calendar 事件失敗: {res_create.status_code if res_create else 'No Response'}")
                                except Exception as e:
                                    print(f"匯入 Google Calendar 異常: {e}")
                            
                    send_telegram_message(f"成功匯入日程！\n- 新增固定課表：{fixed_added} 筆\n- 規劃行事曆事件：{events_added} 筆")
        except Exception as proc_err:
            print(f"處理指令出錯 [{text}]: {proc_err}")
            send_telegram_message(f"處理指令出錯：{proc_err}")

    if max_update_id > 0:
        try:
            ack_url = f"{url}?offset={max_update_id + 1}"
            request_with_retry("GET", ack_url).raise_for_status()
            print(f"已確認更新，新 offset: {max_update_id + 1}")
        except Exception as e:
            print(f"確認 Telegram 更新失敗: {e}")

# ==================== 寒暑假判定 ====================

def is_vacation(check_date):
    m, d = check_date.month, check_date.day
    if m in [7, 8]:
        return True
    if m == 1 and d >= 21:
        return True
    if m == 2 and d <= 10:
        return True
    return False

# ==================== 視覺辨識 (Gemini API) ====================

def get_file_mime_type(content):
    if content.startswith(b'%PDF'):
        return 'application/pdf'
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if content.startswith(b'RIFF') and content[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/jpeg'

def analyze_receipt(image_url):
    print(f"開始分析發票照片: {image_url[:60]}...")
    resp = request_with_retry("GET", image_url)
    resp.raise_for_status()
    content = resp.content
    mime_type = get_file_mime_type(content)
    
    prompt = """
    請幫我分析這張發票或收據照片，提取以下欄位：
    1. item_name (發票中的主要消費項目或商店名稱，例如 "麥當勞" 或 "7-11 飲料"，請使用簡短的繁體中文)
    2. amount (消費總金額，必須是整數數字，如果有多個金額，請選取最終付款的總金額)
    3. category (分類，必須是以下四個選項之一："飲食"、"交通"、"娛樂"、"學習"，請根據消費內容精準推理分類，例如買書為"學習"，吃晚餐為"飲食"，搭火車為"交通"，買遊戲為"娛樂")

    請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
    {
      "item_name": "項目名稱",
      "amount": 100,
      "category": "飲食"
    }
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = safe_generate_content(model, [
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_todo_photo(image_url, today_str):
    print(f"開始分析聯絡簿/考卷/回條照片: {image_url[:60]}...")
    resp = request_with_retry("GET", image_url)
    resp.raise_for_status()
    return analyze_todo_photo_bytes(resp.content, today_str)

def analyze_todo_photo_bytes(content, today_str):
    mime_type = get_file_mime_type(content)
    prompt = f"""
    請幫我分析這張聯絡簿、考卷或回條照片，提取出重要的待辦事項、小考、段考、回條或報名表資訊：
    1. name (事項描述或名稱，例如 "數學課本 P.10-P.12 習題"、"英文單字 L3 小考"、"家長同意書回條"，請用繁體中文)
    2. type (類型，必須是以下選項之一："作業"、"小考"、"段考"、"回條"、"報名表"、"活動")
    3. due_date (截止或考試日期，格式為 YYYY-MM-DD。如果聯絡簿上寫的是明天或特定星期，請結合今天日期 {today_str} 來推理出正確的日期)
    4. subject (相關科目，例如 "數學" "英文" "國文" "物理" "化學"，若無特定科目則填 "無")

    請僅返回以下 JSON 格式，不要包含 any markdown 標記：
    {
      "name": "事項名稱",
      "type": "作業",
      "due_date": "2026-06-21",
      "subject": "數學"
    }
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = safe_generate_content(model, [
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_activity_brochure(image_url, user_instruction=""):
    print(f"開始分析活動簡章照片: {image_url[:60]}...")
    resp = request_with_retry("GET", image_url)
    resp.raise_for_status()
    return analyze_activity_brochure_bytes(resp.content, user_instruction)

def analyze_activity_brochure_bytes(content, user_instruction=""):
    mime_type = get_file_mime_type(content)
    
    prompt = """
    請幫我分析這張活動簡章或海報照片/文件，提取出其中所有關鍵的時段/日期（例如：報名截止日、初賽日期、複賽日期、營隊活動日期等）。
    對於每一個提取出的時段/日期，請建立一個獨立的活動事件。
    
    【重要篩選前提 - 使用者身分過濾】
    使用者身分是：台灣「114學年度入學的高雄中學科學班學生」。
    也就是：目前（2026年6月）為高一升高二的普通高中學生（非高職生）。
    請自動過濾掉不符合此身分、或此身分無法參加的活動。例如：
    - 僅限高職生（或綜合高中專門學程）參加的活動 -> 過濾掉不建立事件
    - 僅限高三（或即將畢業之高三生）參加的活動 -> 過濾掉不建立事件
    - 僅限國中或國小學生參加的活動 ->過濾掉不建立事件
    - 僅限大專院校、大學以上參加的活動 -> 過濾掉不建立事件
    如果整個活動/簡章都不符身分，請回傳空的 events 列表。
    
    對於符合身分可以參加的事件，請提取以下欄位：
    1. name (事件名稱，請用繁體中文。請結合活動主名稱與該日期的項目，例如 "YTP 少年圖靈計畫 - 線上初賽"、"YTP 少年圖靈計畫 - 報名截止")
    2. type (類型，必須是以下選項之一："講座"、"營隊"、"比賽"、"志工"、"休閒"、"其他")
    3. date (活動日期，格式為 YYYY-MM-DD，若是範圍請填寫開始日期)
    4. note (簡短備註，提取該事件的時間、地點、費用、組隊要求或重要資訊，50字以內)
    """
    if user_instruction:
        prompt += f"\n\n請特別注意！使用者給出了以下特定提取指令：\n\"{user_instruction}\"\n請務必依據此指定指令，在簡章中優先找出使用者關心的活動時段或日期，並列在事件列表中。"
        
    prompt += """
    請僅返回以下 JSON 格式（其中 events 是一個陣列，包含??    可判定的動作（action）與其對應的提取資料（data）如下：
    
    1. action: "add_todo" (新增功課、作業、小考、考試準備等課業學習相關待辦事項)
       提取 data 欄位：
       - name (功課/待辦事項名稱或描述，請使用簡短的繁體中文，且不要包含科目名稱。如果使用者提及了預估耗時，例如「需3小時」、「需180分鐘」，請在 name 末尾加上「 (需X小時)」或「 (需X分鐘)」，例如「英文補課 (需3小時)」)
       - subject (相關科目，例如「數學」、「英文」、「物理」等，若無請填 "無")
       - due_date (截止日期，格式為 YYYY-MM-DD。若無提到請填 "#")
       - type (類型，必須是以下之一："作業"、"小考"、"段考"、"回條"、"報名表")
       
    2. action: "complete_todo" (標記某個待辦事項/功課為已完成)
       提取 data 欄位：
       - name (要標記完成的事項關鍵字/名稱)
       - actual_time (實際耗時，必須是整數數字字串，表示分鐘，例如 "60"。若未提及則填 "#")
       
    3. action: "incomplete_todo" (標記某個待辦事項/功課為「沒寫完」、「未完成」，需要重新安排排程)
       提取 data 欄位：
       - name (沒寫完的作業關鍵字/名稱)
       
    4. action: "add_activity" (新增一次性活動、比賽、講座、營隊、志工、出遊行程等)
       提取 data 欄位：
       - name (活動名稱)
       - date (活動日期，如果是單日請填 YYYY-MM-DD。如果是多日區間，格式為 YYYY-MM-DD/YYYY-MM-DD，例如 "2026-07-15/2026-07-19")
       - type (類型，必須是以下之一："講座"、"營隊"、"比賽"、"志工"、"休閒"、"其他")
       
    4. action: "add_expense" (記帳、新增一筆金錢消費/花費記錄)
       提取 data 欄位：
       - name (消費項目名稱或商店名稱，例如 "麥當勞"、"7-11 飲料")
       - amount (消費總金額，必須是整數數字)
       - category (分類，必須是以下之一："飲食"、"交通"、"娛樂"、"學習")
       
    5. action: "generic_todo" (不符合以上，但屬於一般隨手記下的雜事待辦/備忘，例如「清理書桌」)
       提取 data 欄位：
       - name (待辦名稱)
       - date (時間/日期，格式為 YYYY-MM-DD。若無提到請填 "#")

    【絕對分類與路由規則 (CRITICAL ROUTING RULES)】：
    1. 記帳與消費優先：凡是訊息涉及「花了多少錢」、「買了」、「費用」、「金額」、「元」、「收據」等與【金錢/消費/花費/購買/記帳】相關的任何敘述，必須路由為 "add_expense"，絕不能分配為作業 "add_todo" 或備忘 "generic_todo"。
    2. 活動與行程優先：凡是訊息涉及「營隊」、「比賽」、「志工」、「講座」、「聚會」、「演講」、「黑客松」等【一次性活動或日程】，必須路由為 "add_activity"，絕不能分配為學校作業待辦 "add_todo"。
    3. 功課與小考：僅限於學校的功課、作業、課後練習、複習、小考、段考、家長回條等【學校課業與課後自修待辦】路由為 "add_todo"。

    待解析敘述：
    "{text_content}"

    請僅返回以下 JSON 格式，不要包含 any markdown 標記（如 ```json 等）：
    {{
      "action": "add_todo",
      "data": {{
        "name": "作業名稱",
        "subject": "科目",
        "due_date": "2026-07-07",
        "type": "作業"
      }}
    }}  
    請仔細分析照片中的每一天，並提取以下兩類資訊：
    
    1. fixed_schedule (重複性的固定課表/作息)：
       - subject (科目或項目名稱)
       - weekday (星期，整數 1-7，1為星期一，7為星期日)
       - time_range (時間段，格式如 "13:30-16:45")
       - is_vacation (作息類型，請判斷是 "暑假" 還是 "學期中")
       
    2. weekly_events (一次性的具體日期行程、請假或補課)：
       - date (日期，格式為 YYYY-MM-DD)
       - name (行程名稱。如果是請假，名稱中必須包含「請假」或「停課」，例如 "PC化學請假"、"PC物理 停課"、"PC化學 (休息!)"；如果是補課，名稱中必須包含「補課」，例如 "MEC補課")
       - start (開始時間，格式如 "08:30" 或 "18:30")
       - end (結束時間，格式如 "12:00" 或 "21:30")
       - type (行程類型，必須是以下五個之一："上課"、"自習寫功課"、"考試準備"、"段考複習"、"休息"。請注意：請假/停課/休息日的 type 請填 "休息"，上課與補課/活動/志工的 type 請填 "上課")
       
       【節次與起訖時間換算說明】：
       如果在資料中看到「第X節課」、「X-Y節」、「X節」或「X-Y節」（如 1-2節、34節、3-4節、12節），請自動依據雄中課堂時間對照表進行換算：
       - 第 1 節課: 08:10-09:00
       - 第 2 節課: 09:10-10:00
       - 第 3 節課: 10:20-11:10
       - 第 4 節課: 11:20-12:10
       - 第 5 節課: 13:20-14:10
       - 第 6 節課: 14:20-15:10
       - 第 7 節課: 15:20-16:10
       - 第 8 節課: 16:20-17:10
       例如「12節」或「1-2節」即為 08:10-10:00；「34節」或「3-4節」即為 10:20-12:10。

    請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
    {{
      "fixed_schedule": [
        {{
          "subject": "PC化學",
          "weekday": 2,
          "time_range": "13:30-16:45",
          "is_vacation": "暑假"
        }}
      ],
      "weekly_events": [
        {{
          "date": "2026-07-06",
          "name": "高醫志工 (上午)",
          "start": "08:30",
          "end": "12:00",
          "type": "上課"
        }},
        {{
          "date": "2026-07-07",
          "name": "PC化學請假",
          "start": "13:30",
          "end": "16:45",
          "type": "休息"
        }}
      ]
    }}
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = safe_generate_content(model, [
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_calendar_text(text_content, today_str):
    prompt = f"""
    請幫我分析以下行事曆或課表敘述文字，提取其中所有的日常固定課表與一次性日程事件（包括活動、志工、比賽、請假、停課、補課等）。
    
    今天日期為：{today_str}（請以此基準年份和日期，正確推算敘述中的年月日，格式皆為 YYYY-MM-DD）。
    
    請提取以下兩類資訊：
    
    1. fixed_schedule (重複性的固定課表/作息)：
       - subject (科目或項目名稱)
       - weekday (星期，整數 1-7，1為星期一，7為星期日)
       - time_range (時間段，格式如 "13:30-16:45")
       - is_vacation (作息類型，請判斷是 "暑假" 還是 "學期中")
       
    2. weekly_events (一次性的具體日期行程、請假或補課)：
       - date (日期，格式為 YYYY-MM-DD)
       - name (行程名稱。如果是請假，名稱中必須包含「請假」或「停課」，例如 "PC化學請假"、"PC物理 停課"、"PC化學 (休息!)"；如果是補課，名稱中必須包含「補課」，例如 "MEC補課")
       - start (開始時間，格式如 "08:30" 或 "18:30")
       - end (結束時間，格式如 "12:00" 或 "21:30")
       - type (行程類型，必須是以下五個之一："上課"、"自習寫功課"、"考試準備"、"段考複習"、"休息"。請注意：請假/停課/休息日的 type 請填 "休息"，上課與補課/活動/志工的 type 請填 "上課")
       
       【節次與起訖時間換算說明】：
       如果在資料中看到「第X節課」、「X-Y節」、「X節」或「X-Y節」（如 1-2節、34節、3-4節、12節），請自動依據雄中課堂時間對照表進行換算：
       - 第 1 節課: 08:10-09:00
       - 第 2 節課: 09:10-10:00
       - 第 3 節課: 10:20-11:10
       - 第 4 節課: 11:20-12:10
       - 第 5 節課: 13:20-14:10
       - 第 6 節課: 14:20-15:10
       - 第 7 節課: 15:20-16:10
       - 第 8 節課: 16:20-17:10
       例如「12節」或「1-2節」即為 08:10-10:00；「34節」或「3-4節」即為 10:20-12:10。

    待解析敘述：
    "{text_content}"

    請僅返回以下 JSON 格式，不要包含任何 markdown 標記（如 ```json 等）：
    {{
      "fixed_schedule": [
        {{
          "subject": "PC化學",
          "weekday": 2,
          "time_range": "13:30-16:45",
          "is_vacation": "暑假"
        }}
      ],
      "weekly_events": [
        {{
          "date": "2026-07-06",
          "name": "高醫志工 (上午)",
          "start": "08:30",
          "end": "12:00",
          "type": "上課"
        }},
        {{
          "date": "2026-07-07",
          "name": "PC化學請假",
          "start": "13:30",
          "end": "16:45",
          "type": "休息"
        }}
      ]
    }}
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def find_notion_todo_fuzzy(user_input):
    results = query_database_all(TODO_ACTIVITIES_DB_ID)
    uncompleted = [r for r in results if not is_task_completed(r) and get_title(r, "名稱")]
    if not uncompleted:
        return None
        
    options = []
    for idx, t in enumerate(uncompleted):
        options.append(f"{idx+1}. ID: {t['id']} | 名稱: {get_title(t, '名稱')} | 科目: {get_rich_text(t, '相關科目')}")
        
    options_text = "\n".join(options)
    
    prompt = f"""
    請幫我比對使用者的輸入「{user_input}」，在下方的 Notion 任務清單中找到最匹配的那項任務。
    基準規則：使用者可能沒有打完整名稱（例如使用者說「化學單元1」，在清單中可能對應「化學平衡：單元1」）。
    
    Notion 未完成任務清單：
    {options_text}
    
    請僅返回匹配任務的 ID（例如 "abc-123-xyz"）。若沒有任何任務能夠匹配（例如無關的描述），請返回 "#"。
    請只返回 ID 字串，絕對不要包含 markdown 標籤（如 ```）或任何其他說明文字。
    """
    try:
        model = genai.GenerativeModel('gemini-3.1-flash-lite')
        response = safe_generate_content(model, prompt)
        res_id = response.text.strip().replace('"', '').replace("'", "")
        for t in uncompleted:
            if t["id"] == res_id:
                return t
    except Exception as ex:
        print(f"Fuzzy matching Notion todo failed: {ex}")
    return None

def route_and_parse_natural_text(text_content, today_str):
    prompt = f"""
    請幫我分析以下使用者的日常文字訊息，並自動判定他們想要執行的動作。基準日期為：{today_str}。
    
    可判定的動作（action）與其對應的提取資料（data）如下：
    
    1. action: "add_todo" (新增功課、作業、小考、考試準備等課業學習相關待辦事項)
       提取 data 欄位：
       - name (功課/待辦事項名稱或描述，請使用簡短的繁體中文，且不要包含科目名稱，例如「英文閱讀報告」-> name為「閱讀報告」)
       - subject (相關科目，例如「數學」、「英文」、「物理」等，若無請填 "無")
       - due_date (截止日期，格式為 YYYY-MM-DD。若無提到請填 "#")
       - type (類型，必須是以下之一："作業"、"小考"、"段考"、"回條"、"報名表")
       
    2. action: "complete_todo" (標記某個待辦事項/功課為已完成)
       提取 data 欄位：
       - name (要標記完成的事項關鍵字/名稱)
       - actual_time (實際耗時，必須是整數數字字串，表示分鐘，例如 "60"。若未提及則填 "#")
       
    3. action: "incomplete_todo" (標記某個待辦事項/功課為「沒寫完」、「未完成」，需要重新安排排程)
       提取 data 欄位：
       - name (沒寫完的作業關鍵字/名稱)
       
    4. action: "add_activity" (新增一次性活動、比賽、講座、營隊、志工、出遊行程等)
       提取 data 欄位：
       - name (活動名稱)
       - date (活動日期，格式為 YYYY-MM-DD)
       - type (類型，必須是以下之一："講座"、"營隊"、"比賽"、"志工"、"休閒"、"其他")
       
    4. action: "add_expense" (記帳、新增一筆金錢消費/花費記錄)
       提取 data 欄位：
       - name (消費項目名稱或商店名稱，例如 "麥當勞"、"7-11 飲料")
       - amount (消費總金額，必須是整數數字)
       - category (分類，必須是以下之一："飲食"、"交通"、"娛樂"、"學習")
       
    5. action: "generic_todo" (不符合以上，但屬於一般隨手記下的雜事待辦/備忘，例如「清理書桌」)
       提取 data 欄位：
       - name (待辦名稱)
       - date (時間/日期，格式為 YYYY-MM-DD。若無提到請填 "#")

    【絕對分類與路由規則 (CRITICAL ROUTING RULES)】：
    1. 記帳與消費優先：凡是訊息涉及「花了多少錢」、「買了」、「費用」、「金額」、「元」、「收據」等與【金錢/消費/花費/購買/記帳】相關的任何敘述，必須路由為 "add_expense"，絕不能分配為作業 "add_todo" 或備忘 "generic_todo"。
    2. 活動與行程優先：凡是訊息涉及「營隊」、「比賽」、「志工」、「講座」、「聚會」、「演講」、「黑客松」等【一次性活動或日程】，必須路由為 "add_activity"，絕不能分配為學校作業待辦 "add_todo"。
    3. 功課與小考：僅限於學校的功課、作業、課後練習、複習、小考、段考、家長回條等【學校課業與課後自修待辦】路由為 "add_todo"。

    待解析敘述：
    "{text_content}"

    請僅返回以下 JSON 格式，不要包含 any markdown 標記（如 ```json 等）：
    {{
      "action": "add_todo",
      "data": {{
        "name": "作業名稱",
        "subject": "科目",
        "due_date": "2026-07-07",
        "type": "作業"
      }}
    }}
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

# ==================== 核心邏輯 A：下午 5:00 執行 ====================

def run_mode_a(today_dt):
    print("【執行時段 A】記帳統計 + 視覺辨識 + LINE 書包精準檢查通知")
    today_str = today_dt.strftime("%Y-%m-%d")
    tomorrow_dt = today_dt + timedelta(days=1)
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")
    tomorrow_w = tomorrow_dt.isoweekday()  # 1-7
    
    # 1. 圖片多模態辨識與 Notion 自動填回
    # 1.1 記帳本照片處理
    ledger_filter = {
        "filter": {
            "and": [
                {"property": "收據照片", "files": {"is_not_empty": True}},
                {"property": "金額", "number": {"is_empty": True}}
            ]
        }
    }
    unprocessed_ledgers = query_database_all(LEDGER_DB_ID, ledger_filter)
    for row in unprocessed_ledgers:
        img_url = get_first_file_url(row, "收據照片")
        if img_url:
            try:
                res_data = analyze_receipt(img_url)
                update_properties = {
                    "項目名稱": {"title": [{"text": {"content": res_data.get("item_name", "未分類消費")}}]},
                    "金額": {"number": res_data.get("amount", 0)},
                    "分類": {"select": {"name": res_data.get("category", "飲食")}}
                }
                update_page(row["id"], update_properties)
                print(f"已回填記帳: {res_data.get('item_name')} = {res_data.get('amount')}元")
            except Exception as e:
                print(f"處理記帳照片失敗: {e}")
                
    # 1.2 待辦與活動照片處理
    todo_filter = {
        "filter": {
            "and": [
                {"property": "照片上傳", "files": {"is_not_empty": True}},
                {
                    "or": [
                        {"property": "名稱", "title": {"is_empty": True}},
                        {"property": "截止或考試日期", "date": {"is_empty": True}},
                        {"property": "相關科目", "rich_text": {"is_empty": True}}
                    ]
                }
            ]
        }
    }
    unprocessed_todos = query_database_all(TODO_ACTIVITIES_DB_ID, todo_filter)
    for row in unprocessed_todos:
        img_url = get_first_file_url(row, "照片上傳")
        if img_url:
            try:
                res_data = analyze_todo_photo(img_url, today_str)
                update_properties = {
                    "名稱": {"title": [{"text": {"content": get_title(row, "名稱") or res_data.get("name", "未命名事項")}}]},
                    "類型": {"select": {"name": get_select(row, "類型") or res_data.get("type", "作業")}},
                    "截止或考試日期": {"date": {"start": get_date(row, "截止或考試日期") or res_data.get("due_date", today_str)}},
                    "相關科目": {"rich_text": [{"text": {"content": get_rich_text(row, "相關科目") or res_data.get("subject", "無")}}]},
                    "總頁數/題數": {"number": get_number(row, "總頁數/題數") if get_number(row, "總頁數/題數") is not None else 1},
                    "已完成頁數/題數": {"number": get_number(row, "已完成頁數/題數") if get_number(row, "已完成頁數/題數") is not None else 0}
                }
                update_page(row["id"], update_properties)
                print(f"已回填待辦: {res_data.get('name')}，相關科目: {res_data.get('subject')}")
            except Exception as e:
                print(f"處理待辦照片失敗: {e}")

    # 1.3 活動簡章照片處理
    if ACTIVITIES_DB_ID:
        activity_filter = {
            "filter": {
                "and": [
                    {"property": "簡章上傳", "files": {"is_not_empty": True}},
                    {
                        "or": [
                            {"property": "活動名稱", "title": {"is_empty": True}},
                            {"property": "日期", "date": {"is_empty": True}}
                        ]
                    }
                ]
            }
        }
        try:
            unprocessed_activities = query_database_all(ACTIVITIES_DB_ID, activity_filter)
            for row in unprocessed_activities:
                img_url = get_first_file_url(row, "簡章上傳")
                if img_url:
                    try:
                        original_note = get_rich_text(row, "備註")
                        clean_user_note = original_note.split("\n---\n系統提取資訊：")[0].strip()
                        res_data = analyze_activity_brochure(img_url, clean_user_note)
                        
                        events = res_data.get("events", [])
                        if events:
                            first_event = events[0]
                            extracted_note = first_event.get("note", "")
                            if extracted_note:
                                if clean_user_note:
                                    combined_note = f"{clean_user_note}\n---\n系統提取資訊：{extracted_note}"
                                else:
                                    combined_note = extracted_note
                            else:
                                combined_note = clean_user_note

                            original_title = get_title(row, "活動名稱")
                            new_title = first_event.get("name") or original_title or "未命名活動"

                            update_properties = {
                                "活動名稱": {"title": [{"text": {"content": new_title}}]},
                                "類型": {"select": {"name": get_select(row, "類型") or first_event.get("type", "其他")}},
                                "日期": {"date": {"start": get_date(row, "日期") or first_event.get("date", today_str)}},
                                "備註": {"rich_text": [{"text": {"content": combined_note}}]}
                            }
                            update_page(row["id"], update_properties)
                            print(f"已回填主活動: {new_title}")

                            # 建立其他事件的新列
                            for event in events[1:]:
                                new_row_properties = {
                                    "活動名稱": {"title": [{"text": {"content": event.get("name", "未命名活動")}}]},
                                    "類型": {"select": {"name": event.get("type", "其他")}},
                                    "日期": {"date": {"start": event.get("date", today_str)}},
                                    "備註": {"rich_text": [{"text": {"content": f"由 {new_title} 簡章自動生成\n---\n系統提取資訊：{event.get('note', '')}"}}]}
                                }
                                create_page(ACTIVITIES_DB_ID, new_row_properties)
                                print(f"已新增活動事件: {event.get('name')}")
                        else:
                            print(f"未能從簡章中提取出任何符合身分之活動事件，將該列標註為不符身分跳過。")
                            original_title = get_title(row, "活動名稱")
                            new_title = original_title if original_title else "不符身分之活動"
                            update_properties = {
                                "活動名稱": {"title": [{"text": {"content": new_title}}]},
                                "日期": {"date": {"start": today_str}},
                                "備註": {"rich_text": [{"text": {"content": f"{clean_user_note}\n---\n系統提取資訊：此活動不符合您的身分（114學年度雄中科學班高一升高二），已自動跳過。"}}]}
                            }
                            update_page(row["id"], update_properties)
                    except Exception as e:
                        print(f"處理活動簡章照片失敗: {e}")
        except Exception as e:
            print(f"讀取未處理活動失敗: {e}")

    # 2. 傍晚通知邏輯：計算今天放學後到明早回學校前的補習與作業
    take_home = []
    cram_events_list = []
    todo_events_list = []
    
    try:
        access_token = get_google_calendar_access_token()
        if access_token:
            class_calendar_id, _, task_calendar_id, _, _ = get_calendar_ids()
            
            time_min = f"{today_str}T17:00:00+08:00"
            time_max = f"{tomorrow_str}T08:00:00+08:00"
            params_gcal = {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime"
            }
            
            url_class = f"https://www.googleapis.com/calendar/v3/calendars/{class_calendar_id}/events"
            res_class = make_gcal_request("GET", url_class, params=params_gcal)
            if res_class and res_class.status_code == 200:
                for ev in res_class.json().get("items", []):
                    summary = ev.get("summary", "")
                    start_time_str = ev.get("start", {}).get("dateTime", "")
                    is_cram = False
                    if start_time_str:
                        try:
                            hour = int(start_time_str.split("T", 1)[1][:2])
                            if hour >= 17:
                                is_cram = True
                        except:
                            pass
                    summary_lower = summary.lower()
                    if any(k in summary_lower for k in ["pc", "mec", "補習", "補"]):
                        is_cram = True
                    if is_cram:
                        end_time_str = ev.get("end", {}).get("dateTime", "")
                        start_formatted = start_time_str[11:16] if start_time_str else ""
                        end_formatted = end_time_str[11:16] if end_time_str else ""
                        cram_events_list.append((summary, f"{start_formatted}~{end_formatted}"))
            
            url_task = f"https://www.googleapis.com/calendar/v3/calendars/{task_calendar_id}/events"
            res_task = make_gcal_request("GET", url_task, params=params_gcal)
            if res_task and res_task.status_code == 200:
                for ev in res_task.json().get("items", []):
                    if ev.get("extendedProperties", {}).get("private", {}).get("source") in ["life-agent", "life-agent-ai-scheduled"]:
                        summary = ev.get("summary", "")
                        start_time_str = ev.get("start", {}).get("dateTime", "")
                        end_time_str = ev.get("end", {}).get("dateTime", "")
                        start_formatted = start_time_str[11:16] if start_time_str else ""
                        end_formatted = end_time_str[11:16] if end_time_str else ""
                        desc = ev.get("description", "")
                        todo_events_list.append((summary, f"{start_formatted}~{end_formatted}", desc))

        unique_subjects = set()
        
        def parse_subject_from_title(title, desc=""):
            if desc:
                import re
                m = re.search(r"科目：\s*([^\n]+)", desc)
                if m:
                    return m.group(1).strip()
            for subj in ["數學", "物理", "英文", "歷史", "地科", "化學", "國文", "生物", "地理", "公民"]:
                if subj in title:
                    return subj
            return None

        for summary, _ in cram_events_list:
            subj = parse_subject_from_title(summary)
            if subj:
                unique_subjects.add(subj)
                
        for summary, _, desc in todo_events_list:
            subj = parse_subject_from_title(summary, desc)
            if subj:
                unique_subjects.add(subj)

        tracker_results = query_database_all(BOOK_TRACKER_DB_ID)
        location_tracker = {}
        for r in tracker_results:
            name = get_title(r, "科目/物品名稱")
            loc = get_select(r, "目前位置")
            if name:
                location_tracker[name] = (loc, r["id"])

        for subj in unique_subjects:
            if subj in location_tracker:
                loc, page_id = location_tracker[subj]
                if loc == "在學校":
                    take_home.append((subj, "功課與補習", page_id))
            else:
                try:
                    new_pg = create_page(BOOK_TRACKER_DB_ID, {
                        "科目/物品名稱": {"title": [{"text": {"content": subj}}]},
                        "目前位置": {"select": {"name": "在學校"}},
                        "Currently_At": {"select": {"name": "在學校"}}
                    })
                    page_id = new_pg.get("id")
                    if page_id:
                        take_home.append((subj, "功課與補習", page_id))
                except Exception as e:
                    print(f"建立書籍追蹤頁面失敗 {subj}: {e}")
        take_home.sort(key=lambda x: x[0])
    except Exception as e:
        print(f"傍晚通知計算失敗: {e}")

    # 3. 記帳統計與 Telegram 發送
    today_ledger_filter = {
        "filter": {
            "and": [
                {"property": "日期", "date": {"equals": today_str}}
            ]
        }
    }
    today_ledgers = query_database_all(LEDGER_DB_ID, today_ledger_filter)
    total_spend = sum([get_number(x, "金額") or 0 for x in today_ledgers])

    cram_detail = "\n".join([f"  ● {item} ({time_str})" for item, time_str in cram_events_list]) if cram_events_list else "  無"
    todo_detail = "\n".join([f"  ● {item} ({time_str})" for item, time_str, _ in todo_events_list]) if todo_events_list else "  無"
    
    if take_home:
        take_home_section = "\n".join([f"  [ ] {x[0]} ({x[1]})" for x in take_home])
        inline_buttons = []
        for x in take_home:
            short_id = x[2].replace("-", "")
            inline_buttons.append([{"text": f"✅ 已將 {x[0]} 帶回家", "callback_data": f"bh:{short_id}"}])
        reply_markup = {"inline_keyboard": inline_buttons}
    else:
        take_home_section = "  無須帶 any 書本回家。"
        reply_markup = None

    if total_spend > 0:
        expense_section = f"- 總計花費：{total_spend} 元"
    else:
        expense_section = "- 今日無任何消費記帳。"

    telegram_msg = f"""【Life-Agent 傍晚通知 - 書包檢查與記帳】

[離開學校後到回學校前的補習與作業]
--------------------------------
補習日程：
{cram_detail}

作業排程：
{todo_detail}
--------------------------------

[放學必帶回家的科目]
--------------------------------
{take_home_section}
--------------------------------
(請確認相關科目的課本/講義已放入包包)

[今日消費統計]
{expense_section}"""
    send_telegram_message(telegram_msg, reply_markup=reply_markup)

# ==================== 核心邏輯 B：半夜 12:00 執行 ====================

def run_mode_b(today_dt):
    print("【執行時段 B】動態時間塊精確分配 + LINE 明日日程通知")
    today_str = today_dt.strftime("%Y-%m-%d")
    yesterday_dt = today_dt - timedelta(days=1)
    yesterday_str = yesterday_dt.strftime("%Y-%m-%d")
    today_w = today_dt.isoweekday() # 1-7
    
    # 1. 讀取昨日任務，計算時間加權修正
    yesterday_todo_filter = {
        "filter": {
            "and": [
                {"property": "截止或考試日期", "date": {"equals": yesterday_str}}
            ]
        }
    }
    yesterday_todos = query_database_all(TODO_ACTIVITIES_DB_ID, yesterday_todo_filter)
    yesterday_todos = [t for t in yesterday_todos if get_title(t, "名稱") and get_title(t, "名稱").strip() != ""]
    
    weighted_subjects = set()
    for t in yesterday_todos:
        total_p = get_number(t, "總頁數/題數") or 1
        completed_p = get_number(t, "已完成頁數/題數") or 0
        completed = (completed_p / total_p) * 100 if total_p > 0 else 0
        actual_time = get_number(t, "實際耗時") or 0
        t_type = get_select(t, "類型") or "作業"
        sub = get_rich_text(t, "相關科目")
        
        # 動態回饋修正機制已應要求停用
        pass

    # 2. 判斷寒暑假作息
    is_vac = is_vacation(today_dt)
    vac_type = "暑假" if is_vac else "學期中"
    
    # 撈取今日固定課表
    today_schedule_filter = {
        "filter": {
            "and": [
                {"property": "星期", "number": {"equals": today_w}},
                {"property": "作息類型", "select": {"equals": vac_type}}
            ]
        }
    }
    today_fixed_schedules = query_database_all(FIXED_SCHEDULE_DB_ID, today_schedule_filter)
    
    # 3. 撈取所有未完成任務並分類
    raw_all_todos = query_database_all(TODO_ACTIVITIES_DB_ID)
    uncompleted_todos = [t for t in raw_all_todos if not is_task_completed(t) and get_title(t, "名稱") and get_title(t, "名稱").strip() != ""]
    
    sprint_end_dt = today_dt + timedelta(days=2)
    sprint_end_str = sprint_end_dt.strftime("%Y-%m-%d")
    
    pre_study_end_dt = today_dt + timedelta(days=6)
    pre_study_end_str = pre_study_end_dt.strftime("%Y-%m-%d")
    
    sprint_todos = []      # 倒數 3 天衝刺、當天截止或已逾期的任務 (Priority 1)
    pre_study_todos = []   # 提早 7 天段考/報告準備 (Priority 2)
    today_todos = []       # 今天截止的任務 (Priority 3)
    general_todos = []     # 其他所有未完成的任務，包括沒有截止日期的任務 (Priority 4)
    
    for t in uncompleted_todos:
        due = get_date(t, "截止或考試日期")
        if due:
            if due <= today_str:
                if due == today_str:
                    today_todos.append(t)
                sprint_todos.append(t)
            elif due <= sprint_end_str:
                sprint_todos.append(t)
            elif due <= pre_study_end_str:
                pre_study_todos.append(t)
            else:
                general_todos.append(t)
        else:
            general_todos.append(t)
    
    # 4. 規劃今天時間日程 (Time Blocking)
    available_blocks = []
    if not is_vac:
        available_blocks.append((18 * 60 + 30, 22 * 60 + 30)) # 18:30 - 22:30
    else:
        available_blocks.append((9 * 60, 12 * 60))    # 09:00 - 12:00
        available_blocks.append((14 * 60, 17 * 60))   # 14:00 - 17:00
        available_blocks.append((19 * 60, 21 * 60 + 30)) # 19:00 - 21:30

    fixed_events = []
    
    access_token = get_google_calendar_access_token()
    if not access_token:
        print("無法取得 Google Calendar Access Token，終止時間分配。")
        return
        
    class_calendar_id, study_calendar_id, task_calendar_id, _, _ = get_calendar_ids()
    
    # 查詢今日 Google Calendar 事件
    time_min = f"{today_str}T00:00:00+08:00"
    time_max = f"{today_str}T23:59:59+08:00"
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime"
    }
    
    existing_events = []
    bot_deleted_count = 0
    
    cals_to_clear = {class_calendar_id, study_calendar_id, task_calendar_id}
    for cal_id in cals_to_clear:
        url_list = f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events"
        res_list = make_gcal_request("GET", url_list, params=params)
        if res_list and res_list.status_code == 200:
            events_in_cal = res_list.json().get("items", [])
            for ev in events_in_cal:
                is_bot = (
                    ev.get("extendedProperties", {}).get("private", {}).get("source") in ["life-agent", "life-agent-ai-scheduled"] or
                    "[Life-Agent 自動生成]" in (ev.get("description") or "")
                )
                if is_bot:
                    delete_google_calendar_event(access_token, cal_id, ev["id"])
                    bot_deleted_count += 1
                else:
                    if not any(x["id"] == ev["id"] for x in existing_events):
                        existing_events.append(ev)

    class_overrides = []
    other_fixed_events = []
    
    for event in existing_events:
        name = event.get("summary") or "無標題行程"
        is_cancellation = ("請假" in name or "停課" in name or "休息!" in name or "(休息!)" in name)
        if is_cancellation:
            print(f"偵測到請假/停課標記行程 [{name}]，不將其視為忙碌區塊。")
            continue
            
        start_data = event.get("start", {})
        end_data = event.get("end", {})
        
        if "date" in start_data:
            # 全天事件
            ev_struct = {
                "name": name,
                "start": 9 * 60,
                "end": 17 * 60,
                "type": "上課",
                "is_user_event": True
            }
            other_fixed_events.append(ev_struct)
        elif "dateTime" in start_data:
            try:
                dt_start = datetime.fromisoformat(start_data["dateTime"])
                dt_end = datetime.fromisoformat(end_data["dateTime"])
                
                if dt_start.date() < today_dt.date():
                    sh, sm = 0, 0
                else:
                    sh, sm = dt_start.hour, dt_start.minute
                    
                if dt_end.date() > today_dt.date():
                    eh, em = 24, 0
                else:
                    eh, em = dt_end.hour, dt_end.minute
                    
                ev_struct = {
                    "name": name,
                    "start": sh * 60 + sm,
                    "end": eh * 60 + em,
                    "type": "上課",
                    "is_user_event": True
                }
                
                if get_subject_budget(name) > 0:
                    class_overrides.append(ev_struct)
                else:
                    other_fixed_events.append(ev_struct)
                print(f"偵測到 Google Calendar 保留行程: {sh:02d}:{sm:02d}-{eh:02d}:{em:02d} {name}")
            except Exception as e:
                print(f"解析保留行程失敗: {e}")
                    
    for s in today_fixed_schedules:
        time_range = get_rich_text(s, "時間段")
        name = get_title(s, "科目名稱")
        
        # 1. 暑輔日期區間限制 (2026-07-13 至 2026-08-07)
        vac_type = get_select(s, "作息類型")
        if vac_type == "暑假":
            curr_date = today_dt.date()
            if not (date(2026, 7, 13) <= curr_date <= date(2026, 8, 7)):
                print(f"今日 ({curr_date}) 不在暑輔期間 (7/13 - 8/7)，跳過暑假固定行程 [{name}]。")
                continue
                
        # 2. 請假/停課/休息判定
        is_canceled = False
        for ex in existing_events:
            ex_title = ex.get("summary") or ""
            if name in ex_title and ("請假" in ex_title or "停課" in ex_title or "休息" in ex_title):
                is_canceled = True
                print(f"今日課程 [{name}] 在行事曆中被標記為 {ex_title}，已跳過固定行程。")
                break
        if is_canceled:
            continue

        if time_range and "-" in time_range:
            try:
                start_s, end_s = time_range.strip().split("-")
                sh, sm = map(int, start_s.split(":"))
                eh, em = map(int, end_s.split(":"))
                ev = {
                    "name": name,
                    "start": sh * 60 + sm,
                    "end": eh * 60 + em,
                    "type": "上課"
                }
                if get_subject_budget(name) > 0:
                    class_overrides.append(ev)
                else:
                    other_fixed_events.append(ev)
            except Exception as e:
                print(f"解析課表時間段失敗 [{time_range}]: {e}")

    # 建構基礎在校節次作息 (週一至週五)
    if today_w in [1, 2, 3, 4, 5]:
        default_periods = [
            {"name": "準備時間", "start": 8 * 60, "end": 8 * 60 + 10, "type": "上課"},
            {"name": "第 1 節課", "start": 8 * 60 + 10, "end": 9 * 60, "type": "上課", "period": 1},
            {"name": "課間活動", "start": 9 * 60, "end": 9 * 60 + 10, "type": "上課"},
            {"name": "第 2 節課", "start": 9 * 60 + 10, "end": 10 * 60, "type": "上課", "period": 2},
            {"name": "打掃及課間活動", "start": 10 * 60, "end": 10 * 60 + 20, "type": "上課"},
            {"name": "第 3 節課", "start": 10 * 60 + 20, "end": 11 * 60 + 10, "type": "上課", "period": 3},
            {"name": "課間活動", "start": 11 * 60 + 10, "end": 11 * 60 + 20, "type": "上課"},
            {"name": "第 4 節課", "start": 11 * 60 + 20, "end": 12 * 60 + 10, "type": "上課", "period": 4}
        ]
        if not is_vac:
            # 學期中額外加入第 5-8 節課以及午休/午餐
            default_periods.extend([
                {"name": "午餐時間", "start": 12 * 60 + 10, "end": 12 * 60 + 40, "type": "上課"},
                {"name": "午休時間", "start": 12 * 60 + 40, "end": 13 * 60 + 10, "type": "上課"},
                {"name": "課間活動", "start": 13 * 60 + 10, "end": 13 * 60 + 20, "type": "上課"},
                {"name": "第 5 節課", "start": 13 * 60 + 20, "end": 14 * 60 + 10, "type": "上課", "period": 5},
                {"name": "課間活動", "start": 14 * 60 + 10, "end": 14 * 60 + 20, "type": "上課"},
                {"name": "第 6 節課", "start": 14 * 60 + 20, "end": 15 * 60 + 10, "type": "上課", "period": 6},
                {"name": "課間活動", "start": 15 * 60 + 10, "end": 15 * 60 + 20, "type": "上課"},
                {"name": "第 7 節課", "start": 15 * 60 + 20, "end": 16 * 60 + 10, "type": "上課", "period": 7},
                {"name": "課間活動", "start": 16 * 60 + 10, "end": 16 * 60 + 20, "type": "上課"},
                {"name": "第 8 節課", "start": 16 * 60 + 20, "end": 17 * 60 + 10, "type": "上課", "period": 8}
            ])
            
        # 進行合併：如果某個預設節次與 class_overrides 重疊，優先使用 class_overrides 的名稱
        for dp in default_periods:
            for ov in class_overrides:
                overlap = max(dp["start"], ov["start"]) < min(dp["end"], ov["end"])
                if overlap:
                    dp["name"] = ov["name"]
                    
        # 將平日節次加入
        fixed_events.extend(default_periods)
        
        # 處理不重疊於平日白天節次的其他課程（如晚上課程）
        for ov in class_overrides:
            has_overlap = False
            for dp in default_periods:
                if max(dp["start"], ov["start"]) < min(dp["end"], ov["end"]):
                    has_overlap = True
                    break
            if not has_overlap:
                fixed_events.append(ov)
                
        # 處理其他非課程固定行程（如志工等）
        fixed_events.extend(other_fixed_events)
    else:
        # 周末：直接加入所有行程
        fixed_events.extend(class_overrides)
        fixed_events.extend(other_fixed_events)

    # 讀取今天活動資料庫中的活動，並作為固定行程（Busy Blocks）避開 (預設 09:00 - 17:00)
    if ACTIVITIES_DB_ID:
        try:
            all_activities = query_database_all(ACTIVITIES_DB_ID)
            for act in all_activities:
                name = get_title(act, "活動名稱")
                a_type = get_select(act, "類型") or "其他"
                date_obj = act.get("properties", {}).get("日期", {}).get("date")
                if date_obj:
                    start_date = date_obj.get("start")
                    end_date = date_obj.get("end") or start_date
                    if start_date <= today_str <= end_date:
                        fixed_events.append({
                            "name": f"活動：{name}",
                            "start": 9 * 60,
                            "end": 17 * 60,
                            "type": a_type,
                            "is_user_event": True
                        })
                        print(f"偵測到今日活動 (活動期間: {start_date} 至 {end_date})，已加入固定行程: {name}")
        except Exception as e:
            print(f"讀取今日活動失敗: {e}")

    # 初始化時間表：False 為佔用，"FREE" 為可用自習，字串為特定科目專屬時間
    day_minutes = [False] * 1440
    for block_start, block_end in available_blocks:
        for m in range(block_start, block_end):
            day_minutes[m] = "FREE"
            
    original_fixed_classes = []
    for event in fixed_events:
        start_m = event["start"]
        end_m = event["end"]
        name = event["name"]
        
        # 判斷是否為在校課程且有自習額度
        budget = get_subject_budget(name)
        
        if budget > 0 and (end_m - start_m) >= budget:
            sub_key = get_subject_budget_key(name)
            # 將前 budget 分鐘設為該科目專屬
            for m in range(start_m, start_m + budget):
                day_minutes[m] = sub_key
            # 剩餘時間為佔用 (False)
            for m in range(start_m + budget, end_m):
                day_minutes[m] = False
                
            original_fixed_classes.append({
                "name": name,
                "start": start_m,
                "end": end_m,
                "subject": sub_key
            })
        else:
            for m in range(start_m, end_m):
                day_minutes[m] = False

    # 準備待分配的任務
    tasks_to_allocate = []
    processed_todo_ids = set()
    
    # 4.1 倒數 3 天衝刺項目 (優先權最高)
    for t in sprint_todos:
        t_type = get_select(t, "類型") or "作業"
        sub = get_rich_text(t, "相關科目") or "無"
        name = get_title(t, "名稱")
        processed_todo_ids.add(t["id"])
        
        fallback_dur = 90 if t_type in ["小考", "段考"] else (15 if t_type in ["回條", "報名表"] else DEFAULT_DURATION.get(t_type, 45))
        duration = get_todo_duration(name, fallback_dur)
        if sub in weighted_subjects:
            duration = int(duration * 1.3)
            
        t_name = f"衝刺：{name}"
        t_type_calendar = "段考複習" if t_type == "段考" else ("考試準備" if t_type == "小考" else "自習寫功課")
        
        tasks_to_allocate.append({
            "name": t_name,
            "type": t_type_calendar,
            "duration": duration,
            "subject": sub,
            "priority": 1
        })
        
    # 4.2 提早 7 天準備機制 (段考與報告)
    for t in pre_study_todos:
        if t["id"] in processed_todo_ids:
            continue
        t_type = get_select(t, "類型") or "作業"
        name = get_title(t, "名稱")
        sub = get_rich_text(t, "相關科目") or "無"
        
        # 若是未來段考或包含「報告」的作業，提早每天排入 45 分鐘準備
        if t_type == "段考" or (t_type == "作業" and "報告" in name):
            processed_todo_ids.add(t["id"])
            duration = get_todo_duration(name, 45)
            if sub in weighted_subjects:
                duration = int(duration * 1.3)
                
            t_name = f"提早準備：{name}"
            t_type_calendar = "段考複習" if t_type == "段考" else "自習寫功課"
            
            tasks_to_allocate.append({
                "name": t_name,
                "type": t_type_calendar,
                "duration": duration,
                "subject": sub,
                "priority": 2
            })

    # 4.3 今日截止的其餘項目 (Priority 3)
    for t in today_todos:
        if t["id"] in processed_todo_ids:
            continue
        t_type = get_select(t, "類型") or "作業"
        sub = get_rich_text(t, "相關科目") or "無"
        name = get_title(t, "名稱")
        
        fallback_dur = DEFAULT_DURATION.get(t_type, 45)
        duration = get_todo_duration(name, fallback_dur)
        if sub in weighted_subjects:
            duration = int(duration * 1.3)
            
        t_name = f"今日待辦：{name}"
        t_type_calendar = "自習寫功課" if t_type in ["作業", "回條", "報名表"] else "考試準備"
        
        tasks_to_allocate.append({
            "name": t_name,
            "type": t_type_calendar,
            "duration": duration,
            "subject": sub,
            "priority": 3
        })

    # 4.3.2 其他未完成項目 (Priority 4, 包含沒有設定截止日期或期限較遠的所有其餘工作)
    for t in general_todos:
        if t["id"] in processed_todo_ids:
            continue
        t_type = get_select(t, "類型") or "作業"
        sub = get_rich_text(t, "相關科目") or "無"
        name = get_title(t, "名稱")
        
        duration = DEFAULT_DURATION.get(t_type, 45)
        if sub in weighted_subjects:
            duration = int(duration * 1.3)
            
        t_name = f"待辦：{name}"
        t_type_calendar = "自習寫功課" if t_type in ["作業", "回條", "報名表"] else "考試準備"
        
        tasks_to_allocate.append({
            "name": t_name,
            "type": t_type_calendar,
            "duration": duration,
            "subject": sub,
            "priority": 4
        })

    # 4.4 獲取物品位置追蹤庫，進行防遺失警報
    tracker_results = query_database_all(BOOK_TRACKER_DB_ID)
    location_tracker = {}
    for r in tracker_results:
        name = get_title(r, "科目/物品名稱")
        loc = get_select(r, "目前位置")
        if name:
            location_tracker[name] = loc

    # 4.5 番茄鐘式時間塊規劃：若任務時間過長，自動進行拆分與休息插入 (例如超過 50 分鐘的自修)
    split_tasks = []
    for task in tasks_to_allocate:
        dur = task["duration"]
        if dur > 50:
            parts = []
            while dur > 50:
                parts.append(50)
                dur -= 50
            if dur > 0:
                parts.append(dur)
            
            # 將長任務轉換為 多個 50 分鐘任務，並在其中夾雜 10 分鐘休息行程
            for idx, part_dur in enumerate(parts):
                split_tasks.append({
                    "name": f"{task['name']} (專注 Part {idx+1})",
                    "type": task["type"],
                    "duration": part_dur,
                    "subject": task["subject"],
                    "priority": task["priority"]
                })
                if idx < len(parts) - 1:
                    # 插入一個 10 分鐘的番茄鐘休息
                    split_tasks.append({
                        "name": "番茄鐘伸展休息",
                        "type": "休息",
                        "duration": 10,
                        "subject": "無",
                        "priority": task["priority"]
                    })
        else:
            split_tasks.append(task)

    planned_events = []
    # 寫入沒有自習額度的固定行程 (保留原本的類型與使用者行程標記)
    for event in fixed_events:
        name = event["name"]
        budget = get_subject_budget(name)
        if budget <= 0:
            planned_events.append({
                "name": name,
                "type": event.get("type", "上課"),
                "start": event["start"],
                "end": event["end"],
                "note": "",
                "is_user_event": event.get("is_user_event", False)
            })

    # 分配位置輔助函式
    def find_free_slot(task_subject, duration):
        consecutive_free = 0
        start_idx = -1
        for i in range(1440):
            val = day_minutes[i]
            # 可用的分鐘包括 "FREE" 以及與任務科目相符的專屬時間
            is_avail = (val == "FREE") or (task_subject and val == task_subject)
            if is_avail:
                if start_idx == -1:
                    start_idx = i
                consecutive_free += 1
                if consecutive_free >= duration:
                    return start_idx, start_idx + duration
            else:
                consecutive_free = 0
                start_idx = -1
        return None

    unplanned_tasks = []
    for task in split_tasks:
        sub = task["subject"]
        if sub and sub.lower() == "無":
            sub = None
            
        if task["name"] == "番茄鐘伸展休息":
            # 尋找 10 分鐘空擋 (必須是 FREE)
            slot = find_free_slot(None, 10)
            if slot:
                start_m, end_m = slot
                for m in range(start_m, end_m):
                    day_minutes[m] = "TASK"
                planned_events.append({
                    "name": task["name"],
                    "type": "休息",
                    "start": start_m,
                    "end": end_m,
                    "note": ""
                })
            continue

        slot = find_free_slot(sub, task["duration"])
        if slot:
            start_m, end_m = slot
            for m in range(start_m, end_m):
                day_minutes[m] = "TASK"
                
            # 核對課本位置，提供警報
            note = ""
            if sub:
                loc = location_tracker.get(sub)
                if loc == "在學校":
                    note = f"[警報]{sub}課本仍在學校！請找同學借閱或確認是否漏帶！"
                    
            planned_events.append({
                "name": task["name"],
                "type": task["type"],
                "start": start_m,
                "end": end_m,
                "note": note
            })
        else:
            unplanned_tasks.append(task)

    # 重組課程事件：對於原本有自習額度的課程，將未被 TASK 佔用的部分還原為 [上課]
    for c in original_fixed_classes:
        c_start = c["start"]
        c_end = c["end"]
        sub = c["subject"]
        name = c["name"]
        
        in_class_block = False
        block_start = -1
        
        for m in range(c_start, c_end):
            val = day_minutes[m]
            if val != "TASK":
                if not in_class_block:
                    in_class_block = True
                    block_start = m
            else:
                if in_class_block:
                    planned_events.append({
                        "name": name,
                        "type": "上課",
                        "start": block_start,
                        "end": m,
                        "note": ""
                    })
                    in_class_block = False
                    
        if in_class_block:
            planned_events.append({
                "name": name,
                "type": "上課",
                "start": block_start,
                "end": c_end,
                "note": ""
            })

    # 填補剩餘可用自習時間為自由休息
    rest_start = -1
    for i in range(1440):
        if day_minutes[i] == "FREE":
            if rest_start == -1:
                rest_start = i
        else:
            if rest_start != -1:
                planned_events.append({
                    "name": "自由休息與放鬆",
                    "type": "休息",
                    "start": rest_start,
                    "end": i,
                    "note": ""
                })
                rest_start = -1
    if rest_start != -1:
        planned_events.append({
            "name": "自由休息與放鬆",
            "type": "休息",
            "start": rest_start,
            "end": 1440,
            "note": ""
        })

    planned_events.sort(key=lambda x: (x["start"], x["end"]))

    # 5. 批次寫回 Google Calendar
    print(f"已清除 Google Calendar 今日自動生成行程共 {bot_deleted_count} 筆。")

    for event in planned_events:
        if event.get("is_user_event"):
            continue
            
        sh, sm = divmod(event["start"], 60)
        eh, em = divmod(event["end"], 60)
        start_iso = f"{today_str}T{sh:02d}:{sm:02d}:00+08:00"
        end_iso = f"{today_str}T{eh:02d}:{em:02d}:00+08:00"
        
        c_type = event["type"]
        color_id = "5"
        if c_type == "上課":
            color_id = "9"
            target_cal_id = class_calendar_id
        elif c_type in ["自習寫功課", "段考複習", "考試準備"]:
            color_id = "10"
            target_cal_id = task_calendar_id
        else:
            target_cal_id = study_calendar_id
            
        desc = "[Life-Agent 自動生成]"
        if event.get("note"):
            desc += f"\n備註：{event['note']}"
            
        url_create = f"https://www.googleapis.com/calendar/v3/calendars/{target_cal_id}/events"
        payload = {
            "summary": event["name"],
            "description": desc,
            "start": {
                "dateTime": start_iso,
                "timeZone": "Asia/Taipei"
            },
            "end": {
                "dateTime": end_iso,
                "timeZone": "Asia/Taipei"
            },
            "colorId": color_id,
            "extendedProperties": {
                "private": {
                    "source": "life-agent"
                }
            }
        }
        try:
            res = make_gcal_request("POST", url_create, json=payload)
            if res and res.status_code == 200:
                print(f"已寫入 Google Calendar 行程: {sh:02d}:{sm:02d}-{eh:02d}:{em:02d} [{c_type}] {event['name']}")
            else:
                print(f"寫入 Google Calendar 失敗: {res.status_code if res else 'No Response'}")
        except Exception as e:
            print(f"寫入 Google Calendar 異常: {e}")

    # 5.5 更新 Notion 中的書籍追蹤位置狀態做為跨日轉移
    try:
        today_subjects = {get_title(s, "科目名稱") for s in today_fixed_schedules if get_title(s, "科目名稱")}
        
        yesterday_todos = query_database_all(TODO_ACTIVITIES_DB_ID, {
            "filter": {
                "and": [
                    {"property": "截止或考試日期", "date": {"equals": yesterday_str}}
                ]
            }
        })
        yesterday_todos = [t for t in yesterday_todos if get_title(t, "名稱") and get_title(t, "名稱").strip() != ""]
        yesterday_subjects = {get_rich_text(t, "相關科目") for t in yesterday_todos if get_rich_text(t, "相關科目")}
        yesterday_subjects = {sub for sub in yesterday_subjects if sub and sub.lower() != "無"}
        
        tracker_results = query_database_all(BOOK_TRACKER_DB_ID)
        tracker_map = {get_title(r, "科目/物品名稱"): r["id"] for r in tracker_results if get_title(r, "科目/物品名稱")}
        
        for sub in today_subjects:
            if sub in tracker_map:
                update_page(tracker_map[sub], {"目前位置": {"select": {"name": "在學校"}}})
                update_page(tracker_map[sub], {"Currently_At": {"select": {"name": "在學校"}}})
                
        for sub in yesterday_subjects:
            if sub in tracker_map:
                update_page(tracker_map[sub], {"目前位置": {"select": {"name": "在家裡"}}})
                update_page(tracker_map[sub], {"Currently_At": {"select": {"name": "在家裡"}}})
        print("已成功進行跨日書籍追蹤位置自動轉移。")
    except Exception as e:
        print(f"書籍位置狀態自動轉移失敗: {e}")

    # 5.8 計算出門要帶去的物品 (回學校前要準備的補習、作業與課堂)
    bring_to_school = []
    today_cram_list = []
    today_todo_list = []
    try:
        today_school_subjects = {get_title(s, "科目名稱") for s in today_fixed_schedules if get_title(s, "科目名稱")}
        
        time_min_b = f"{today_str}T08:00:00+08:00"
        time_max_b = f"{today_str}T23:59:59+08:00"
        params_b = {
            "timeMin": time_min_b,
            "timeMax": time_max_b,
            "singleEvents": "true",
            "orderBy": "startTime"
        }
        
        res_class_b = make_gcal_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/{class_calendar_id}/events", params=params_b)
        if res_class_b and res_class_b.status_code == 200:
            for ev in res_class_b.json().get("items", []):
                summary = ev.get("summary", "")
                start_time_str = ev.get("start", {}).get("dateTime", "")
                is_cram = False
                if start_time_str:
                    try:
                        hour = int(start_time_str.split("T", 1)[1][:2])
                        if hour >= 17:
                            is_cram = True
                    except:
                        pass
                summary_lower = summary.lower()
                if any(k in summary_lower for k in ["pc", "mec", "補習", "補"]):
                    is_cram = True
                if is_cram:
                    start_formatted = start_time_str[11:16] if start_time_str else ""
                    today_cram_list.append((summary, start_formatted))
                    
        res_task_b = make_gcal_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/{task_calendar_id}/events", params=params_b)
        if res_task_b and res_task_b.status_code == 200:
            for ev in res_task_b.json().get("items", []):
                if ev.get("extendedProperties", {}).get("private", {}).get("source") in ["life-agent", "life-agent-ai-scheduled"]:
                    summary = ev.get("summary", "")
                    start_time_str = ev.get("start", {}).get("dateTime", "")
                    start_formatted = start_time_str[11:16] if start_time_str else ""
                    desc = ev.get("description", "")
                    today_todo_list.append((summary, start_formatted, desc))

        today_required_subjects = set(today_school_subjects)
        
        def parse_subject_from_title_b(title, desc=""):
            if desc:
                import re
                m = re.search(r"科目：\s*([^\n]+)", desc)
                if m:
                    return m.group(1).strip()
            for subj in ["數學", "物理", "英文", "歷史", "地科", "化學", "國文", "生物", "地理", "公民"]:
                if subj in title:
                    return subj
            return None

        subj_sources = {}
        for sub in today_school_subjects:
            subj_sources[sub] = "課堂"
            
        for summary, _ in today_cram_list:
            subj = parse_subject_from_title_b(summary)
            if subj:
                today_required_subjects.add(subj)
                existing_src = subj_sources.get(subj, "")
                subj_sources[subj] = f"{existing_src}+補習" if existing_src else "補習"
                
        for summary, _, desc in today_todo_list:
            subj = parse_subject_from_title_b(summary, desc)
            if subj:
                today_required_subjects.add(subj)
                existing_src = subj_sources.get(subj, "")
                subj_sources[subj] = f"{existing_src}+作業" if existing_src else "作業"

        tracker_results = query_database_all(BOOK_TRACKER_DB_ID)
        location_tracker = {}
        for r in tracker_results:
            name = get_title(r, "科目/物品名稱")
            loc = get_select(r, "目前位置")
            if name:
                location_tracker[name] = (loc, r["id"])

        for subj in today_required_subjects:
            label = subj_sources.get(subj, "課堂")
            if subj in location_tracker:
                loc, page_id = location_tracker[subj]
                if loc == "在家裡":
                    bring_to_school.append((subj, label, page_id))
            else:
                try:
                    new_pg = create_page(BOOK_TRACKER_DB_ID, {
                        "科目/物品名稱": {"title": [{"text": {"content": subj}}]},
                        "Currently_At": {"select": {"name": "在家裡"}},
                        "目前位置": {"select": {"name": "在家裡"}}
                    })
                    page_id = new_pg.get("id")
                    if page_id:
                        bring_to_school.append((subj, label, page_id))
                except Exception as e:
                    print(f"建立書籍追蹤頁面失敗 {subj}: {e}")
        bring_to_school.sort(key=lambda x: x[0])
    except Exception as e:
        print(f"計算出門攜帶物品失敗: {e}")
        bring_to_school = []

    # 6. Telegram 發送明早出門帶書通知
    cram_detail_b = "\n".join([f"  ● {item} ({time_str})" for item, time_str in today_cram_list]) if today_cram_list else "  無"
    todo_detail_b = "\n".join([f"  ● {item} ({time_str})" for item, time_str, _ in today_todo_list]) if today_todo_list else "  無"

    if bring_to_school:
        bring_to_school_section = "\n".join([f"  [ ] {x[0]} ({x[1]})" for x in bring_to_school])
    else:
        bring_to_school_section = "  今日無須帶任何課本/物品去學校。"

    telegram_msg = f"""【Life-Agent 晨間通知 - 書包檢查與日程】

[今天在學校與回學校後的補習與作業]
--------------------------------
當天課程科目：{', '.join(today_school_subjects) if today_school_subjects else '無'}
補習日程：
{cram_detail_b}

作業排程：
{todo_detail_b}
--------------------------------

[回學校前必帶去學校的科目]
--------------------------------
{bring_to_school_section}
--------------------------------
(請確認相關科目的課本/講義已放入包包)"""

    # 7. 隨手記一日總結與碎片提取整合
    daily_summary_text = ""
    memos = []
    if TEMP_INBOX_DB_ID:
        try:
            inbox_filter = {
                "filter": {
                    "and": [
                        {"property": "日期", "date": {"equals": today_str}}
                    ]
                }
            }
            inbox_entries = query_database_all(TEMP_INBOX_DB_ID, inbox_filter)
            inbox_entries = [x for x in inbox_entries if get_title(x, "內容").strip() != ""]
            
            if inbox_entries:
                print(f"偵測到今日隨手記暫存區共有 {len(inbox_entries)} 筆資料，進行一日總結與碎片資料處理...")
                
                # 下載所有照片
                pil_images = []
                for entry in inbox_entries:
                    photo_url = get_first_file_url(entry, "照片上傳")
                    if photo_url:
                        try:
                            resp = request_with_retry("GET", photo_url)
                            if resp.status_code == 200:
                                pil_images.append(Image.open(io.BytesIO(resp.content)))
                        except Exception as e:
                            print(f"下載暫存照片失敗: {e}")
                            
                # 呼叫 Gemini 進行總結與提取
                inbox_texts = [f"- {get_title(x, '內容')}" for x in inbox_entries]
                inbox_texts_str = "\n".join(inbox_texts)
                
                prompt = f"""
                請分析以下使用者今天隨手記下的碎片文字與照片，完成三件事：
                
                1. 撰寫一篇溫馨、生動、完整的【一日總結】（日記）。請以繁體中文撰寫，字數約 150-300 字。
                2. 提取出所有不屬於學業課業、消費記帳、具體活動行程的【一般雜項備忘/提醒】（例如「去pc拿水壺」、「打電話給媽媽」），整理為 memos 陣列。
                3. 從這些碎片資料中，分析並提取出以下三類標準資料（若無則不提取）：
                   - "add_expense" (消費/記帳記錄)：提取 name(品項), amount(金額，整數), category(分類: 飲食、交通、娛樂、學習)
                   - "add_todo" (學校作業/小考待辦)：提取 name(簡短事項描述。若提及了需時，例如「需3小時」、「需180分鐘」，請在 name 的末尾加上「 (需X小時)」或「 (需X分鐘)」，例如「英文補課 (需3小時)」), subject(科目), due_date(格式 YYYY-MM-DD，若無為 "#"), type(作業、小考、段考、回條、報名表)
                   - "add_activity" (一次性活動)：提取 name(活動名稱), date(格式 YYYY-MM-DD，若是跨日範圍如「7/15-7/19」請填「YYYY-MM-DD/YYYY-MM-DD」，例如「2026-07-15/2026-07-19」), type(講座、營隊、比賽、志工、休閒、其他)
                   
                碎片文字內容如下：
                {inbox_texts_str}
                
                請務必以 JSON 格式回覆，結構如下（不要包含 ```json 等 markdown 標記）：
                {{
                  "daily_summary": "今日的一日總結內容...",
                  "memos": [
                    "去pc拿水壺"
                  ],
                  "actions": [
                    {{
                      "action": "add_expense",
                      "data": {{"name": "品項名稱", "amount": 150, "category": "飲食"}}
                    }}
                  ]
                }}
                """
                
                schema = {
                    "type": "object",
                    "properties": {
                        "daily_summary": {"type": "string"},
                        "memos": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "action": {"type": "string", "enum": ["add_expense", "add_todo", "add_activity"]},
                                    "data": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "amount": {"type": "integer"},
                                            "category": {"type": "string"},
                                            "subject": {"type": "string"},
                                            "due_date": {"type": "string"},
                                            "type": {"type": "string"},
                                            "date": {"type": "string"}
                                        }
                                    }
                                },
                                "required": ["action", "data"]
                            }
                        }
                    },
                    "required": ["daily_summary", "memos", "actions"]
                }
                model = genai.GenerativeModel('gemini-3.1-flash-lite')
                if pil_images:
                    response = safe_generate_content(model, [prompt] + pil_images, generation_config={"response_mime_type": "application/json", "response_schema": schema})
                else:
                    response = safe_generate_content(model, prompt, generation_config={"response_mime_type": "application/json", "response_schema": schema})
                    
                res_json = safe_load_json(response.text)
                daily_summary_text = res_json.get("daily_summary", "")
                memos = res_json.get("memos", [])
                actions = res_json.get("actions", [])
                
                # 同步雜項備忘至 Google Calendar
                for memo in memos:
                    write_misc_to_gcal(memo, today_str)
                
                # 處理提取的動作
                for act in actions:
                    action_type = act.get("action")
                    d = act.get("data", {})
                    if action_type == "add_expense":
                        if LEDGER_DB_ID:
                            create_page(LEDGER_DB_ID, {
                                "項目名稱": {"title": [{"text": {"content": d.get("name", "隨手記消費")}}]},
                                "日期": {"date": {"start": today_str}},
                                "金額": {"number": int(d.get("amount", 0))},
                                "分類": {"select": {"name": d.get("category", "飲食")}}
                            })
                            print(f"已從隨手記自動寫入消費: {d.get('name')} = {d.get('amount')}元")
                    elif action_type == "add_todo":
                        if TODO_ACTIVITIES_DB_ID:
                            create_page(TODO_ACTIVITIES_DB_ID, {
                                "名稱": {"title": [{"text": {"content": d.get("name", "未命名事項")}}]},
                                "類型": {"select": {"name": d.get("type", "作業")}},
                                "截止或考試日期": {"date": {"start": d.get("due_date", today_str) if d.get("due_date") != "#" else today_str}},
                                "相關科目": {"rich_text": [{"text": {"content": d.get("subject", "無")}}]},
                                "總頁數/題數": {"number": 1},
                                "已完成頁數/題數": {"number": 0}
                            })
                            print(f"已從隨手記自動寫入待辦: {d.get('name')}")
                    elif action_type == "add_activity":
                        if ACTIVITIES_DB_ID:
                            date_val = d.get("date", today_str)
                            start_date = date_val.strip()
                            end_date = None
                            if "/" in date_val:
                                parts = date_val.split("/")
                                start_date = parts[0].strip()
                                end_date = parts[1].strip()
                            
                            date_prop = {"start": start_date}
                            if end_date:
                                date_prop["end"] = end_date
                                
                            create_page(ACTIVITIES_DB_ID, {
                                "活動名稱": {"title": [{"text": {"content": d.get("name", "未命名活動")}}]},
                                "日期": {"date": date_prop},
                                "類型": {"select": {"name": d.get("type", "其他")}}
                            })
                            write_activity_to_gcal(d.get("name"), date_val, d.get("type", "其他"))
                            print(f"已從隨手記自動寫入活動: {d.get('name')}")
                            
                # 清理已處理的暫存資料
                for entry in inbox_entries:
                    delete_page(entry["id"])
                print(f"已成功清理/封存 {len(inbox_entries)} 筆暫存資料。")
                
        except Exception as e:
            print(f"隨手記暫存與一日總結處理失敗: {e}")

    memos_section = ""
    if memos:
        memos_section = "\n\n【今日雜項提醒】\n" + "\n".join([f"  ● {x}" for x in memos])

    if daily_summary_text:
        telegram_msg += f"\n\n【一日生活總結】\n{daily_summary_text}"
    if memos_section:
        telegram_msg += memos_section

    reply_markup = None
    if bring_to_school:
        inline_buttons = []
        for x in bring_to_school:
            if len(x) >= 3:
                short_id = x[2].replace("-", "")
                inline_buttons.append([{"text": f"✅ 已將 {x[0]} 帶去學校", "callback_data": f"bs:{short_id}"}])
        if inline_buttons:
            reply_markup = {"inline_keyboard": inline_buttons}

    send_telegram_message(telegram_msg, reply_markup=reply_markup)

def run_mode_shortcut(today_dt):
    print("【隨手記 SHORTCUT 模式】將輸入寫入 Notion 暫存區")
    today_str = today_dt.strftime("%Y-%m-%d")
    
    # 讀取輸入 (優先從環境變數，次之從 command-line 參數)
    shortcut_text = os.environ.get("SHORTCUT_TEXT")
    shortcut_photo_url = os.environ.get("SHORTCUT_PHOTO_URL")
    
    for arg in sys.argv:
        if arg.startswith("--text="):
            shortcut_text = arg.split("=", 1)[1]
        elif arg.startswith("--photo_url="):
            shortcut_photo_url = arg.split("=", 1)[1]
            
    if not shortcut_text and not shortcut_photo_url:
        print("未偵測到任何隨手記文字或照片網址輸入，跳過寫入。")
        return
        
    if not TEMP_INBOX_DB_ID:
        print("警告: 未設定 NOTION_TEMP_INBOX_DB_ID，無法寫入暫存區。")
        return
        
    properties = {
        "內容": {"title": [{"text": {"content": shortcut_text or "隨手記照片"}}]},
        "日期": {"date": {"start": today_str}}
    }
    if shortcut_photo_url:
        properties["照片上傳"] = {
            "files": [{"name": "shortcut_photo.jpg", "type": "external", "external": {"url": shortcut_photo_url}}]
        }
        
    try:
        create_page(TEMP_INBOX_DB_ID, properties)
        print("已成功將隨手記碎片資料寫入 Notion 暫存區！")
    except Exception as e:
        print(f"寫入 Notion 暫存區失敗: {e}")

# ==================== 主程式入口 ====================

def main():
    tw_tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tw_tz)
    
    mode = None
    if len(sys.argv) > 1:
        for arg in sys.argv:
            if arg.startswith("--mode="):
                mode = arg.split("=")[1].upper()
            elif arg == "--mode":
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    mode = sys.argv[idx + 1].upper()

    if not mode:
        if os.environ.get("SHORTCUT_TEXT") or os.environ.get("SHORTCUT_PHOTO_URL"):
            mode = "SHORTCUT"
        elif 15 <= now.hour <= 20:
            mode = "A"
        elif now.hour >= 22 or now.hour <= 2:
            mode = "B"
        else:
            mode = "A"

    print(f"當前台灣時間: {now.strftime('%Y-%m-%d %H:%M:%S')}，執行模式: {mode}")

    test_date_str = os.environ.get("TEST_DATE")
    if test_date_str:
        today_dt = datetime.strptime(test_date_str, "%Y-%m-%d").replace(tzinfo=tw_tz)
        print(f"使用測試日期: {today_dt.strftime('%Y-%m-%d')}")
    else:
        today_dt = now

    # 執行 Telegram 指令處理
    process_telegram_commands(today_dt)

    if mode == "A":
        run_mode_a(today_dt)
    elif mode == "B":
        run_mode_b(today_dt)
    elif mode == "SHORTCUT":
        run_mode_shortcut(today_dt)
    else:
        print(f"未知的執行模式: {mode}")

if __name__ == "__main__":
    main()
