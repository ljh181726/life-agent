import os
import sys
import pytz
from datetime import datetime, timedelta

# 解決 Windows 控制台 Emoji 與中文編碼問題
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# 將當前路徑加入 sys.path 以便 import main
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import main

# ==================== 模擬資料 ====================

# 1. 課表資料庫模擬 (星期日=7, 星期一=1...)
mock_fixed_schedule = [
    {"properties": {"科目名稱": {"title": [{"text": {"content": "數學"}}]}, "星期": {"number": 1}, "時間段": {"rich_text": [{"text": {"content": "08:10-09:50"}}]}, "作息類型": {"select": {"name": "學期中"}}, "是否可寫作業": {"checkbox": True}}},
    {"properties": {"科目名稱": {"title": [{"text": {"content": "英文"}}]}, "星期": {"number": 1}, "時間段": {"rich_text": [{"text": {"content": "10:10-12:00"}}]}, "作息類型": {"select": {"name": "學期中"}}, "是否可寫作業": {"checkbox": True}}},
    {"properties": {"科目名稱": {"title": [{"text": {"content": "歷史"}}]}, "星期": {"number": 1}, "時間段": {"rich_text": [{"text": {"content": "13:30-15:10"}}]}, "作息類型": {"select": {"name": "學期中"}}, "是否可寫作業": {"checkbox": False}}},
]

# 2. 待辦與活動資料庫模擬
# 假設今天為 2026-06-21 (星期日)，明天為 2026-06-22 (星期一)
# 昨天為 2026-06-20 (星期六)
mock_todo_activities = [
    # 昨天截止且未完成的作業 (用來觸發時間加權)
    {
        "id": "todo_y_1",
        "properties": {
            "名稱": {"title": [{"text": {"content": "數學 L2 習題"}}]},
            "類型": {"select": {"name": "作業"}},
            "截止或考試日期": {"date": {"start": "2026-06-20"}},
            "相關科目": {"rich_text": [{"text": {"content": "數學"}}]},
            "總頁數/題數": {"number": 10},
            "已完成頁數/題數": {"number": 5}, # 5/10 未完成
            "實際耗時": {"number": 60},
            "照片上傳": {"files": []}
        }
    },
    # 明天截止的作業 (需要帶去)
    {
        "id": "todo_t_1",
        "properties": {
            "名稱": {"title": [{"text": {"content": "英文 Writing 報告"}}]},
            "類型": {"select": {"name": "作業"}},
            "截止或考試日期": {"date": {"start": "2026-06-22"}},
            "相關科目": {"rich_text": [{"text": {"content": "英文"}}]},
            "總頁數/題數": {"number": 1},
            "已完成頁數/題數": {"number": 0},
            "實際耗時": {"number": None},
            "照片上傳": {"files": []}
        }
    },
    # 明天截止的重要回條 (需要帶去)
    {
        "id": "todo_t_2",
        "properties": {
            "名稱": {"title": [{"text": {"content": "家長同意書回條"}}]},
            "類型": {"select": {"name": "回條"}},
            "截止或考試日期": {"date": {"start": "2026-06-22"}},
            "相關科目": {"rich_text": [{"text": {"content": "無"}}]},
            "總頁數/題數": {"number": 1},
            "已完成頁數/題數": {"number": 0},
            "實際耗時": {"number": None},
            "照片上傳": {"files": []}
        }
    },
    # 4 天後 (2026-06-25) 截止的段考 (需要提早準備且今晚需要帶課本回家)
    {
        "id": "todo_f_1",
        "properties": {
            "名稱": {"title": [{"text": {"content": "歷史 L1-L3 段考"}}]},
            "類型": {"select": {"name": "段考"}},
            "截止或考試日期": {"date": {"start": "2026-06-25"}},
            "相關科目": {"rich_text": [{"text": {"content": "歷史"}}]},
            "總頁數/題數": {"number": 1},
            "已完成頁數/題數": {"number": 0},
            "實際耗時": {"number": None},
            "照片上傳": {"files": []}
        }
    },
    # 新上傳照片但欄位未填寫的待辦
    {
        "id": "todo_vision",
        "properties": {
            "名稱": {"title": []}, # 待辨識
            "類型": {"select": None},
            "截止或考試日期": {"date": None},
            "相關科目": {"rich_text": []},
            "總頁數/題數": {"number": None},
            "已完成頁數/題數": {"number": None},
            "實際耗時": {"number": None},
            "照片上傳": {"files": [{"type": "external", "external": {"url": "https://example.com/mock_receipt.jpg"}}]}
        }
    }
]

