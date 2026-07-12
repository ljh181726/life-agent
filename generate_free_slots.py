"""
generate_free_slots.py  v3
--------------------------
修正版：
- 課間空檔 = 該科最後N分鐘（在課堂內，非中堂，非留校）
- 中堂和其他短暫下課不算（掃地/移動）
- 晚上空檔延至22:00
- 週二/三下午13:10-13:30若下午有課直接封鎖
- 週末10:00-11:00算空檔，週六12:30-13:30封鎖，週日16:00-17:00運動
- 週末晚上19:20-22:00算空檔
- 不過濾短時間（全部顯示）
"""

import os, sys, json, time, requests
from datetime import datetime, timedelta
from collections import defaultdict

if sys.platform.startswith("win"):
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

env_path = ".env"
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip().strip('"').strip("'")

TOKEN_CACHE = ".gcal_token_cache.json"

def get_token():
    if os.path.exists(TOKEN_CACHE):
        try:
            with open(TOKEN_CACHE, "r") as f:
                c = json.load(f)
            if c.get("expires_at", 0) > time.time() + 60:
                return c["access_token"]
        except: pass
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN"),
        "grant_type":    "refresh_token"
    })
    r.raise_for_status()
    d = r.json()
    with open(TOKEN_CACHE, "w") as f:
        json.dump({"access_token": d["access_token"],
                   "expires_at": time.time() + d.get("expires_in", 3600)}, f)
    return d["access_token"]

token = get_token()
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

study_cal = os.environ.get("GOOGLE_CALENDAR_ID_STUDY")    or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
class_cal = os.environ.get("GOOGLE_CALENDAR_ID_CLASS")    or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
task_cal  = os.environ.get("GOOGLE_CALENDAR_ID_TASK")     or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
act_cal   = os.environ.get("GOOGLE_CALENDAR_ID_ACTIVITY") or os.environ.get("GOOGLE_CALENDAR_ID") or "primary"
all_cals  = list(dict.fromkeys([class_cal, task_cal, act_cal]))

SOURCE_TAG = "life-agent-free-slot"
PLAN_DAYS  = 14
TZ         = "Asia/Taipei"

# 課堂內可用的最後N分鐘（非中堂休息，非留校）
SUBJECT_BUFFER = {
    "化學": 20, "國文": 30, "英文": 0,
    "數學": 10, "物理": 20,
}
def get_buffer(subject):
    for k, v in SUBJECT_BUFFER.items():
        if k in subject:
            return v
    return 0

def t2m(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m

def m2t(m):
    return f"{m//60:02d}:{m%60:02d}"

# ── 讀取行程 ─────────────────────────────────────────────────────
today    = datetime.now().date()
time_min = datetime.combine(today, datetime.min.time()).isoformat() + "+08:00"
time_max = (datetime.combine(today, datetime.min.time()) + timedelta(days=PLAN_DAYS+1)).isoformat() + "+08:00"

print(f"讀取未來 {PLAN_DAYS} 天行程...")
raw_events = []
for cal_id in all_cals:
    r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{cal_id}/events",
                     headers=h, params={"timeMin": time_min, "timeMax": time_max,
                                        "singleEvents": "true", "maxResults": 500})
    if r.status_code == 200:
        raw_events.extend(r.json().get("items", []))

day_events = defaultdict(list)
for ev in raw_events:
    s = ev.get("start", {})
    e = ev.get("end", {})
    if s.get("dateTime"):
        d_str = s["dateTime"][:10]
        s_min = t2m(s["dateTime"][11:16])
        e_min = t2m(e["dateTime"][11:16])
        day_events[d_str].append({
            "summary": ev.get("summary", ""),
            "start": s_min, "end": e_min
        })
for d in day_events:
    day_events[d].sort(key=lambda x: x["start"])
print(f"讀取到 {sum(len(v) for v in day_events.values())} 筆行程。")

# ── 清除舊空檔 ───────────────────────────────────────────────────
print("清除舊的空檔標記...")
r = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{study_cal}/events",
                 headers=h, params={"timeMin": time_min, "timeMax": time_max,
                                    "singleEvents": "true", "maxResults": 500})
cleared = 0
if r.status_code == 200:
    for ev in r.json().get("items", []):
        if ev.get("extendedProperties", {}).get("private", {}).get("source") == SOURCE_TAG:
            dr = requests.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/{study_cal}/events/{ev['id']}",
                headers=h)
            if dr.status_code in [200, 204]:
                cleared += 1
