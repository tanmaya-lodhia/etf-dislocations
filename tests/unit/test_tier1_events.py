import pandas as pd
import pytest

from etf_dislocations.stress.tier1_events import event_for_dates, load_tier1_events


def test_configured_events_match_spec():
    events = load_tier1_events()
    names = [e.name for e in events]
    assert names == ["flash_crash_2015", "selloff_dec2018", "covid_2020", "rates_2022"]
    covid = events[2]
    assert covid.start == pd.Timestamp("2020-02-24")
    assert covid.end == pd.Timestamp("2020-04-03")


def test_known_dates_mapped_to_events():
    events = load_tier1_events()
    dates = pd.DatetimeIndex(
        pd.to_datetime(
            ["2015-08-24", "2018-12-24", "2020-03-16", "2022-09-28", "2024-01-15"]
        )
    )
    mapped = event_for_dates(dates, events)
    assert mapped.iloc[0] == "flash_crash_2015"
    assert mapped.iloc[1] == "selloff_dec2018"
    assert mapped.iloc[2] == "covid_2020"
    assert mapped.iloc[3] == "rates_2022"
    assert pd.isna(mapped.iloc[4])


def _write_events(tmp_path, events_yaml):
    path = tmp_path / "events.yaml"
    path.write_text(events_yaml, encoding="utf-8")
    return path


def test_reversed_window_rejected(tmp_path):
    path = _write_events(
        tmp_path,
        "events:\n  - {name: bad, start: 2020-03-01, end: 2020-02-01}\n",
    )
    with pytest.raises(ValueError, match="before start"):
        load_tier1_events(path)


def test_overlapping_windows_rejected(tmp_path):
    path = _write_events(
        tmp_path,
        "events:\n"
        "  - {name: a, start: 2020-01-01, end: 2020-02-01}\n"
        "  - {name: b, start: 2020-01-15, end: 2020-03-01}\n",
    )
    with pytest.raises(ValueError, match="overlap"):
        load_tier1_events(path)
