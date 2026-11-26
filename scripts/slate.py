"""Taipei evening slate: 16:00 through 08:00 the following morning."""
import datetime as dt
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Taipei")


def slate_window(now=None):
    """Before 08:00, keep last evening's slate; otherwise target today's."""
    local = (now or dt.datetime.now(ZONE)).astimezone(ZONE)
    day = (local - dt.timedelta(hours=8)).date()
    start = dt.datetime.combine(day, dt.time(16), ZONE)
    return start, start + dt.timedelta(hours=16)
