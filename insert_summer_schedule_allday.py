import os
import sys
import json
import requests
import time
from datetime import datetime, timedelta

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

def get_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                if cache.get("expires_at", 0) > time.time() + 60:
                    return cache.get("access_token")
        except:
            pass
    client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
    if not client_id or not client_secret or not refresh_token:
        print("缺少 OAuth 憑證，終止執行。")
        return None
    res = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token"
    })
    res.raise_for_status()
    d = res.json()
    access_token = d["access_token"]
    with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"access_token": access_token, "expires_at": time.time() + d.get("expires_in", 3600)}, f)
    return access_token

token = get_token()
if not token:
    sys.exit(1)

class_cal = os.environ.get("GOOGLE_CALENDAR_ID_CLASS")    or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
act_cal   = os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
gcal_h    = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

SOURCE_TAG = "life-agent-summer-v2"
TZ = "Asia/Taipei"

# -------------------------------------------------------------------
# 行程清單
# "start"/"end" 存在 => 有時段事件 (dateTime)
# 否則 => 全天事件 (date)
# "cal": "class" => 課表日曆, "act" => 活動日曆
# -------------------------------------------------------------------
EVENTS = [
    # ── 7/1 週三 ──
    {"date": "2026-07-01", "summary": "高醫職前訓",       "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-01", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},

    # ── 7/4 週六 ──
    {"date": "2026-07-04", "summary": "中山微創",          "start": "08:30", "end": "16:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-04", "summary": "PC數學（請假）",    "cal": "class", "color": "5"},

    # ── 7/5 週日 ──
    {"date": "2026-07-05", "summary": "中山微創",          "start": "08:30", "end": "13:00", "cal": "act",   "color": "10"},

    # ── 7/6 週一 ──
    {"date": "2026-07-06", "summary": "高醫志工",          "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-06", "summary": "高醫志工",          "start": "13:30", "end": "17:00", "cal": "act",   "color": "10"},

    # ── 7/7 週二 ──
    {"date": "2026-07-07", "summary": "高醫志工",          "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-07", "summary": "YTP面試",           "start": "13:30", "end": "17:00", "cal": "act",   "color": "11"},
    {"date": "2026-07-07", "summary": "PC化學（請假）",    "cal": "class", "color": "5"},

    # ── 7/8 週三 ──
    {"date": "2026-07-08", "summary": "高醫志工",          "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-08", "summary": "高醫志工",          "start": "13:30", "end": "17:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-08", "summary": "PC物理（請假）",    "cal": "class", "color": "5"},

    # ── 7/9 週四 ──
    {"date": "2026-07-09", "summary": "高醫志工",          "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-09", "summary": "高醫志工",          "start": "13:30", "end": "17:00", "cal": "act",   "color": "10"},

    # ── 7/10 週五 ──
    {"date": "2026-07-10", "summary": "高醫志工",          "start": "08:30", "end": "12:00", "cal": "act",   "color": "10"},
    {"date": "2026-07-10", "summary": "高醫志工",          "start": "13:30", "end": "17:00", "cal": "act",   "color": "10"},

    # ── 7/11 週六 ──
    {"date": "2026-07-11", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    # ── 第一週補習 (7/14~18) ──
    {"date": "2026-07-14", "summary": "PC化學補習",        "start": "13:30", "end": "16:45", "cal": "class", "color": "5"},
    {"date": "2026-07-14", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-07-15", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},
    {"date": "2026-07-18", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    # ── 第二週補習 (7/21~25) ──
    {"date": "2026-07-21", "summary": "PC化學補習",        "start": "13:30", "end": "16:45", "cal": "class", "color": "5"},
    {"date": "2026-07-21", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-07-22", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},
    {"date": "2026-07-25", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    # ── 第三週補習 (7/28~) ──
    {"date": "2026-07-28", "summary": "PC化學補習",        "start": "13:30", "end": "16:45", "cal": "class", "color": "5"},
    {"date": "2026-07-28", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-07-29", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},

    # ── 8月補習 ──
    {"date": "2026-08-01", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},
    {"date": "2026-08-04", "summary": "PC化學補習",        "start": "13:30", "end": "16:45", "cal": "class", "color": "5"},
    {"date": "2026-08-04", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-08-05", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},
    {"date": "2026-08-08", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    # ── 8/10-12 雄中參訪 (全天，無時間) ──
    {"date": "2026-08-10", "summary": "雄中參訪",          "cal": "act",   "color": "10"},
    {"date": "2026-08-11", "summary": "雄中參訪",          "cal": "act",   "color": "10"},
    {"date": "2026-08-11", "summary": "PC化學（停課）",    "cal": "class", "color": "5"},
    {"date": "2026-08-11", "summary": "MEC（請假）",       "cal": "class", "color": "5"},
    {"date": "2026-08-12", "summary": "雄中參訪",          "cal": "act",   "color": "10"},
    {"date": "2026-08-12", "summary": "PC物理（停課）",    "cal": "class", "color": "5"},

    # ── 8/13 以後 ──
    {"date": "2026-08-13", "summary": "返校打掃",          "cal": "act",   "color": "10"},
    {"date": "2026-08-14", "summary": "成大資工程式競賽？","cal": "act",   "color": "11"},
    {"date": "2026-08-15", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    {"date": "2026-08-18", "summary": "PC化學補習",        "start": "13:30", "end": "16:45", "cal": "class", "color": "5"},
    {"date": "2026-08-18", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-08-19", "summary": "PC物理補習",        "start": "13:30", "end": "16:40", "cal": "class", "color": "5"},
    {"date": "2026-08-22", "summary": "PC數學補習",        "start": "13:30", "end": "17:30", "cal": "class", "color": "5"},

    {"date": "2026-08-25", "summary": "PC化學（休息）",    "cal": "class", "color": "5"},
    {"date": "2026-08-26", "summary": "PC物理（休息）",    "cal": "class", "color": "5"},
    {"date": "2026-08-29", "summary": "MEC補習",           "start": "18:30", "end": "21:30", "cal": "class", "color": "5"},
    {"date": "2026-08-29", "summary": "PC數學（休息）",    "cal": "class", "color": "5"},

    {"date": "2026-08-31", "summary": "開學正式上課",      "cal": "act",   "color": "11"},
]

# -------------------------------------------------------------------
# 先清除舊匯入
# -------------------------------------------------------------------
for cal_id in list({class_cal, act_cal}):
    print(f"清除日曆 {cal_id} 中舊行程...")
    params = {"timeMin": "2026-07-01T00:00:00+08:00",
              "timeMax": "2026-09-01T00:00:00+08:00",
              "singleEvents": "true", "maxResults": 500}
    res = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
                       headers=gcal_h, params=params)
    if res.status_code == 200:
        deleted = 0
        for ev in res.json().get("items", []):
            if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
                dr = requests.delete(
                    f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events/{ev['id']}",
                    headers=gcal_h)
                if dr.status_code in [200, 204]:
                    deleted += 1
        print(f"  清除 {deleted} 筆。")

# -------------------------------------------------------------------
# 寫入行程
# -------------------------------------------------------------------
print(f"\n寫入共 {len(EVENTS)} 筆行程...")
success = 0
for ev in EVENTS:
    cal_id   = class_cal if ev["cal"] == "class" else act_cal
    date_str = ev["date"]
    has_time = "start" in ev

    if has_time:
        payload = {
            "summary":     ev["summary"],
            "description": "[Life-Agent 暑假課表匯入]",
            "start": {"dateTime": f"{date_str}T{ev['start']}:00+08:00", "timeZone": TZ},
            "end":   {"dateTime": f"{date_str}T{ev['end']}:00+08:00",   "timeZone": TZ},
            "colorId": ev["color"],
            "extendedProperties": {"private": {"source": SOURCE_TAG}}
        }
    else:
        end_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        payload = {
            "summary":     ev["summary"],
            "description": "[Life-Agent 暑假課表匯入]",
            "start": {"date": date_str},
            "end":   {"date": end_date},
            "colorId": ev["color"],
            "extendedProperties": {"private": {"source": SOURCE_TAG}}
        }

    try:
        r = requests.post(
            f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
            headers=gcal_h, json=payload)
        if r.status_code == 200:
            tag = f"{ev.get('start','全天')}-{ev.get('end','')}" if has_time else "全天"
            print(f"  OK [{ev['cal']:5}] {date_str} [{tag}] {ev['summary']}")
            success += 1
        else:
            print(f"  FAIL {date_str} {ev['summary']}: {r.status_code}")
    except Exception as e:
        print(f"  ERR {date_str} {ev['summary']}: {e}")

print(f"\n[匯入完成] 成功 {success}/{len(EVENTS)} 筆。")
