import re
import pytz
import dateparser
from datetime import datetime, timedelta
from dateutil import tz as dateutil_tz
from email.utils import parsedate_tz
from logger_config import logger   



def normalize_time_text(raw: str) -> str:
    """
Normalize common human expressions to improve parsability.
    e.g. '5PM, NEXT Tuesday' -> 'next tuesday 5 pm'
    """
    if not raw:
        return raw
    text = raw.strip()

    # Strip redundant punctuation and normalize whitespaces.
    text = re.sub(r"[,\u3001]+", " ", text)      # Remove commas and ideographic commas.
    text = re.sub(r"\s+", " ", text)

    # Normalize text to lowercase for better compatibility with dateparser.
    text = text.lower()

    # Common notation conversion:tues. -> tuesday, sth -> ...
    repl = {
        "mon.": "monday", "tues.": "tuesday", "wed.": "wednesday",
        "thur.": "thursday", "fri.": "friday", "sat.": "saturday", "sun.": "sunday",
        "next tues": "next tuesday",
        "pm.": "pm", "am.": "am",
        "@": " at ",                          # User-friendly 'next tue @ 5pm'
    }
    for k, v in repl.items():
        text = text.replace(k, v)

    
    # If only a time is provided without a date, proceed to the next handling step. dateparser + 'PREFER_DATES_FROM=future'
    return text

def parse_human_time(human_text: str, base_dt: datetime | None = None) -> datetime | None:
    """
    Attempt multi-round parsing of natural language time expressions.
        1) dateparser first try
        2) Retry after secondary normalization.
        3) Map a standalone time expression to its closest future occurrence relative to now (e.g., if 5 PM today has passed, schedule for 5 PM tomorrow).
        Returns: a timezone-aware datetime object or None.
    """
    if not human_text:
        return None

    if base_dt is None:
        # Use the current time in the local timezone as the relative reference.
        tz = pytz.timezone(DEFAULT_TZ)
        base_dt = datetime.now(tz)

    text1 = normalize_time_text(human_text)

    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": DEFAULT_TZ,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "RELATIVE_BASE": base_dt,
         }

    # First parse
    dt = dateparser.parse(text1, settings=settings, languages=["en", "zh"])
    if dt:
        return dt

    # Second pass: apply normalization (e.g., forcibly insert "at").
    text2 = re.sub(r"\b(\d{1,2})(am|pm)\b", r"\1 \2", text1)  # '5pm' -> '5 pm'
    text2 = re.sub(r"\b(\d{1,2}):(\d{2})(am|pm)\b", r"\1:\2 \3", text2)
    dt = dateparser.parse(text2, settings=settings, languages=["en", "zh"])
    if dt:
        return dt

    # Third pass:If the input is a time-only string (e.g., "5pm" or "17:00") with no date, map it to the nearest future occurrence.
    m_time_only = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text1)
    if m_time_only:
        hour = int(m_time_only.group(1))
        minute = int(m_time_only.group(2) or 0)
        ampm = (m_time_only.group(3) or "").lower()

        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0

        candidate = base_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= base_dt:
            candidate += timedelta(days=1)
        return candidate

    return None

def get_sender_timezone(headers: dict,default_tz):
    """
    Extract the sender's timezone from the email headers. If parsing fails, fall back to the default timezone.
    """
    try:
        date_header = headers.get("Date")
        if not date_header:
            logger.warning("No Date header found; using default timezone.")
            return default_tz

        parsed_date = parsedate_tz(date_header)
        if not parsed_date:
            logger.warning(f"Date Parsing failed:{date_header}")
            return default_tz

        tz_offset = parsed_date[9]
        if tz_offset is None:
            return default_tz

        hours_offset = tz_offset / 3600
        # Important Note: The sign convention for Etc/GMT timezones is the opposite of the common standard.
        sign = "-" if hours_offset > 0 else "+" if hours_offset < 0 else ""
        abs_offset = abs(int(hours_offset))
        tz_name = f"Etc/GMT{sign}{abs_offset}" if abs_offset != 0 else "Etc/GMT"
        return tz_name

    except Exception as e:
        logger.error(f"Failed to parse the time zone:{e}")
        return default_tz