# 3. 科目與教科書位置追蹤模擬
mock_book_tracker = [
    {"id": "track_1", "properties": {"科目/物品名稱": {"title": [{"text": {"content": "數學"}}]}, "目前位置": {"select": {"name": "在家裡"}}}},
    {"id": "track_2", "properties": {"科目/物品名稱": {"title": [{"text": {"content": "英文"}}]}, "目前位置": {"select": {"name": "在學校"}}}},
    {"id": "track_3", "properties": {"科目/物品名稱": {"title": [{"text": {"content": "歷史"}}]}, "目目前位置": {"select": {"name": "在學校"}}, "目前位置": {"select": {"name": "在學校"}}}},
]

# 4. 記帳本模擬
mock_ledger = [
    # 今天已有的記帳
    {"properties": {"項目名稱": {"title": [{"text": {"content": "午餐便當"}}]}, "日期": {"date": {"start": "2026-06-21"}}, "金額": {"number": 120}, "分類": {"select": {"name": "飲食"}}}},
    # 新上傳收據照片未處理的記帳
    {
        "id": "ledger_vision",
        "properties": {
            "項目名稱": {"title": []},
            "日期": {"date": {"start": "2026-06-21"}},
            "金額": {"number": None},
            "分類": {"select": None},
            "收據照片": {"files": [{"type": "external", "external": {"url": "https://example.com/mock_invoice.jpg"}}]}
        }
    }
]

# 5. 每週行事曆模擬
mock_weekly_calendar = []

# 6. 活動資料庫模擬
mock_activities = [
    # 今天已有的活動
    {
        "id": "act_1",
        "properties": {
            "活動名稱": {"title": [{"text": {"content": "AI 科學黑客松比賽"}}]},
            "日期": {"date": {"start": "2026-06-21"}},
            "類型": {"select": {"name": "比賽"}},
            "簡章上傳": {"files": []},
            "備註": {"rich_text": []}
        }
    },
    # 新上傳簡章但欄位未填的活動
    {
        "id": "act_vision",
        "properties": {
            "活動名稱": {"title": []},
            "日期": {"date": None},
            "類型": {"select": None},
            "簡章上傳": {"files": [{"type": "external", "external": {"url": "https://example.com/mock_brochure.jpg"}}]},
            "備註": {"rich_text": []}
        }
    }
]

# 7. 隨手記暫存區模擬
mock_temp_inbox = []

# ==================== MOCKING Notion & Gemini API ====================

