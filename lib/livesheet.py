"""Read new Job Cards from the live Tracksheet. Never writes to that site."""

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LIVE_SITE = "https://track.aryabhangymotors.com"
LIVE_DATABASE = "https://tracksheet.aryabhangymotors.com"
TABLE_ID = 561
DATE_FIELD = 5256
MAX_PAGES = 10
MAX_DAYS = 31


class LiveError(RuntimeError):
    pass


def read_dates(latest):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    start = today if latest is None or latest > today else latest
    if (today - start).days > MAX_DAYS - 1:
        start = today - timedelta(days=MAX_DAYS - 1)
    days = []
    current = start
    while current <= today:
        days.append(current)
        current += timedelta(days=1)
    return days


def cards_on(days):
    if not days:
        return []
    token = _token()
    found = []
    for day in days:
        query = (
            f"/api/database/rows/table/{TABLE_ID}/"
            f"?user_field_names=true&size=200&page=1"
            f"&filter__field_{DATE_FIELD}__date_equal={day.isoformat()}"
        )
        for row in _pages(query, token):
            card = _card(row)
            if card is not None:
                found.append(card)
    return found


def _card(row):
    source = row.get("id")
    jc_number = _jc(row.get("JC Number"))
    on_date = _date(row.get("Date"))
    branch = _text(row.get("Branch"), 80)
    if not isinstance(source, int) or not jc_number or not on_date or not branch:
        return None
    return {
        "source_row_id": source,
        "jc_number": jc_number,
        "on_date": on_date,
        "registration": _text(row.get("Registration"), 40),
        "customer_name": _text(row.get("Customer Name"), 160),
        "model": _text(row.get("Model"), 80),
        "branch": branch,
        "service_type": _text(row.get("Service Type"), 80),
        "booking_source": _text(row.get("Booking Source"), 80),
        "adviser": _text(row.get("Adviser"), 80),
        "technician": _text(row.get("Technician"), 80),
        "final_inspection": _text(row.get("Final Inspection"), 80),
        "repeat_complaint": row.get("Repeat Complaint") is True,
    }


def _text(value, limit):
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()[:limit]


def _jc(value):
    text = _text(value, 40)
    if not text or re.search(r"[A-Za-z]", text):
        return ""
    if re.fullmatch(r"\d{1,6}", text):
        return text.zfill(6)
    return ""


def _date(value):
    text = _text(value, 40)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text[:10] if len(text) >= 10 else ""):
        return text[:10]
    return ""


def _token():
    request = urllib.request.Request(
        LIVE_SITE + "/config.js", headers={"User-Agent": "AryabhangyDemo"}
    )
    try:
        text = urllib.request.urlopen(request, timeout=8).read().decode("utf-8", "replace")
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise LiveError("The live Tracksheet could not be read.") from error
    match = re.search(r'TRACKSHEET_TOKEN\s*=\s*"([^"]+)"', text)
    if not match or match.group(1) in {"", "PASTE_DB_TOKEN_HERE", "MISSING_CONFIG_JS"}:
        raise LiveError("The live Tracksheet could not be read.")
    return match.group(1)


def _pages(query, token):
    rows = []
    for _page in range(MAX_PAGES):
        data = _get(query, token)
        rows.extend(data.get("results") or [])
        nxt = data.get("next") or ""
        if not nxt:
            return rows
        if not nxt.startswith(LIVE_DATABASE + "/"):
            raise LiveError("The live Tracksheet could not be read.")
        query = nxt[len(LIVE_DATABASE):]
    raise LiveError("The live Tracksheet returned more job cards than this read allows.")


def _get(path, token):
    if not path.startswith("/api/database/rows/"):
        raise LiveError("The live Tracksheet could not be read.")
    request = urllib.request.Request(
        LIVE_DATABASE + path,
        headers={"Authorization": "Token " + token, "User-Agent": "AryabhangyDemo"},
    )
    try:
        raw = urllib.request.urlopen(request, timeout=8).read().decode("utf-8", "replace")
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise LiveError("The live Tracksheet could not be read.") from error
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LiveError("The live Tracksheet could not be read.") from error
    if not isinstance(body, dict):
        raise LiveError("The live Tracksheet could not be read.")
    return body
