import os
import json
import requests
import urllib3
from datetime import datetime
import pytz

# 停用 SSL 警告（若有需要 verify=False）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TAIPEI_TZ = pytz.timezone('Asia/Taipei')
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holiday_cache.json")

# 記憶體快取
_holiday_cache = {}

def refresh_cache_sync():
    """同步重新整理假期快取，自 GitHub CDN 抓取台灣行事曆並存檔。"""
    global _holiday_cache
    now_year = datetime.now(TAIPEI_TZ).year
    years_to_fetch = [now_year, now_year + 1]
    
    new_cache = {}
    success = False
    
    for year in years_to_fetch:
        url = f"https://cdn.jsdelivr.net/gh/ruyut/TaiwanCalendar/data/{year}.json"
        try:
            # 使用 verify=False 防禦本地系統缺憑證問題，設定 timeout 避免卡死
            res = requests.get(url, verify=False, timeout=5)
            if res.status_code == 200:
                data = res.json()
                for entry in data:
                    # entry 格式為 {"date": "YYYYMMDD", "isHoliday": true/false, ...}
                    date_str = entry.get("date")
                    is_holiday = entry.get("isHoliday", False)
                    if date_str:
                        new_cache[date_str] = is_holiday
                success = True
        except Exception as e:
            print(f"無法從 {url} 獲取假期資料: {e}")

    if success:
        _holiday_cache.update(new_cache)
        # 寫入本地快取檔案
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(_holiday_cache, f, ensure_ascii=False, indent=2)
            print("國定假日快取已成功從網路更新。")
        except Exception as e:
            print(f"寫入本地快取檔案失敗: {e}")
    else:
        # 網路失敗時，嘗試讀取本地快取檔案
        load_local_cache()

def load_local_cache():
    """載入本地快取檔案"""
    global _holiday_cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _holiday_cache = json.load(f)
            print("已載入本地國定假日快取。")
        except Exception as e:
            print(f"載入本地快取檔案失敗: {e}")
            _holiday_cache = {}
    else:
        print("本地無國定假日快取檔案。")
        _holiday_cache = {}

def is_holiday(date_obj) -> bool:
    """判斷指定日期是否為國定假日或週末。
    若快取中找不到，則預設週末（週六、週日）為假日。
    """
    # 格式化為 YYYYMMDD
    date_str = date_obj.strftime("%Y%m%d")
    if date_str in _holiday_cache:
        return _holiday_cache[date_str]
    
    # 預設週末判定 (1-7, 6 是週六, 7 是週日)
    return date_obj.isoweekday() in [6, 7]

# 啟動時自動嘗試讀取本地快取
load_local_cache()