def mock_query_database_all(database_id, filter_payload=None):
    if database_id == main.FIXED_SCHEDULE_DB_ID:
        return mock_fixed_schedule
    elif database_id == main.TODO_ACTIVITIES_DB_ID:
        # 簡單過濾
        if filter_payload and "filter" in filter_payload:
            f = filter_payload["filter"]
            # 檢查是否過濾昨天
            if "equals" in str(f) and "2026-06-20" in str(f):
                return [x for x in mock_todo_activities if x["properties"]["截止或考試日期"]["date"] and x["properties"]["截止或考試日期"]["date"]["start"] == "2026-06-20"]
            # 檢查是否過濾明天
            if "equals" in str(f) and "2026-06-22" in str(f):
                return [x for x in mock_todo_activities if x["properties"]["截止或考試日期"]["date"] and x["properties"]["截止或考試日期"]["date"]["start"] == "2026-06-22"]
            # 檢查是否是圖片未處理的待辦
            if "照片上傳" in str(f) and "rich_text" in str(f):
                return [x for x in mock_todo_activities if x["id"] == "todo_vision"]
        return mock_todo_activities
    elif database_id == main.TEMP_INBOX_DB_ID:
        return mock_temp_inbox
    elif database_id == main.BOOK_TRACKER_DB_ID:
        return mock_book_tracker
    elif database_id == main.LEDGER_DB_ID:
        if filter_payload and "收據照片" in str(filter_payload):
            return [x for x in mock_ledger if x.get("id") == "ledger_vision"]
        return mock_ledger
    elif database_id == main.WEEKLY_CALENDAR_DB_ID:
        return mock_weekly_calendar
    elif database_id == main.ACTIVITIES_DB_ID:
        if filter_payload and "簡章上傳" in str(filter_payload):
            return [x for x in mock_activities if x.get("id") == "act_vision"]
        return mock_activities
    return []

def mock_update_page(page_id, properties):
    # 尋找並更新模擬物件
    for db in [mock_todo_activities, mock_book_tracker, mock_ledger, mock_weekly_calendar, mock_activities]:
        for item in db:
            if item.get("id") == page_id:
                for k, v in properties.items():
                    item["properties"][k] = v
                print(f"[Notion Mock API] 已更新 Page {page_id} 欄位: {list(properties.keys())}")
                return item
    return {}

def mock_create_page(database_id, properties):
    new_page = {
        "id": f"new_page_{len(mock_weekly_calendar) + 1}",
        "properties": properties
    }
    if database_id == main.WEEKLY_CALENDAR_DB_ID:
        mock_weekly_calendar.append(new_page)
    elif database_id == main.TEMP_INBOX_DB_ID:
        mock_temp_inbox.append(new_page)
    elif database_id == main.BOOK_TRACKER_DB_ID:
        mock_book_tracker.append(new_page)
    print(f"[Notion Mock API] 已新增 Page 至資料庫 {database_id[:10]}...: {properties.get('行程名稱', properties.get('科目/物品名稱', {}))}")
    return new_page

def mock_delete_page(page_id):
    global mock_weekly_calendar, mock_temp_inbox
    mock_weekly_calendar = [x for x in mock_weekly_calendar if x.get("id") != page_id]
    mock_temp_inbox = [x for x in mock_temp_inbox if x.get("id") != page_id]
    print(f"[Notion Mock API] 已刪除/封存 Page: {page_id}")
    return {}

def mock_analyze_activity_brochure(image_url, user_instruction=""):
    print(f"[Gemini Mock API] 辨識活動簡章 {image_url[:40]}...，特別指令: {user_instruction}")
    return {
        "events": [
            {
                "name": "2026 青年AI科學夏令營 - 第一期",
                "type": "營隊",
                "date": "2026-06-22",
                "note": f"時間：09:00-17:00，地點：台大，費用：免費 (指令：{user_instruction})" if user_instruction else "時間：09:00-17:00，地點：台大，費用：免費"
            },
            {
                "name": "2026 青年AI科學夏令營 - 報名截止",
                "type": "其他",
                "date": "2026-06-10",
                "note": "名額有限，報完為止"
            }
        ]
    }

def mock_analyze_receipt(image_url):
    print(f"[Gemini Mock API] 辨識收據照片 {image_url[:40]}...")
    return {
        "item_name": "7-11 咖啡與麵包",
        "amount": 75,
        "category": "飲食"
    }

def mock_analyze_todo_photo(image_url, today_str):
    print(f"[Gemini Mock API] 辨識聯絡簿照片 {image_url[:40]}...")
    return {
        "name": "數學課本 P.20-P.22 習題",
        "type": "作業",
        "due_date": "2026-06-22",
        "subject": "數學"
    }