print(f"已清除 {cleared} 筆。")

# ── 寫入空檔 ─────────────────────────────────────────────────────
SLEEP_MIN = t2m("22:30")
WAKE_MIN  = t2m("08:00")
weekday_zh = ["週一","週二","週三","週四","週五","週六","週日"]

total = 0

def write_slot(d_str, fs, fe, label="可用空檔"):
    global total
    dur = fe - fs
    if dur <= 0:
        return
    payload = {
        "summary":     f"{label} ({dur}分鐘)",
        "description": f"[Life-Agent 自動生成空檔]\n{d_str} {m2t(fs)}-{m2t(fe)} ({dur}分鐘)",
        "start": {"dateTime": f"{d_str}T{m2t(fs)}:00+08:00", "timeZone": TZ},
        "end":   {"dateTime": f"{d_str}T{m2t(fe)}:00+08:00", "timeZone": TZ},
        "colorId": "2",
        "extendedProperties": {"private": {"source": SOURCE_TAG}}
    }
    r = requests.post(f"https://www.googleapis.com/calendar/v3/calendars/{study_cal}/events",
                      headers=h, json=payload)
    if r.status_code == 200:
        wd = datetime.strptime(d_str, "%Y-%m-%d").weekday()
        print(f"  {d_str} {weekday_zh[wd]} {m2t(fs)}-{m2t(fe)} ({dur}分) — {label}")
        total += 1

print("\n計算可用空檔...")

