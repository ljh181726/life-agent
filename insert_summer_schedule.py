import os
import sys
import json
import requests
import time

# Load env variables from .env
env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

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
            
        print("已重新整理並快取 Google Calendar access token。")
        return access_token
    except Exception as e:
        print(f"更新 Google Calendar access token 失敗: {e}")
        return None

token = get_google_calendar_access_token()
if not token:
    print("無法取得授權，終止執行。")
    sys.exit(1)

calendar_id = os.environ.get("GOOGLE_CALENDAR_ID_CLASS") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"

# 1. 先清除此日期區間內所有舊的暑輔行程 (防止重複)
print("正在清除 2026-07-13 至 2026-08-07 區間內現存的暑輔日程...")
time_min = "2026-07-13T00:00:00+08:00"
time_max = "2026-08-07T23:59:59+08:00"
url_list = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
params = {
    "timeMin": time_min,
    "timeMax": time_max,
    "singleEvents": "true",
    "maxResults": 250
}
headers = {
    "Authorization": f"Bearer {token}"
}

try:
    res = requests.get(url_list, headers=headers, params=params)
    if res.status_code == 200:
        existing_events = res.json().get("items", [])
        deleted_count = 0
        for ev in existing_events:
            source = ev.get("extendedProperties", {}).get("private", {}).get("source")
            if source == "life-agent-summer":
                del_url = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{ev['id']}"
                del_res = requests.delete(del_url, headers=headers)
                if del_res.status_code in [200, 204]:
                    deleted_count += 1
        print(f"已成功清除 {deleted_count} 筆舊暑輔日程。")
except Exception as e:
    print(f"清除舊日程失敗: {e}")

# 2. 定義四週完整暑輔課程日程 (已包含國文調課及八月數學/英文調課)
events = [
    # Week 1 (7/13 - 7/17)
    {"date": "2026-07-13", "summary": "暑輔：化學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-13", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-14", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-14", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-15", "summary": "暑輔：國文", "start": "08:10", "end": "10:00"}, # 調課
    {"date": "2026-07-15", "summary": "暑輔：化學", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-16", "summary": "暑輔：英文", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-16", "summary": "暑輔：物理", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-17", "summary": "暑輔：物理", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-17", "summary": "暑輔：英文", "start": "10:20", "end": "12:10"},
    
    # Week 2 (7/20 - 7/24)
    {"date": "2026-07-20", "summary": "暑輔：化學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-20", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-21", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-21", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-22", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-22", "summary": "暑輔：化學", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-23", "summary": "暑輔：國文", "start": "08:10", "end": "10:00"}, # 調課
    {"date": "2026-07-23", "summary": "暑輔：物理", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-24", "summary": "暑輔：物理", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-24", "summary": "暑輔：英文", "start": "10:20", "end": "12:10"},
    
    # Week 3 (7/27 - 7/31)
    {"date": "2026-07-27", "summary": "暑輔：化學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-27", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-28", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-28", "summary": "暑輔：國文", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-29", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-29", "summary": "暑輔：化學", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-30", "summary": "暑輔：英文", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-30", "summary": "暑輔：物理", "start": "10:20", "end": "12:10"},
    {"date": "2026-07-31", "summary": "暑輔：物理", "start": "08:10", "end": "10:00"},
    {"date": "2026-07-31", "summary": "暑輔：英文", "start": "10:20", "end": "12:10"},
    
    # Week 4 (8/3 - 8/7)
    {"date": "2026-08-03", "summary": "暑輔：化學", "start": "08:10", "end": "10:00"},
    {"date": "2026-08-03", "summary": "暑輔：數學", "start": "10:20", "end": "12:10"}, # 調課
    {"date": "2026-08-04", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-08-04", "summary": "暑輔：英文", "start": "10:20", "end": "12:10"}, # 調課
    {"date": "2026-08-05", "summary": "暑輔：數學", "start": "08:10", "end": "10:00"},
    {"date": "2026-08-05", "summary": "暑輔：化學", "start": "10:20", "end": "12:10"},
    {"date": "2026-08-06", "summary": "暑輔：英文", "start": "08:10", "end": "10:00"},
    {"date": "2026-08-06", "summary": "暑輔：物理", "start": "10:20", "end": "12:10"},
    {"date": "2026-08-07", "summary": "暑輔：物理", "start": "08:10", "end": "10:00"},
    {"date": "2026-08-07", "summary": "暑輔：英文", "start": "10:20", "end": "12:10"}
]

print(f"開始寫入共 {len(events)} 筆暑期輔導日程...")
url_create = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
headers_create = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

success_count = 0
for event in events:
    start_iso = f"{event['date']}T{event['start']}:00+08:00"
    end_iso = f"{event['date']}T{event['end']}:00+08:00"
    
    payload = {
        "summary": event["summary"],
        "description": "[暑輔課程安排]",
        "start": {"dateTime": start_iso, "timeZone": "Asia/Taipei"},
        "end": {"dateTime": end_iso, "timeZone": "Asia/Taipei"},
        "colorId": "9", # Blueberry
        "extendedProperties": {
            "private": {
                "source": "life-agent-summer"
            }
        }
    }
    
    try:
        res = requests.post(url_create, headers=headers_create, json=payload)
        if res.status_code == 200:
            print(f"  成功寫入: {event['date']} {event['summary']} ({event['start']} - {event['end']})")
            success_count += 1
        else:
            print(f"  寫入失敗 {event['date']} {event['summary']}: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"  寫入異常 {event['date']} {event['summary']}: {e}")

print(f"暑輔課表匯入完成！成功 {success_count}/{len(events)} 筆。")
