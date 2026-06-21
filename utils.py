import re
from datetime import datetime

def extract_date_time(text: str) -> dict:
    """Extract date and optional time from free‑form text.
    Returns a dict with keys 'date' (YYYY‑MM‑DD) and optional 'time' (HH:MM).
    If year is omitted, defaults to the current year.
    Invalid dates are ignored.
    """
    date_pattern = r"(?P<month>\d{1,2})[\/\-](?P<day>\d{1,2})(?:[\/\-](?P<year>\d{2,4}))?"
    time_pattern = r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
    result = {}
    date_match = re.search(date_pattern, text)
    if date_match:
        month = int(date_match.group('month'))
        day = int(date_match.group('day'))
        year = date_match.group('year')
        if not year:
            year = datetime.now().year
        else:
            year = int(year)
            if year < 100:  # two‑digit year handling
                year += 2000 if year < 70 else 1900
        try:
            date_obj = datetime(year, month, day)
            result['date'] = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            pass
    time_match = re.search(time_pattern, text)
    if time_match and 'date' in result:
        hour = int(time_match.group('hour'))
        minute = int(time_match.group('minute'))
        try:
            datetime(year, month, day, hour, minute)  # validation
            result['time'] = f"{hour:02d}:{minute:02d}"
        except ValueError:
            pass
    return result

def clean_title(text: str) -> str:
    """Strip leading symbols, hashtags and whitespace to obtain a clean title."""
    return re.sub(r"^[#@\s]+", "", text).strip()