def mock_send_telegram_message(message):
    print("\n========== 模擬 TELEGRAM 訊息發送 ==========")
    print(message)
    print("============================================\n")

# ==================== MOCKING Google Calendar API ====================

class MockResponse:
    def __init__(self, json_data, status_code):
        self.json_data = json_data
        self.status_code = status_code
    def json(self):
        return self.json_data

mock_gcal_events = []

def mock_make_gcal_request(method, url, headers=None, **kwargs):
    global mock_gcal_events
    if method == "GET":
        if "/events" in url:
            return MockResponse({"items": mock_gcal_events}, 200)
    elif method == "POST":
        if "/events" in url:
            json_body = kwargs.get("json", {})
            summary = json_body.get("summary")
            start = json_body.get("start", {}).get("dateTime")
            end = json_body.get("end", {}).get("dateTime")
            color_id = json_body.get("colorId")
            ext_props = json_body.get("extendedProperties", {})
            
            new_event = {
                "id": f"gcal_event_{len(mock_gcal_events) + 1}",
                "summary": summary,
                "description": json_body.get("description", ""),
                "start": json_body.get("start"),
                "end": json_body.get("end"),
                "colorId": color_id,
                "extendedProperties": ext_props
            }
            mock_gcal_events.append(new_event)
            print(f"[Google Calendar Mock API] 已建立行程: {start[11:16]}-{end[11:16]} [{color_id}] {summary}")
            return MockResponse(new_event, 200)
    elif method == "DELETE":
        parts = url.split("/")
        event_id = parts[-1]
        mock_gcal_events = [x for x in mock_gcal_events if x.get("id") != event_id]
        print(f"[Google Calendar Mock API] 已刪除行程 ID: {event_id}")
        return MockResponse({}, 204)
        
    return MockResponse({}, 404)

def mock_delete_google_calendar_event(access_token, calendar_id, event_id):
    global mock_gcal_events
    mock_gcal_events = [x for x in mock_gcal_events if x.get("id") != event_id]
    print(f"[Google Calendar Mock API] 已刪除行程 ID: {event_id}")
    return True

def mock_safe_generate_content(model, *args, **kwargs):
    prompt_arg = args[0]
    if isinstance(prompt_arg, list):
        prompt_str = prompt_arg[0]
    else:
        prompt_str = prompt_arg
        
    if "請分析以下使用者今天隨手記下的碎片文字與照片" in prompt_str:
        import json
        class MockGenerativeResponse:
            def __init__(self, text):
                self.text = text
        return MockGenerativeResponse(json.dumps({
            "daily_summary": "今天過得非常充實，晚上吃美味的麥當勞犒賞自己。同時也提醒自己要交物理報告，繼續努力！",
            "actions": [
                {
                    "action": "add_expense",
                    "data": {"name": "麥當勞", "amount": 180, "category": "飲食"}
                },
                {
                    "action": "add_todo",
                    "data": {"name": "物理報告", "subject": "物理", "due_date": "2026-06-22", "type": "作業"}
                }
            ]
        }))
    class MockGenerativeResponse:
        def __init__(self, text):
            self.text = text
    return MockGenerativeResponse("{}")

# 替換 main.py 中的 API 函數為 Mock 函數
main.FIXED_SCHEDULE_DB_ID = "mock_fixed_schedule_db"
main.TODO_ACTIVITIES_DB_ID = "mock_todo_activities_db"
main.BOOK_TRACKER_DB_ID = "mock_book_tracker_db"
main.LEDGER_DB_ID = "mock_ledger_db"
main.WEEKLY_CALENDAR_DB_ID = "mock_weekly_calendar_db"
main.NOTION_TOKEN = "mock_token"

