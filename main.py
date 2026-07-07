import os
import sys
import requests
import json
import io
import pytz
from datetime import datetime, timedelta, date
from PIL import Image
import google.generativeai as genai
import re

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

# Notion API Headers
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

# 預估時間基準值 (分鐘)
DEFAULT_DURATION = {
    "作業": 45,
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
            
        res = requests.post(url, headers=HEADERS, json=payload)
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
    res = requests.post(url, headers=HEADERS, json=data)
    res.raise_for_status()
    return res.json()

def update_page(page_id, properties):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {
        "properties": properties
    }
    res = requests.patch(url, headers=HEADERS, json=data)
    res.raise_for_status()
    return res.json()

def delete_page(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    data = {"archived": True}
    res = requests.patch(url, headers=HEADERS, json=data)
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
        res = requests.get(url, headers=HEADERS)
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

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未設定，無法發送 Telegram 通知。")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        res = requests.post(url, json=payload)
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
        res = requests.post(url, json=payload, headers=headers)
        res.raise_for_status()
        return f'Success (status {res.status_code})'
    except Exception as e:
        return f'Error: {e}'

def get_telegram_file_url(file_id):
    if not TELEGRAM_BOT_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}"
    res = requests.get(url)
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
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
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
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
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
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
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

def process_telegram_commands(today_dt):
    if not TELEGRAM_BOT_TOKEN:
        print("未設定 TELEGRAM_BOT_TOKEN，跳過指令處理。")
        return
        
    print("正在檢查 Telegram 新指令...")
    today_str = today_dt.strftime("%Y-%m-%d")
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(url)
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
                    name = data.get("name")
                    actual_time_str = data.get("actual_time")
                    time_spent = None
                    if actual_time_str and actual_time_str != "#":
                        try:
                            time_spent = int(actual_time_str)
                        except:
                            pass
                            
                    if not name or name == "#":
                        send_telegram_message("無法識別要完成的事項名稱。")
                        continue
                        
                    # 搜尋未完成的任務
                    query = {
                        "filter": {
                            "and": [
                                {"property": "名稱", "title": {"contains": name}}
                            ]
                        }
                    }
                    results = query_database_all(TODO_ACTIVITIES_DB_ID, query)
                    uncompleted = [r for r in results if not is_task_completed(r)]
                    if uncompleted:
                        target = uncompleted[0]
                        total_pages = get_number(target, "總頁數/題數") or 1
                        update_properties = {
                            "已完成頁數/題數": {"number": total_pages}
                        }
                        if time_spent is not None:
                            update_properties["實際耗時"] = {"number": time_spent}
                        update_page(target["id"], update_properties)
                        time_msg = f"，耗時 {time_spent} 分鐘" if time_spent is not None else ""
                        send_telegram_message(f"已將待辦【{get_title(target, '名稱')}】標記為完成{time_msg}。")
                    else:
                        send_telegram_message(f"找不到名稱包含【{name}】且未完成的待辦事項。")
                        
                elif action == "add_activity":
                    name = data.get("name") or "未命名活動"
                    date_val = data.get("date") or today_str
                    a_type = data.get("type") or "其他"
                    
                    if not is_valid_date_format(date_val):
                        date_val = today_str
                    if a_type not in ["講座", "營隊", "比賽", "志工", "休閒", "其他"]:
                        a_type = "其他"
                    
                    properties = {
                        "活動名稱": {"title": [{"text": {"content": name}}]},
                        "日期": {"date": {"start": date_val.strip()}},
                        "類型": {"select": {"name": a_type}}
                    }
                    create_page(ACTIVITIES_DB_ID, properties)
                    send_telegram_message(f"已自動分析並新增活動：{name} (日期: {date_val}, 類型: {a_type})")
                    
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
                    # generic_todo or fallback
                    name = data.get("name") or text
                    date_val = data.get("date")
                    
                    properties = {
                        "名稱": {"title": [{"text": {"content": name}}]},
                        "類型": {"select": {"name": "作業"}}
                    }
                    if date_val and is_valid_date_format(date_val):
                        properties["截止或考試日期"] = {"date": {"start": date_val.strip()}}
                        
                    create_page(TODO_ACTIVITIES_DB_ID, properties)
                    send_telegram_message(f"已自動新增備忘待辦：{name}")
                    
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
                    resp = requests.get(file_url)
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
                    
                    todo_query = {
                        "filter": {
                            "and": [
                                {"property": "名稱", "title": {"contains": name}}
                            ]
                        }
                    }
                    candidates = query_database_all(TODO_ACTIVITIES_DB_ID, todo_query)
                    target_row = None
                    for row in candidates:
                        if not is_task_completed(row):
                            target_row = row
                            break
                            
                    if target_row:
                        total_pages = get_number(target_row, "總頁數/題數") or 1
                        time_spent = 45
                        if actual_time.isdigit():
                            time_spent = int(actual_time)
                            
                        update_properties = {
                            "已完成頁數/題數": {"number": total_pages},
                            "實際耗時": {"number": time_spent}
                        }
                        update_page(target_row["id"], update_properties)
                        send_telegram_message(f"已將待辦【{get_title(target_row, '名稱')}】標記為完成，耗時 {time_spent} 分鐘。")
                    else:
                        send_telegram_message(f"找不到名稱包含【{name}】且未完成的待辦事項。")

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
                                
                    # 2. 寫入一次性行程與請假/補課
                    # 為了避免在同個日期重複，我們先按日期分組，將有新日程的那些日期上原本由 Bot 建立的日程清空
                    dates_to_clear = {e.get("date") for e in events_list if e.get("date")}
                    for d in dates_to_clear:
                        clear_query = {
                            "filter": {
                                "and": [
                                    {"property": "日期", "date": {"equals": d}}
                                ]
                            }
                        }
                        day_events = query_database_all(WEEKLY_CALENDAR_DB_ID, clear_query)
                        bot_user_id = get_bot_user_id()
                        for ev in day_events:
                            created_by_id = ev.get("created_by", {}).get("id")
                            if bot_user_id and created_by_id == bot_user_id:
                                delete_page(ev["id"])
                                
                    # 寫入新日程
                    for ev in events_list:
                        ev_date = ev.get("date")
                        ev_name = ev.get("name")
                        ev_start = ev.get("start")
                        ev_end = ev.get("end")
                        ev_type = ev.get("type") or "上課"
                        if ev_date and ev_name and ev_start and ev_end:
                            create_page(WEEKLY_CALENDAR_DB_ID, {
                                "行程名稱": {"title": [{"text": {"content": ev_name}}]},
                                "日期": {"date": {"start": ev_date}},
                                "開始時間": {"rich_text": [{"text": {"content": ev_start}}]},
                                "結束時間": {"rich_text": [{"text": {"content": ev_end}}]},
                                "行程類型": {"select": {"name": ev_type}}
                            })
                            events_added += 1
                            
                    send_telegram_message(f"成功匯入日程！\n- 新增固定課表：{fixed_added} 筆\n- 規劃行事曆事件：{events_added} 筆")
        except Exception as proc_err:
            print(f"處理指令出錯 [{text}]: {proc_err}")
            send_telegram_message(f"處理指令出錯：{proc_err}")

    if max_update_id > 0:
        try:
            ack_url = f"{url}?offset={max_update_id + 1}"
            requests.get(ack_url).raise_for_status()
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
    resp = requests.get(image_url)
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
    response = model.generate_content([
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_todo_photo(image_url, today_str):
    print(f"開始分析聯絡簿/考卷/回條照片: {image_url[:60]}...")
    resp = requests.get(image_url)
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
    response = model.generate_content([
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_activity_brochure(image_url, user_instruction=""):
    print(f"開始分析活動簡章照片: {image_url[:60]}...")
    resp = requests.get(image_url)
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
    請僅返回以下 JSON 格式（其中 events 是一個陣列，包含所有找到的事件，至少包含一個主事件。若完全不符身分，請返回空的 events 陣列），不要包含 any markdown 標記：
    {
      "events": [
        {
          "name": "活動名稱 - 線上初賽",
          "type": "比賽",
          "date": "2026-07-07",
          "note": "初賽將於線上舉行"
        },
        {
          "name": "活動名稱 - 報名截止",
          "type": "其他",
          "date": "2026-06-10",
          "note": "需組隊報名，高中組3人"
        }
      ]
    }
    """
    model = genai.GenerativeModel('gemini-3.1-flash-lite')
    response = model.generate_content([
        {
            'mime_type': mime_type,
            'data': content
        },
        prompt
    ], generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def analyze_calendar_image_bytes(content, today_str):
    mime_type = get_file_mime_type(content)
    prompt = f"""
    請幫我分析這張行事曆、功課表或課表照片，提取其中所有的日常固定課表與一次性日程事件（包括活動、志工、比賽、請假、停課、補課等）。
    
    今天日期為：{today_str}（請以此基準年份和日期，正確推算照片中的年月日，格式皆為 YYYY-MM-DD）。
    
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
    response = model.generate_content([
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
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    return safe_load_json(response.text)

def route_and_parse_natural_text(text_content, today_str):
    prompt = f"""
    請幫我分析以下使用者的日常文字訊息，並自動判定他們想要執行的動作。基準日期為：{today_str}。
    
    可判定的動作（action）與其對應的提取資料（data）如下：
    
    1. action: "add_todo" (新增功課、作業、小考、考試準備等待辦事項)
       提取 data 欄位：
       - name (功課/待辦事項名稱或描述，請使用簡短的繁體中文，且不要包含科目名稱，例如「英文閱讀報告」-> name為「閱讀報告」)
       - subject (相關科目，例如「數學」、「英文」、「物理」等，若無請填 "無")
       - due_date (截止日期，格式為 YYYY-MM-DD。若無提到請填 "#")
       - type (類型，必須是以下之一："作業"、"小考"、"段考"、"回條"、"報名表"、"活動")
       
    2. action: "complete_todo" (標記某個待辦事項/功課為已完成)
       提取 data 欄位：
       - name (要標記完成的事項關鍵字/名稱)
       - actual_time (實際耗時，必須是整數數字字串，表示分鐘，例如 "60"。若未提及則填 "#")
       
    3. action: "add_activity" (新增一次性活動、比賽、講座、營隊等)
       提取 data 欄位：
       - name (活動名稱)
       - date (活動日期，格式為 YYYY-MM-DD)
       - type (類型，必須是以下之一："講座"、"營隊"、"比賽"、"志工"、"休閒"、"其他")
       
    4. action: "add_expense" (記帳、新增一筆消費記錄)
       提取 data 欄位：
       - name (消費項目名稱或商店名稱，例如 "麥當勞"、"7-11 飲料")
       - amount (消費總金額，必須是整數數字)
       - category (分類，必須是以下之一："飲食"、"交通"、"娛樂"、"學習")
       
    5. action: "generic_todo" (不符合以上，但屬於一般隨手記下的待辦/備忘)
       提取 data 欄位：
       - name (待辦名稱)
       - date (時間/日期，格式為 YYYY-MM-DD。若無提到請填 "#")

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
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
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

    # 2. 書包物品精準檢查
    # 2.1 撈取明天所需物品與科目
    tomorrow_vacation = is_vacation(tomorrow_dt)
    tomorrow_vacation_type = "暑假" if tomorrow_vacation else "學期中"
    
    # 撈取明天課表
    schedule_filter = {
        "filter": {
            "and": [
                {"property": "星期", "number": {"equals": tomorrow_w}},
                {"property": "作息類型", "select": {"equals": tomorrow_vacation_type}}
            ]
        }
    }
    tomorrow_schedules = query_database_all(FIXED_SCHEDULE_DB_ID, schedule_filter)
    tomorrow_subjects = {get_title(s, "科目名稱") for s in tomorrow_schedules if get_title(s, "科目名稱")}
    
    # 撈取明天截止或明天要考試的待辦
    todo_tomorrow_filter = {
        "filter": {
            "and": [
                {"property": "截止或考試日期", "date": {"equals": tomorrow_str}}
            ]
        }
    }
    tomorrow_todos = query_database_all(TODO_ACTIVITIES_DB_ID, todo_tomorrow_filter)
    
    # 建立明天要帶去學校的物品清單 (無 emoji 標記)
    tomorrow_required_items = {} # {物品/科目: 標籤}
    
    # 固定課表需要的科目為一般重要
    for sub in tomorrow_subjects:
        tomorrow_required_items[sub] = "課堂課本"
        
    for t in tomorrow_todos:
        sub = get_rich_text(t, "相關科目")
        t_type = get_select(t, "類型")
        t_name = get_title(t, "名稱")
        
        label = "明天作業"
        if t_type in ["回條", "報名表"]:
            label = "重要回條"
        elif t_type in ["小考", "段考"]:
            label = "考試科目"
            
        if sub and sub.lower() != "無":
            tomorrow_required_items[sub] = label
        else:
            tomorrow_required_items[t_name] = label

    # 2.2 預覽今晚至未來三天內讀書/作業所需之課本 (包含已逾期、未來3天內截止、或沒有設定截止日期的所有未完成任務科目)
    preview_end_dt = today_dt + timedelta(days=2)
    preview_end_str = preview_end_dt.strftime("%Y-%m-%d")
    
    raw_study_todos = query_database_all(TODO_ACTIVITIES_DB_ID)
    study_todos = [t for t in raw_study_todos if not is_task_completed(t)]
    future_study_subjects = {} # {科目: 標籤}
    for t in study_todos:
        due = get_date(t, "截止或考試日期")
        # 篩選條件：無截止日期，或截止日期在未來3天之內(含逾期)
        if not due or due <= preview_end_str:
            sub = get_rich_text(t, "相關科目")
            if sub and sub.lower() != "無":
                t_type = get_select(t, "類型")
                t_name = get_title(t, "名稱")
                lbl = "功課複習"
                if t_type in ["小考", "段考"]:
                    lbl = "衝刺準備"
                future_study_subjects[sub] = f"{lbl} ({t_name[:12]})"

    # 2.3 讀取教科書位置追蹤庫
    tracker_results = query_database_all(BOOK_TRACKER_DB_ID)
    location_tracker = {} # {物品名稱: (目前位置, page_id)}
    for r in tracker_results:
        name = get_title(r, "科目/物品名稱")
        loc = get_select(r, "目前位置")
        if name:
            location_tracker[name] = (loc, r["id"])

    # 2.4 計算明天出門要帶去的物品 (狀態在學校 -> 忽略；狀態在家裡 -> 要帶)
    bring_to_school = [] # list of tuples: (item, label)
    for item, label in tomorrow_required_items.items():
        if item in location_tracker:
            loc, page_id = location_tracker[item]
            if loc == "在家裡":
                bring_to_school.append((item, label))
        else:
            # 追蹤庫中沒有的物品，預設新增且預設在家裡 (以便之後提示需要帶去)
            bring_to_school.append((item, label))
            create_page(BOOK_TRACKER_DB_ID, {
                "科目/物品名稱": {"title": [{"text": {"content": item}}]},
                "目前位置": {"select": {"name": "在家裡"}}
            })

    # 2.5 計算今天放學要帶回的物品 (狀態在家裡 -> 忽略；狀態在學校 -> 要帶回)
    take_home = [] # list of tuples: (item, label)
    for item, label in future_study_subjects.items():
        if item in location_tracker:
            loc, page_id = location_tracker[item]
            if loc == "在學校":
                take_home.append((item, label))
        else:
            # 追蹤庫中沒有的物品，預設新增且預設在學校 (以便之後提示需要帶回)
            take_home.append((item, label))
            create_page(BOOK_TRACKER_DB_ID, {
                "科目/物品名稱": {"title": [{"text": {"content": item}}]},
                "目前位置": {"select": {"name": "在學校"}}
            })

    # 2.6 將兩個清單寫入明天 (tomorrow) Notion 行事曆的「今日攜帶清單」
    bring_to_school.sort(key=lambda x: x[0])
    take_home.sort(key=lambda x: x[0])
    bring_to_school_str = "\n".join([f"- {x[0]} ({x[1]})" for x in bring_to_school]) if bring_to_school else "無"
    take_home_str = "\n".join([f"- {x[0]} ({x[1]})" for x in take_home]) if take_home else "無"
    
    carry_note = f"【明早出門必帶】：\n{bring_to_school_str}\n\n【放學必帶回家】：\n{take_home_str}"
    
    # 尋找明天是否已有備忘 Page (無 emoji 標題)
    memo_title = "【攜帶備忘】明天出門與今日放學物品"
    memo_filter = {
        "filter": {
            "and": [
                {"property": "行程名稱", "title": {"equals": memo_title}},
                {"property": "日期", "date": {"equals": tomorrow_str}}
            ]
        }
    }
    existing_memos = query_database_all(WEEKLY_CALENDAR_DB_ID, memo_filter)
    if existing_memos:
        update_page(existing_memos[0]["id"], {
            "今日攜帶清單": {"rich_text": [{"text": {"content": carry_note}}]}
        })
    else:
        create_page(WEEKLY_CALENDAR_DB_ID, {
            "行程名稱": {"title": [{"text": {"content": memo_title}}]},
            "日期": {"date": {"start": tomorrow_str}},
            "行程類型": {"select": {"name": "休息"}},
            "今日攜帶清單": {"rich_text": [{"text": {"content": carry_note}}]}
        })

    # 3. 記帳統計與 LINE 發送
    today_ledger_filter = {
        "filter": {
            "and": [
                {"property": "日期", "date": {"equals": today_str}}
            ]
        }
    }
    today_ledgers = query_database_all(LEDGER_DB_ID, today_ledger_filter)
    total_spend = sum([get_number(x, "金額") or 0 for x in today_ledgers])

    # 組裝 Telegram 訊息 (移除 emoji 標註與理財提醒)
    telegram_msg = f"""
【Life-Agent 傍晚通知 - 書包檢查與記帳】

[明早出門必帶去學校！]
--------------------------------
{chr(10).join([f'  [ ] {x[0]} ({x[1]})' for x in bring_to_school]) if bring_to_school else '  [x] 沒有特別需要帶的'}
--------------------------------

[今天放學必帶回包包！]
--------------------------------
{chr(10).join([f'  [ ] {x[0]} ({x[1]})' for x in take_home]) if take_home else '  [x] 沒有需要特別帶回家的'}
--------------------------------
(帶回家的課本將供今晚與未來幾天的學習排程使用)

[今日消費統計]
- 總計花費：{total_spend} 元
"""
    send_telegram_message(telegram_msg)

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
    
    weighted_subjects = set()
    for t in yesterday_todos:
        total_p = get_number(t, "總頁數/題數") or 1
        completed_p = get_number(t, "已完成頁數/題數") or 0
        completed = (completed_p / total_p) * 100 if total_p > 0 else 0
        actual_time = get_number(t, "實際耗時") or 0
        t_type = get_select(t, "類型") or "作業"
        sub = get_rich_text(t, "相關科目")
        
        default_time = DEFAULT_DURATION.get(t_type, 45)
        if completed < 100 or actual_time > default_time:
            if sub and sub.lower() != "無":
                weighted_subjects.add(sub)
                print(f"昨日任務 [{get_title(t, '名稱')}] 未完成或超時，今日科目 [{sub}] 任務預估時間將乘以 1.3 倍。")

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
    uncompleted_todos = [t for t in raw_all_todos if not is_task_completed(t)]
    
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
    bot_user_id = get_bot_user_id()
    print(f"當前 Bot User ID: {bot_user_id}")

    # 讀取今天行事曆中的現有事件，保留使用者手動建立的，並作為固定行程（Busy Blocks）避開
    today_calendar_filter = {
        "filter": {
            "and": [
                {"property": "日期", "date": {"equals": today_str}},
                {"property": "行程名稱", "title": {"does_not_contain": "攜帶備忘"}}
            ]
        }
    }
    existing_events = []
    if WEEKLY_CALENDAR_DB_ID:
        try:
            existing_events = query_database_all(WEEKLY_CALENDAR_DB_ID, today_calendar_filter)
        except Exception as e:
            print(f"讀取今日行事曆失敗: {e}")

    # 分類：區分自動建立的（待清除）與使用者建立的（保留並視為固定行程）
    bot_event_ids_to_delete = []
    today_fixed_subject_names = {get_title(s, "科目名稱") for s in today_fixed_schedules if get_title(s, "科目名稱")}
    for row in existing_events:
        created_by_id = row.get("created_by", {}).get("id")
        name = get_title(row, "行程名稱")
        
        # 判斷是否為自動產生的自習/休息塊或重複性課表項目
        is_bot_generated_block = (
            name in ["自由休息與放鬆", "番茄鐘伸展休息"] or
            name.startswith("衝刺：") or
            name.startswith("提早準備：") or
            name.startswith("今日待辦：") or
            name in today_fixed_subject_names
        )
        
        if bot_user_id and created_by_id == bot_user_id and is_bot_generated_block:
            # 這是機器人自動生成的，需要刪除重建
            bot_event_ids_to_delete.append(row["id"])
        else:
            # 這是使用者手動加入的，或是腳本匯入的一次性行程/請假，保留
            # 如果是請假/停課/休息，不作為忙碌區塊（Fixed Busy Blocks）避開，以便釋放時間進行安排
            is_cancellation = ("請假" in name or "停課" in name or "休息!" in name or "(休息!)" in name)
            if is_cancellation:
                print(f"偵測到請假/停課標記行程 [{name}]，不將其視為忙碌區塊以釋放時間。")
                continue
                
            start_time_str = get_rich_text(row, "開始時間")
            end_time_str = get_rich_text(row, "結束時間")
            if start_time_str and end_time_str:
                try:
                    start_time_str = start_time_str.strip()
                    end_time_str = end_time_str.strip()
                    if ":" in start_time_str and ":" in end_time_str:
                        sh, sm = map(int, start_time_str.split(":"))
                        eh, em = map(int, end_time_str.split(":"))
                        fixed_events.append({
                            "name": name,
                            "start": sh * 60 + sm,
                            "end": eh * 60 + em,
                            "type": get_select(row, "行程類型") or "上課",
                            "is_user_event": True
                        })
                        print(f"偵測到保留行程/一次性事件，已視為固定行程: {start_time_str}-{end_time_str} {name}")
                except Exception as e:
                    print(f"解析保留行程時間失敗 [{name}]: {e}")
    for s in today_fixed_schedules:
        time_range = get_rich_text(s, "時間段")
        name = get_title(s, "科目名稱")
        
        # 1. 暑輔日期區間限制 (2026-07-13 至 2026-08-07)
        if name == "暑輔":
            curr_date = today_dt.date()
            if not (date(2026, 7, 13) <= curr_date <= date(2026, 8, 7)):
                print(f"今日 ({curr_date}) 不在暑輔期間 (7/13 - 8/7)，跳過固定行程 暑輔。")
                continue
                
        # 2. 請假/停課/休息判定
        is_canceled = False
        for ex in existing_events:
            ex_title = get_title(ex, "行程名稱")
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
                fixed_events.append({
                    "name": name,
                    "start": sh * 60 + sm,
                    "end": eh * 60 + em,
                    "type": "上課"
                })
            except Exception as e:
                print(f"解析課表時間段失敗 [{time_range}]: {e}")

    if not is_vac and not fixed_events:
        fixed_events.append({
            "name": "學校上課",
            "start": 8 * 60,
            "end": 17 * 60,
            "type": "上課"
        })

    # 讀取今天活動資料庫中的活動，並作為固定行程（Busy Blocks）避開 (預設 09:00 - 17:00)
    if ACTIVITIES_DB_ID:
        try:
            today_activity_filter = {
                "filter": {
                    "and": [
                        {"property": "日期", "date": {"equals": today_str}}
                    ]
                }
            }
            today_activities = query_database_all(ACTIVITIES_DB_ID, today_activity_filter)
            for act in today_activities:
                name = get_title(act, "活動名稱")
                a_type = get_select(act, "類型") or "其他"
                # 預設將活動排在 09:00 - 17:00 區間作為固定行程
                fixed_events.append({
                    "name": f"活動：{name}",
                    "start": 9 * 60,
                    "end": 17 * 60,
                    "type": a_type,
                    "is_user_event": True  # 不需要再寫回行事曆中，因為本來就存在於活動資料庫中
                })
                print(f"偵測到今日活動，已加入固定行程: {name}")
        except Exception as e:
            print(f"讀取今日活動失敗: {e}")

    # 初始化時間表：True 為可用自習，False 為佔用
    day_minutes = [False] * 1440
    for block_start, block_end in available_blocks:
        for m in range(block_start, block_end):
            day_minutes[m] = True
            
    for event in fixed_events:
        for m in range(event["start"], event["end"]):
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
        
        duration = 90 if t_type in ["小考", "段考"] else (15 if t_type in ["回條", "報名表"] else DEFAULT_DURATION.get(t_type, 45))
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
            duration = 45
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
        
        duration = DEFAULT_DURATION.get(t_type, 45)
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
    # 寫入固定上課行程 (保留原本的類型與使用者行程標記)
    for event in fixed_events:
        planned_events.append({
            "name": event["name"],
            "type": event.get("type", "上課"),
            "start": event["start"],
            "end": event["end"],
            "note": "",
            "is_user_event": event.get("is_user_event", False)
        })

    # 分配位置輔助函式
    def find_free_slot(duration):
        consecutive_free = 0
        start_idx = -1
        for i in range(1440):
            if day_minutes[i]:
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
        if task["name"] == "番茄鐘伸展休息":
            # 尋找 10 分鐘空擋
            slot = find_free_slot(10)
            if slot:
                start_m, end_m = slot
                for m in range(start_m, end_m):
                    day_minutes[m] = False
                planned_events.append({
                    "name": task["name"],
                    "type": "休息",
                    "start": start_m,
                    "end": end_m,
                    "note": ""
                })
            continue

        slot = find_free_slot(task["duration"])
        if slot:
            start_m, end_m = slot
            for m in range(start_m, end_m):
                day_minutes[m] = False
                
            # 核對課本位置，提供警報
            note = ""
            sub = task["subject"]
            if sub and sub != "無":
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

    # 填補剩餘可用自習時間為自由休息
    rest_start = -1
    for i in range(1440):
        if day_minutes[i]:
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

    # 5. 批次寫回 Notion
    # 僅刪除屬於機器人自動生成的現有事件
    for page_id in bot_event_ids_to_delete:
        delete_page(page_id)
    print(f"已清除今日自動生成行程共 {len(bot_event_ids_to_delete)} 筆。")

    for event in planned_events:
        if event.get("is_user_event"):
            # 使用者手動建立的行程原本就存在於 Notion 中，不重複寫入！
            continue
            
        sh, sm = divmod(event["start"], 60)
        eh, em = divmod(event["end"], 60)
        start_str = f"{sh:02d}:{sm:02d}"
        end_str = f"{eh:02d}:{em:02d}"
        
        properties = {
            "行程名稱": {"title": [{"text": {"content": event["name"]}}]},
            "日期": {"date": {"start": today_str}},
            "開始時間": {"rich_text": [{"text": {"content": start_str}}]},
            "結束時間": {"rich_text": [{"text": {"content": end_str}}]},
            "行程類型": {"select": {"name": event["type"]}},
            "備註": {"rich_text": [{"text": {"content": event["note"]}}]}
        }
        create_page(WEEKLY_CALENDAR_DB_ID, properties)
        print(f"已寫入行程: {start_str}-{end_str} [{event['type']}] {event['name']}")

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

    # 6. Telegram 發送今日日程 (無 emoji 格式)
    schedule_lines = []
    warning_alerts = []
    
    for event in planned_events:
        sh, sm = divmod(event["start"], 60)
        eh, em = divmod(event["end"], 60)
        line = f"{sh:02d}:{sm:02d} - {eh:02d}:{em:02d} | [{event['type']}] {event['name']}"
        if event["note"]:
            line += f"\n   注意: {event['note']}"
            warning_alerts.append(f"● {event['name']}: {event['note']}")
        schedule_lines.append(line)

    alert_section = ""
    if warning_alerts:
        alert_section = "【漏帶物品與課本警報】\n" + "\n".join(warning_alerts) + "\n\n"

    unplanned_msg = ""
    if unplanned_tasks:
        unique_unplanned = {t["name"] for t in unplanned_tasks if "番茄鐘" not in t["name"]}
        if unique_unplanned:
            unplanned_msg = "\n注意: 因時間不足未排入的待辦：\n" + "\n".join([f"- {t}" for t in unique_unplanned])

    telegram_msg = f"""
【Life-Agent 日程通知 - 時間管理與日程分配】

{alert_section}今日時間日程表 (Time Blocking - 番茄鐘專注版)：
--------------------------------
{chr(10).join(schedule_lines)}
--------------------------------
{unplanned_msg}

今日目標：專注 50 分鐘、放鬆 10 分鐘，不漏帶任何課本，穩定前進！
"""
    send_telegram_message(telegram_msg)

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
        if 15 <= now.hour <= 20:
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
    else:
        print(f"未知的執行模式: {mode}")

if __name__ == "__main__":
    main()
