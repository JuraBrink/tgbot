
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

DATE_RE = re.compile(r"""
^\s*
(?:(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{2}|\d{4})\s+)?
(?P<start>\d{1,2}(?::\d{1,2})?)
\s*-\s*
(?P<end>\d{1,2}(?::\d{1,2})?)
(?:\s*-\s*(?P<brk>(?:\d{1,2})(?::\d{1,2})?))?
\s*$
""", re.VERBOSE)

DAYOFF_RE = re.compile(r"""
^\s*
(?:(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{2}|\d{4})\s+)?
0\s*$
""", re.VERBOSE)

@dataclass
class ParsedWork:
    date: date
    start_min: int
    end_min: int
    break_min: int
    from_template_candidate: bool

@dataclass
class ParsedDayOff:
    date: date

def _to_minutes(hhmm: str) -> int:
    if ':' in hhmm:
        h, m = hhmm.split(':', 1)
        return int(h) * 60 + int(m)
    else:
        return int(hhmm) * 60

def _norm_year(y: int) -> int:
    if y < 100:
        return 2000 + y
    return y

def parse_input(text: str, user_tz: str, now_utc: Optional[datetime] = None):
    tz = ZoneInfo(user_tz or "UTC")
    now = (now_utc or datetime.now(timezone.utc)).astimezone(tz)
    m = DAYOFF_RE.match(text)
    if m:
        if m.group('d'):
            y = _norm_year(int(m.group('y')))
            d = int(m.group('d')); mm = int(m.group('m'))
            dt = datetime(y, mm, d, tzinfo=tz).date()
        else:
            dt = now.date()
        return ParsedDayOff(date=dt)

    m = DATE_RE.match(text)
    if not m:
        return None
    has_date = m.group('d') is not None

    if has_date:
        y = _norm_year(int(m.group('y')))
        d = int(m.group('d')); mm = int(m.group('m'))
        dt = datetime(y, mm, d, tzinfo=tz).date()
    else:
        dt = now.date()

    start = _to_minutes(m.group('start'))
    end = _to_minutes(m.group('end'))
    brk_raw = m.group('brk')
    brk = _to_minutes(brk_raw) if brk_raw is not None else 0

    if not (0 <= start < 24*60 and 0 < end <= 24*60):
        return None
    if not (start < end):
        return None
    work_span = end - start
    if brk < 0 or brk > work_span:
        return None

    return ParsedWork(
        date=dt,
        start_min=start,
        end_min=end,
        break_min=brk,
        from_template_candidate=(not has_date)
    )

def fmt_hhmm(total_min: int) -> str:
    h = total_min // 60
    m = total_min % 60
    return f"{h:02d}:{m:02d}"
