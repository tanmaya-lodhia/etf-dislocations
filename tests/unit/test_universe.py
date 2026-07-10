import pytest

from etf_dislocations.universe import VALID_BUCKETS, load_universe


def test_universe_matches_spec():
    u = load_universe()
    assert len(u.tickers) == 17
    assert len(set(u.tickers)) == 17
    # Spot-check the bucket structure from SPEC.md section 2.1.
    assert u.bucket_of("SPY") == "domestic_equity"
    assert u.bucket_of("EEM") == "international_equity"
    assert u.bucket_of("HYG") == "hy_credit"
    assert u.bucket_of("TLT") == "rates"
    assert all(e.bucket in VALID_BUCKETS for e in u.entries)


def test_unknown_ticker_raises():
    u = load_universe()
    with pytest.raises(KeyError):
        u.bucket_of("NOTREAL")


def test_subset_preserves_order_and_rejects_typos():
    u = load_universe()
    sub = u.subset(["TLT", "SPY"])
    assert sub.tickers == ["SPY", "TLT"]  # universe order, not request order
    with pytest.raises(KeyError):
        u.subset(["SPY", "TYPO"])
