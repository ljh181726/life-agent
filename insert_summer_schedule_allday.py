import os
import sys
import json
import requests
import time

# Fix Windows console encoding
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except:
        pass

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
        cache_data = {"access_token": access_token, "expires_at": time.time() + expires_in}
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
        return access_token
    except Exception as e:
        print(f"更新 Google Calendar access token 失敗: {e}")
        return None

token = get_google_calendar_access_token()
if not token:
    print("無法取得授權，終止執行。")
    sys.exit(1)

class_cal  = os.environ.get("GOOGLE_CALENDAR_ID_CLASS")    or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
act_cal    = os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"

gcal_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

SOURCE_TAG = "life-agent-summer-v2"

# -------------------------------------------------------------------
# 所有行程清單（全天事件）
# 格式: {"date": "YYYY-MM-DD", "summary": "...", "cal": class_cal|act_cal, "color": "N"}
# colorId: 9=Blueberry(課表), 10=Basil(活動/志工), 11=Tomato(重要活動), 5=Banana(補習)
# -------------------------------------------------------------------
EVENTS = [
    # ---- 7月初特殊活動 ----
    {"date": "2026-07-01", "summary": "高醫職前訓",    "cal": "act",   "color": "10"},
    {"date": "2026-07-01", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-04", "summary": "中山微創",      "cal": "act",   "color": "10"},
    {"date": "2026-07-04", "summary": "PC數學（請假）","cal": "class", "color": "5"},
    {"date": "2026-07-05", "summary": "中山微創",      "cal": "act",   "color": "10"},
    {"date": "2026-07-06", "summary": "高醫志工",      "cal": "act",   "color": "10"},
    {"date": "2026-07-07", "summary": "高醫志工",      "cal": "act",   "color": "10"},
    {"date": "2026-07-07", "summary": "YTP面試",       "cal": "act",   "color": "11"},
    {"date": "2026-07-07", "summary": "PC化學（請假）","cal": "class", "color": "5"},
    {"date": "2026-07-08", "summary": "高醫志工",      "cal": "act",   "color": "10"},
    {"date": "2026-07-08", "summary": "PC物理（請假）","cal": "class", "color": "5"},
    {"date": "2026-07-09", "summary": "高醫志工",      "cal": "act",   "color": "10"},
    {"date": "2026-07-10", "summary": "高醫志工",      "cal": "act",   "color": "10"},
    {"date": "2026-07-11", "summary": "PC數學補習",    "cal": "class", "color": "5"},

    # ---- 7/13 暑輔第一週 ----
    {"date": "2026-07-13", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-14", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-14", "summary": "PC化學補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-14", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-07-15", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-15", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-16", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-17", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-18", "summary": "PC數學補習",    "cal": "class", "color": "5"},

    # ---- 7/20 暑輔第二週 ----
    {"date": "2026-07-20", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-21", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-21", "summary": "PC化學補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-21", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-07-22", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-22", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-23", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-24", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-25", "summary": "PC數學補習",    "cal": "class", "color": "5"},

    # ---- 7/27 暑輔第三週 ----
    {"date": "2026-07-27", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-28", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-28", "summary": "PC化學補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-28", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-07-29", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-29", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-07-30", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-07-31", "summary": "暑輔",          "cal": "class", "color": "9"},

    # ---- 8月 ----
    {"date": "2026-08-01", "summary": "PC數學補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-03", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-08-04", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-08-04", "summary": "PC化學補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-04", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-08-05", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-08-05", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-06", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-08-07", "summary": "暑輔",          "cal": "class", "color": "9"},
    {"date": "2026-08-08", "summary": "PC數學補習",    "cal": "class", "color": "5"},

    # ---- 8/10-12 雄中參訪 ----
    {"date": "2026-08-10", "summary": "雄中參訪",      "cal": "act",   "color": "10"},
    {"date": "2026-08-11", "summary": "雄中參訪",      "cal": "act",   "color": "10"},
    {"date": "2026-08-11", "summary": "PC化學（停課）","cal": "class", "color": "5"},
    {"date": "2026-08-11", "summary": "MEC（請假）",   "cal": "class", "color": "5"},
    {"date": "2026-08-12", "summary": "雄中參訪",      "cal": "act",   "color": "10"},
    {"date": "2026-08-12", "summary": "PC物理（停課）","cal": "class", "color": "5"},
    {"date": "2026-08-13", "summary": "返校打掃",      "cal": "act",   "color": "10"},
    {"date": "2026-08-14", "summary": "成大資工程式競賽？","cal": "act","color": "11"},
    {"date": "2026-08-15", "summary": "PC數學補習",    "cal": "class", "color": "5"},

    # ---- 8/16 之後 ----
    {"date": "2026-08-18", "summary": "PC化學補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-18", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-08-19", "summary": "PC物理補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-22", "summary": "PC數學補習",    "cal": "class", "color": "5"},
    {"date": "2026-08-25", "summary": "PC化學（休息）","cal": "class", "color": "5"},
    {"date": "2026-08-26", "summary": "PC物理（休息）","cal": "class", "color": "5"},
    {"date": "2026-08-29", "summary": "MEC補習",       "cal": "class", "color": "5"},
    {"date": "2026-08-29", "summary": "PC數學（休息）","cal": "class", "color": "5"},
    {"date": "2026-08-31", "summary": "開學正式上課",  "cal": "act",   "color": "11"},
]

# -------------------------------------------------------------------
# 清除舊匯入
# -------------------------------------------------------------------
calendars_to_clear = list({class_cal, act_cal})
for cal_id in calendars_to_clear:
    print(f"正在清除日曆 {cal_id} 中舊暑假行程...")
    params = {
        "timeMin": "2026-07-01T00:00:00+08:00",
        "timeMax": "2026-09-01T00:00:00+08:00",
        "singleEvents": "true",
        "maxResults": 500
    }
    try:
        res = requests.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
            headers=gcal_headers, params=params
        )
        if res.status_code == 200:
            items = res.json().get("items", [])
            deleted = 0
            for ev in items:
                src = ev.get("extendedProperties", {}).get("private", {}).get("source")
                if src == SOURCE_TAG:
                    del_res = requests.delete(
                        f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events/{ev['id']}",
                        headers=gcal_headers
                    )
                    if del_res.status_code in [200, 204]:
                        deleted += 1
            print(f"  清除 {deleted} 筆舊行程。")
    except Exception as e:
        print(f"  清除失敗: {e}")

# -------------------------------------------------------------------
# 寫入全天行程
# -------------------------------------------------------------------
from datetime import datetime, timedelta

print(f"\n開始寫入共 {len(EVENTS)} 筆全天行程...")
success = 0
for ev in EVENTS:
    cal_id = class_cal if ev["cal"] == "class" else act_cal
    date_str = ev["date"]
    # end date = date + 1 for all-day events
    end_str = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    payload = {
        "summary": ev["summary"],
        "description": "[Life-Agent 暑假課表匯入]",
        "start": {"date": date_str},
        "end":   {"date": end_str},
        "colorId": ev["color"],
        "extendedProperties": {"private": {"source": SOURCE_TAG}}
    }
    try:
        res = requests.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
            headers=gcal_headers, json=payload
        )
        if res.status_code == 200:
            print(f"  OK [{ev['cal']:5}] {date_str} {ev['summary']}")
            success += 1
        else:
            print(f"  FAIL {date_str} {ev['summary']}: {res.status_code}")
    except Exception as e:
        print(f"  ERR {date_str} {ev['summary']}: {e}")

print(f"\n[匯入完成] 成功 {success}/{len(EVENTS)} 筆。")