main.query_database_all = mock_query_database_all
main.update_page = mock_update_page
main.create_page = mock_create_page
main.delete_page = mock_delete_page
main.analyze_receipt = mock_analyze_receipt
main.analyze_todo_photo = mock_analyze_todo_photo
main.analyze_activity_brochure = mock_analyze_activity_brochure
main.send_telegram_message = mock_send_telegram_message
main.get_bot_user_id = lambda: "mock_bot_user_id"
main.ACTIVITIES_DB_ID = "mock_activities_db"
main.process_telegram_commands = lambda today_dt: print("[Telegram Mock] 執行指令處理 (跳過實體 API)...")

# Google Calendar Mocks
main.get_google_calendar_access_token = lambda: "mock_access_token"
main.make_gcal_request = mock_make_gcal_request
main.delete_google_calendar_event = mock_delete_google_calendar_event
main.safe_generate_content = mock_safe_generate_content
main.TEMP_INBOX_DB_ID = "mock_temp_inbox_db"

# ==================== 執行測試 ====================

def run_tests():
    # 設定測試日期為 2026-06-21 (星期日，台灣時間)
    # 明天為 2026-06-22 (星期一，開始上課)
    test_today = datetime(2026, 6, 21, tzinfo=pytz.timezone("Asia/Taipei"))
    
    print("=== 1. 開始測試【時段 A】下午 5:00 執行 (圖片視覺辨識 + 攜帶清單檢查) ===")
    main.run_mode_a(test_today)
    
    print("\n=== 2. 開始測試【時段 B】半夜 12:00 執行 (時間塊動態分配 + 課本位置警報) ===")
    # 再次模擬 B 模式。由於時段 A 已經更新了物品位置追蹤：
    # 數學：原「在家裡」，因明天是星期一且明天截止作業，A 判定要帶去學校，更新為「在學校」。
    # 英文：原「在學校」，明天要交報告，A 判定要帶去，忽略 (已在學校)。
    # 歷史：原「在學校」，因未來 3 天內有段考，A 判定今晚要帶回家複習，更新為「在家裡」。
    #
    # 在 B 模式下：
    # - 昨日(6/20)數學作業未完成，今日(6/21)數學任務預估時間會乘上 1.3 倍。
    # - 歷史段考在未來 4 天截止，觸發「提早準備機制」，今晚排入 45 分鐘歷史複習。
    # - 歷史複習需要的歷史課本目前在「在家裡」（由 A 帶回家了，安全）。
    # - 明天截止的英文 Writing 報告在未來 3 天內截止，觸發「衝刺機制」，排入 90 分鐘專注，並因 > 50 分鐘切分為番茄鐘。
    # - 英文報告需要的英文課本目前在「在學校」（雖然 A 判定要帶去，但在放學帶回的預估中沒有被帶回，因為英文是明天截止，而 A 放學帶回只看今日起 3 天內未完成的任務。英文報告由於是明天截止，A 的 future_study_subjects 應該包含英文，但因為英文目前在學校，放學應該帶回。如果放學沒有帶回，B 就會發出警報）。
    main.run_mode_b(test_today)

    print("\n=== 3. 開始測試【SHORTCUT 模式與隨手記總結】 ===")
    import sys
    # 設定環境變數 TEST_DATE 使得 SHORTCUT 寫入的日期與 B 模式相符
    os.environ["TEST_DATE"] = "2026-06-21"
    
    # 模擬 SHORTCUT 模式寫入兩筆碎片
    sys.argv = ["main.py", "--mode=SHORTCUT", "--text=今天晚餐吃麥當勞，花了180元"]
    main.main()
    
    # 模擬另一筆
    sys.argv = ["main.py", "--mode=SHORTCUT", "--text=明天要交物理報告"]
    main.main()
    
    # 執行 B 模式，進行一日總結與碎片提取，並自動寫入 Ledger/Todo
    sys.argv = ["main.py", "--mode=B"]
    main.run_mode_b(test_today)

if __name__ == "__main__":
    run_tests()
