import os
import sys
import json
import requests
import time

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

calendar_id = os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
url_create = f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"

events = [
    {"summary": "暑輔：國文", "start": "2026-07-13T10:20:00+08:00", "end": "2026-07-13T12:10:00+08:00"},
    {"summary": "暑輔：國文", "start": "2026-07-14T10:20:00+08:00", "end": "2026-07-14T12:10:00+08:00"},
    
    {"summary": "暑輔：國文", "start": "2026-07-20T10:20:00+08:00", "end": "2026-07-20T12:10:00+08:00"},
    {"summary": "暑輔：國文", "start": "2026-07-21T10:20:00+08:00", "end": "2026-07-21T12:10:00+08:00"},
    
    {"summary": "暑輔：國文", "start": "2026-07-27T10:20:00+08:00", "end": "2026-07-27T12:10:00+08:00"},
    {"summary": "暑輔：國文", "start": "2026-07-28T10:20:00+08:00", "end": "2026-07-28T12:10:00+08:00"},
    
    {"summary": "暑輔：國文", "start": "2026-07-15T08:10:00+08:00", "end": "2026-07-15T10:00:00+08:00"},
    {"summary": "暑輔：國文", "start": "2026-07-23T08:10:00+08:00", "end": "2026-07-23T10:00:00+08:00"},
    
    {"summary": "暑輔：數學", "start": "2026-08-03T10:20:00+08:00", "end": "2026-08-03T12:10:00+08:00"},
    {"summary": "暑輔：英文", "start": "2026-08-04T10:20:00+08:00", "end": "2026-08-04T12:10:00+08:00"}
]

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

for event in events:
    payload = {
        "summary": event["summary"],
        "description": "[暑輔課程安排]",
        "start": {"dateTime": event["start"], "timeZone": "Asia/Taipei"},
        "end": {"dateTime": event["end"], "timeZone": "Asia/Taipei"},
        "colorId": "9", # Blueberry
        "extendedProperties": {
            "private": {
                "source": "life-agent-summer"
            }
        }
    }
    
    try:
        res = requests.post(url_create, headers=headers, json=payload)
        if res.status_code == 200:
            print(f"成功新增行程: {event['summary']} ({event['start']} ~ {event['end']})")
        else:
            print(f"新增行程失敗 {event['summary']}: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"寫入行程異常 {event['summary']}: {e}")
