"""Pure billing rules: units x price per unit, as written in the rental contract."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Bangkok")
PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


@dataclass
class Reading:
    value: str
    rollover: bool = False


def units_used(prev: str, curr: str, rollover: bool):
    """Units between two readings. None = current is lower and nobody confirmed a rollover."""
    diff = int(curr) - int(prev)
    if diff >= 0:
        return diff
    if rollover:
        return diff + 10 ** max(len(prev), len(curr))
    return None


def money(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def bill_line(prev, curr, price):
    """One meter for one month. status: ok | missing | first | review | no_rate"""
    if curr is None:
        return {"status": "missing", "units": None, "amount": None}
    if prev is None:
        return {"status": "first", "units": None, "amount": None}
    units = units_used(prev.value, curr.value, curr.rollover)
    if units is None:
        return {"status": "review", "units": None, "amount": None}
    if price is None:
        return {"status": "no_rate", "units": units, "amount": None}
    return {"status": "ok", "units": units, "amount": money(Decimal(units) * Decimal(price))}


def period_of(ts: datetime) -> str:
    """Billing month in Thai local time, e.g. '2026-09'."""
    local = ts.astimezone(LOCAL_TZ)
    return f"{local.year:04d}-{local.month:02d}"


def period_bounds(period: str):
    """UTC [start, end) of a billing month."""
    m = PERIOD_RE.match(period or "")
    if not m:
        raise ValueError("period must look like 2026-09")
    year, month = int(m.group(1)), int(m.group(2))
    start = datetime(year, month, 1, tzinfo=LOCAL_TZ)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=LOCAL_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
