import pandas as pd

from src.decision_time import decision_time


def _events(rows):
    return pd.DataFrame(rows, columns=["activity", "timestamp"])


def test_block_time_wins_over_invoice_time():
    events = _events([("Record Invoice Receipt", pd.Timestamp("2020-01-03")),
                      ("Set Payment Block", pd.Timestamp("2020-01-02"))])
    assert decision_time(events) == pd.Timestamp("2020-01-02")


def test_invoice_time_when_no_block():
    events = _events([("Record Invoice Receipt", pd.Timestamp("2020-01-03"))])
    assert decision_time(events) == pd.Timestamp("2020-01-03")


def test_none_when_neither_exists():
    events = _events([("Clear Invoice", pd.Timestamp("2020-01-03"))])
    assert decision_time(events) is None