for day_offset in range(PLAN_DAYS):
    d     = today + timedelta(days=day_offset)
    d_str = d.strftime("%Y-%m-%d")
    wd    = d.weekday()
    is_wkd = wd >= 5
    evs   = day_events.get(d_str, [])

    # 找出暑輔科目
    school_evs = sorted([ev for ev in evs if "暑輔" in ev["summary"]], key=lambda x: x["start"])
    is_school  = len(school_evs) > 0

    # 找出非暑輔的課/活動（補習等）
    other_evs = [ev for ev in evs if "暑輔" not in ev["summary"]]

    if is_school:
        # ── A. 課堂內自習空檔（該科最後N分鐘）──────────────────────
        for ev in school_evs:
            subject = ev["summary"].replace("暑輔：", "").replace("暑輔:", "")
            buf     = get_buffer(subject)
            if buf > 0:
                slot_s = ev["end"] - buf
                slot_e = ev["end"]
                write_slot(d_str, slot_s, slot_e, f"課內自習・{subject}")

        # ── B. 下午空檔（放學後回家，13:10起）──────────────────────
        afternoon_free_s = t2m("13:10")
        afternoon_free_e = t2m("16:30")  # 16:30-18:00 個人時間

        # 如果有下午補課：只看 12:00-18:00 之間的真實課/補習事件
        # 排除晚間 AI 排程的作業事件（start >= 17:00 以後視為晚上處理）
        pm_evs = sorted([ev for ev in other_evs
                         if t2m("12:00") <= ev["start"] < t2m("17:00")],
                        key=lambda x: x["start"])

        if pm_evs:
            first_pm_start = pm_evs[0]["start"]
            # 若下午第一課 ≤ 13:30（13:10-first_pm_start 過濾，買東西抵銷）
            if first_pm_start <= t2m("13:30"):
                # 補習之間的空隙（限 16:30 前）
                for i in range(len(pm_evs)-1):
                    gap_s = pm_evs[i]["end"]
                    gap_e = min(pm_evs[i+1]["start"], t2m("16:30"))
                    if gap_e > gap_s:
                        write_slot(d_str, gap_s, gap_e, "可用空檔")
                # 最後一個下午課到 16:30
                last_pm_end = pm_evs[-1]["end"]
                if last_pm_end < t2m("16:30"):
                    write_slot(d_str, last_pm_end, t2m("16:30"), "可用空檔")
            else:
                # 13:10 到第一個下午課前（最多到16:30）
                slot_end = min(first_pm_start, t2m("16:30"))
                if slot_end > afternoon_free_s:
                    write_slot(d_str, afternoon_free_s, slot_end, "可用空檔")
                # 補習之間空隙（限 16:30）
                for i in range(len(pm_evs)-1):
                    gap_s = pm_evs[i]["end"]
                    gap_e = min(pm_evs[i+1]["start"], t2m("16:30"))
                    if gap_e > gap_s:
                        write_slot(d_str, gap_s, gap_e, "可用空檔")
                last_pm_end = pm_evs[-1]["end"]
                if last_pm_end < t2m("16:30"):
                    write_slot(d_str, last_pm_end, t2m("16:30"), "可用空檔")
        else:
            # 沒有下午補課：13:10-16:30 整塊空閒
            write_slot(d_str, afternoon_free_s, afternoon_free_e, "可用空檔")

        # ── C. 16:30-18:00 個人時間（不算空檔）──────────────────────
        # ── D. 晚餐 18:00-18:30 ─────────────────────────────────────
        # ── E. 洗澡刷牙整理 18:30-19:20 ─────────────────────────────
        # ── F. 晚上空檔 19:20-22:00 ──────────────────────────────────
        # 排除這段中有晚間補課（如 MEC 18:30-21:30）
        evening_s = t2m("19:20")
        evening_e = t2m("22:00")
        # 晚間補課（如 MEC 18:30-21:30）——只處理真實課/補習事件，排除 AI 排程作業
        eve_evs = sorted([ev for ev in other_evs
                          if ev["start"] >= t2m("18:00")
                          and ev["end"] <= t2m("23:00")
                          and any(k in ev["summary"] for k in ["補習","MEC","PC","補課","補講","課"])],
                         key=lambda x: x["start"])
        if eve_evs:
            # 晚間補課前後找空隙
            cur = evening_s
            for ev in eve_evs:
                if ev["start"] > cur:
                    write_slot(d_str, cur, ev["start"], "可用空檔")
                cur = max(cur, ev["end"])
            if cur < evening_e:
                write_slot(d_str, cur, evening_e, "可用空檔")
        else:
            write_slot(d_str, evening_s, evening_e, "可用空檔")

        # ── G. 22:00-22:30 睡前準備（不算空檔）─────────────────────

    else:
        # ══════ 假日 / 週末 ══════════════════════════════════════════
        # 早餐 08:00-08:30
        # 空檔 08:30-10:00 (週六有 PC數學 需要12:30出發，週日一樣)
        write_slot(d_str, t2m("08:30"), t2m("10:00"), "可用空檔")

        # 10:00-11:00 是空檔（不是運動）
        write_slot(d_str, t2m("10:00"), t2m("11:00"), "可用空檔")

        # 午餐 11:00-11:30（假日早一點吃）
        # 11:30 - 下午活動前的空檔

        # 找週末的午後事件（補習）
        pm_evs_wkd = sorted([ev for ev in evs if ev["start"] >= t2m("11:30")],
                             key=lambda x: x["start"])

        if wd == 5:  # 週六
            # 12:30-13:30 封鎖（玩一下+通勤PC數學）
            # 午餐 11:00-11:30，11:30-12:30 空檔
            write_slot(d_str, t2m("11:00"), t2m("12:30"), "可用空檔")
            # 12:30-13:30 不算（通勤/準備 PC數學）
            # 找 PC數學或其他下午課
            pc_sat = [ev for ev in evs if ev["start"] >= t2m("13:30")]
            if pc_sat:
                pc_sat.sort(key=lambda x: x["start"])
                # PC數學後到晚餐前
                after_pm = pc_sat[-1]["end"]
                if after_pm < t2m("18:00"):
                    write_slot(d_str, after_pm, t2m("18:00"), "可用空檔")
            else:
                write_slot(d_str, t2m("13:30"), t2m("18:00"), "可用空檔")

        elif wd == 6:  # 週日
            # 午餐 11:00-11:30，11:30-16:00 空檔
            write_slot(d_str, t2m("11:00"), t2m("16:00"), "可用空檔")
            # 運動 16:00-17:00
            # 17:00-18:00 空檔
            write_slot(d_str, t2m("17:00"), t2m("18:00"), "可用空檔")

        # 晚餐 18:00-18:30
        # 洗澡刷牙整理 18:30-19:20
        # 週末晚上空檔 19:20-22:00
        write_slot(d_str, t2m("19:20"), t2m("22:00"), "可用空檔")
        # 22:00-22:30 睡前準備（不算）

print(f"\n[完成] 共寫入 {total} 個空檔至自習日曆！")
