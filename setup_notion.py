import os
import sys
import requests

def extract_page_id(url_or_id):
    url_or_id = url_or_id.strip()
    if "/" in url_or_id:
        part = url_or_id.split("/")[-1]
        part = part.split("?")[0]
        part = part.split("-")[-1]
        if len(part) == 32:
            return part
    return url_or_id.replace("-", "")

def main():
    env_path = ".env"
    if not os.path.exists(env_path):
        print("未檢測到 .env 檔案，請先確認目錄結構。")
        sys.exit(1)

    # 讀取 .env 中的變數
    config = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()

    token = config.get("NOTION_TOKEN")
    parent_url_or_id = config.get("NOTION_PARENT_PAGE_ID")

    if not token:
        # 嘗試從環境變數讀取
        token = os.environ.get("NOTION_TOKEN")
    if not parent_url_or_id:
        parent_url_or_id = os.environ.get("NOTION_PARENT_PAGE_ID")

    if not token or not parent_url_or_id:
        print("請在 .env 檔案中填寫 NOTION_TOKEN 與 NOTION_PARENT_PAGE_ID (Notion 頁面的 URL 或 ID)")
        sys.exit(1)

    parent_page_id = extract_page_id(parent_url_or_id)
    print(f"解析出 Parent Page ID: {parent_page_id}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }

    # 定義五個資料庫的 Schema
    databases_schema = {
        "NOTION_FIXED_SCHEDULE_DB_ID": {
            "title": "固定課表資料庫",
            "properties": {
                "科目名稱": {"title": {}},
                "星期": {"number": {"format": "number"}},
                "時間段": {"rich_text": {}},
                "作息類型": {"select": {"options": [{"name": "學期中"}, {"name": "暑假"}]}},
                "是否可寫作業": {"checkbox": {}}
            }
        },
        "NOTION_TODO_ACTIVITIES_DB_ID": {
            "title": "待辦事項資料庫",
            "properties": {
                "名稱": {"title": {}},
                "類型": {"select": {"options": [{"name": "作業"}, {"name": "小考"}, {"name": "段考"}, {"name": "回條"}, {"name": "報名表"}]}},
                "開始日期": {"date": {}},
                "截止或考試日期": {"date": {}},
                "相關科目": {"rich_text": {}},
                "總頁數/題數": {"number": {"format": "number"}},
                "已完成頁數/題數": {"number": {"format": "number"}},
                "實際耗時": {"number": {"format": "number"}},
                "照片上傳": {"files": {}}
            }
        },
        "NOTION_ACTIVITIES_DB_ID": {
            "title": "活動資料庫",
            "properties": {
                "活動名稱": {"title": {}},
                "日期": {"date": {}},
                "類型": {"select": {"options": [{"name": "講座"}, {"name": "營隊"}, {"name": "比賽"}, {"name": "志工"}, {"name": "休閒"}, {"name": "其他"}]}},
                "簡章上傳": {"files": {}},
                "備註": {"rich_text": {}}
            }
        },
        "NOTION_BOOK_TRACKER_DB_ID": {
            "title": "科目與教科書位置追蹤資料庫",
            "properties": {
                "科目/物品名稱": {"title": {}},
                "目前位置": {"select": {"options": [{"name": "在家裡"}, {"name": "在學校"}]}}
            }
        },
        "NOTION_LEDGER_DB_ID": {
            "title": "記帳本資料庫",
            "properties": {
                "項目名稱": {"title": {}},
                "日期": {"date": {}},
                "金額": {"number": {"format": "number"}},
                "分類": {"select": {"options": [{"name": "飲食"}, {"name": "交通"}, {"name": "娛樂"}, {"name": "學習"}]}},
                "收據照片": {"files": {}}
            }
        },
        "NOTION_WEEKLY_CALENDAR_DB_ID": {
            "title": "每週行事曆資料庫",
            "properties": {
                "行程名稱": {"title": {}},
                "日期": {"date": {}},
                "開始時間": {"rich_text": {}},
                "結束時間": {"rich_text": {}},
                "行程類型": {"select": {"options": [{"name": "上課"}, {"name": "自習寫功課"}, {"name": "考試準備"}, {"name": "段考複習"}, {"name": "休息"}]}},
                "今日攜帶清單": {"rich_text": {}},
                "備註": {"rich_text": {}}
            }
        }
    }

    created_ids = {}

    # 批次建立資料庫
    url = "https://api.notion.com/v1/databases"
    for env_key, schema in databases_schema.items():
        if config.get(env_key):
            print(f"資料庫 {schema['title']} 已存在於 .env 中 (ID: {config[env_key]})，跳過建立。")
            created_ids[env_key] = config[env_key]
            continue

        payload = {
            "parent": {
                "type": "page_id",
                "page_id": parent_page_id
            },
            "title": [
                {
                    "type": "text",
                    "text": {
                        "content": schema["title"]
                    }
                }
            ],
            "properties": schema["properties"]
        }
        print(f"正在建立 {schema['title']}...")
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            db_id = res.json().get("id").replace("-", "")
            created_ids[env_key] = db_id
            print(f"建立成功！資料庫 ID: {db_id}")
        else:
            print(f"建立 {schema['title']} 失敗。狀態碼: {res.status_code}，錯誤訊息: {res.text}")
            sys.exit(1)

    # 將生成的 ID 回填至 .env
    lines = []
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        matched = False
        for env_key, db_id in created_ids.items():
            if line.startswith(f"{env_key}="):
                new_lines.append(f"{env_key}={db_id}\n")
                matched = True
                break
        if not matched:
            new_lines.append(line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print("\n資料庫全部建立完成！對應 ID 已自動回填至 .env 檔案中。")

if __name__ == "__main__":
    main()
