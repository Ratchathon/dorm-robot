from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.billing import Reading, bill_line, money, period_of, period_bounds, units_used


def r(value, rollover=False):
    return Reading(value=value, rollover=rollover)


@pytest.mark.parametrize("prev, curr, rollover, expected", [
    ("3312", "3398", False, 86),
    ("0834", "0834", False, 0),
    ("9990", "0015", True, 25),
    ("99990", "00015", True, 25),
    ("3312", "3300", False, None),   # lower without rollover -> needs review
])
def test_units_used(prev, curr, rollover, expected):
    assert units_used(prev, curr, rollover) == expected


def test_money_rounds_half_up_to_satang():
    assert money(Decimal("86") * Decimal("7.125")) == Decimal("612.75")
    assert money(Decimal("0.005")) == Decimal("0.01")


def test_bill_line_ok():
    line = bill_line(prev=r("3312"), curr=r("3398"), price=Decimal("7"))
    assert line["status"] == "ok" and line["units"] == 86 and line["amount"] == Decimal("602.00")


def test_bill_line_missing_current():
    assert bill_line(prev=r("3312"), curr=None, price=Decimal("7"))["status"] == "missing"


def test_bill_line_first_reading_is_baseline():
    line = bill_line(prev=None, curr=r("0851"), price=Decimal("18"))
    assert line["status"] == "first" and line["amount"] is None


def test_bill_line_lower_needs_review():
    line = bill_line(prev=r("5120"), curr=r("5098"), price=Decimal("7"))
    assert line["status"] == "review" and line["amount"] is None


def test_bill_line_rollover():
    line = bill_line(prev=r("9990"), curr=r("0015", rollover=True), price=Decimal("7"))
    assert line["units"] == 25 and line["amount"] == Decimal("175.00")


def test_bill_line_without_rate():
    line = bill_line(prev=r("1"), curr=r("5"), price=None)
    assert line["status"] == "no_rate" and line["units"] == 4


def test_period_uses_thai_time():
    # 30 Sep 2026 18:30 UTC is already 1 Oct 01:30 in Bangkok
    assert period_of(datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)) == "2026-10"


def test_period_bounds():
    start, end = period_bounds("2026-12")
    assert start.isoformat() == "2026-11-30T17:00:00+00:00"
    assert end.isoformat() == "2026-12-31T17:00:00+00:00"


@pytest.mark.parametrize("bad", ["2026-13", "26-01", "abcd-ef", "", None])
def test_period_bounds_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        period_bounds(bad)
