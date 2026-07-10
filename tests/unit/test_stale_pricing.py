import pandas as pd

from etf_dislocations.dislocation.stale_pricing import stale_pricing_flags

CALENDARS = {"EFA": "XLON"}


def test_domestic_ticker_never_flagged():
    dates = pd.DatetimeIndex(pd.bdate_range("2024-05-01", "2024-05-10"))
    flags = stale_pricing_flags(dates, "SPY", CALENDARS)
    assert not flags.any()


def test_uk_bank_holiday_flagged_for_efa():
    # 2024-05-06 was the UK Early May bank holiday (LSE closed, NYSE open);
    # 2024-05-07 both markets were open.
    dates = pd.DatetimeIndex(pd.to_datetime(["2024-05-06", "2024-05-07"]))
    flags = stale_pricing_flags(dates, "EFA", CALENDARS)
    assert bool(flags.loc["2024-05-06"]) is True
    assert bool(flags.loc["2024-05-07"]) is False


def test_regular_week_unflagged_for_efa():
    dates = pd.DatetimeIndex(pd.bdate_range("2024-06-10", "2024-06-14"))
    flags = stale_pricing_flags(dates, "EFA", CALENDARS)
    assert not flags.any()
