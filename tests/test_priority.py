import pandas as pd

from src.priority import block_intervals, class_medians, build_queue, load_reference

T = pd.Timestamp


def _log():
    rows = []
    for cid, start, end in [("h1", "2018-01-01", "2018-01-11"),
                             ("h2", "2018-01-01", "2018-01-11"),
                             ("h3", "2018-01-01", "2018-01-21"),
                             ("e1", "2018-01-01", "2018-12-01"),
                             ("A", "2018-05-01", None), ("B", "2018-06-07", None),
                             ("C", "2018-06-05", None)]:
        rows.append((cid, "Record Invoice Receipt", T(start)))
        if end:
            rows.append((cid, "Remove Payment Block", T(end)))
    return pd.DataFrame(rows, columns=["case_id", "activity", "timestamp"])


LABELS = pd.DataFrame({"case_id": ["h1", "h2", "h3", "e1", "A", "B", "C"],
                       "exception_type": ["PV", "PV", "SEQ", "PV", "SEQ", "PV", "SEQ"]})


def test_medians_exclude_eval_and_report_n():
    medians = class_medians(block_intervals(_log()), LABELS, ["e1"])
    assert medians.loc["PV", "median_days"] == 10
    assert medians.loc["PV", "n"] == 2
    assert medians.loc["SEQ", "median_days"] == 20


def test_queue_order_and_overdue_driver():
    intervals = block_intervals(_log())
    medians = class_medians(intervals, LABELS, ["e1"])
    cases = pd.DataFrame({"case_id": ["A", "B", "C"], "owner": ["proc"] * 3,
                          "exception_type": ["SEQ", "PV", "SEQ"],
                          "exposure_eur": [8000, 50000, 2000],
                          "decision": ["ESCALATE", "HUMAN_APPROVAL", "HUMAN_APPROVAL"],
                          "evidence_level": ["WEAK"] * 3})
    queue = build_queue(cases, intervals, medians, "2018-06-10")
    assert list(queue.case_id) == ["B", "A", "C"]
    assert queue.set_index("case_id").loc["A", "priority_driver"] == "overdue"


def test_auto_resolved_and_closed_cases_excluded():
    intervals = block_intervals(_log())
    medians = class_medians(intervals, LABELS, ["e1"])
    cases = pd.DataFrame({"case_id": ["A", "h1"], "owner": ["proc", "proc"],
                          "exception_type": ["SEQ", "PV"], "exposure_eur": [1, 1],
                          "decision": ["AUTO_RESOLVE", "ESCALATE"],
                          "evidence_level": ["STRONG", "WEAK"]})
    assert build_queue(cases, intervals, medians, "2018-06-10").empty


def test_reference_table_roundtrip(tmp_path):
    intervals = block_intervals(_log())
    medians = class_medians(intervals, LABELS, ["e1"])
    path = tmp_path / "reference.csv"
    medians.reset_index().rename(columns={"index": "exception_type"}).to_csv(path, index=False)
    reference = load_reference(path)
    assert list(build_queue(
        pd.DataFrame({"case_id": ["A", "B", "C"], "owner": ["proc"] * 3,
                      "exception_type": ["SEQ", "PV", "SEQ"], "exposure_eur": [8000, 50000, 2000],
                      "decision": ["ESCALATE", "HUMAN_APPROVAL", "HUMAN_APPROVAL"],
                      "evidence_level": ["WEAK"] * 3}),
        intervals, reference, "2018-06-10").case_id) == ["B", "A", "C"]
