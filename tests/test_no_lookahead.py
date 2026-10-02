import json

import pandas as pd

from src import config
from src.tools import ToolBox


def _fixtures(n=20):
    cases = []
    events = []
    for index in range(n):
        case_id = f"case-{index}"
        cases.append({"case_id": case_id, "vendor": "vendor-a", "was_blocked": True,
                      "post_price_change": False, "exposure_eur": 1000.0,
                      "pre_n_ir": 1, "pre_n_gr": 0, "pre_has_gr": False,
                      "invoice_before_gr": False, "pre_duplicate_ir": False,
                      "pre_price_change": False, "pre_qty_change": False,
                      "gr_ir_count_mismatch": False, "gr_expected": True,
                      "anchor_ts": pd.Timestamp("2020-01-02", tz="UTC")})
        events.extend([
            (case_id, "Record Invoice Receipt", "2020-01-01T00:00:00Z"),
            (case_id, "Set Payment Block", "2020-01-02T00:00:00Z"),
            (case_id, "Record Goods Receipt", "2020-01-03T00:00:00Z"),
            (case_id, "Remove Payment Block", "2020-01-04T00:00:00Z"),
            (case_id, "Clear Invoice", "2020-01-05T00:00:00Z"),
        ])
    return pd.DataFrame(cases), pd.DataFrame(events, columns=["case_id", "activity", "timestamp"])


def test_twenty_cases_have_no_future_events_in_tool_path():
    cases, events = _fixtures()
    box = ToolBox(cases, events)
    for case_id in cases.case_id:
        as_of = box.decision_time(case_id)
        visible = box.events_until(case_id, as_of)
        assert (visible.timestamp <= as_of).all()
        for tool in ["get_invoice", "lookup_po", "lookup_goods_receipt",
                      "check_duplicate_payment", "lookup_vendor_history", "lookup_policy"]:
            output = box.call(tool, case_id, as_of=as_of)
            serialized = json.dumps(output, default=str)
            assert "Remove Payment Block" not in serialized
            assert "Clear Invoice" not in serialized
        vendor_output = box.call("lookup_vendor_history", case_id, as_of=as_of)
        assert case_id not in json.dumps(vendor_output, default=str)


def test_vendor_history_excludes_current_and_future_resolutions():
    cases, events = _fixtures(1)
    extra_cases = pd.DataFrame([
        {"case_id": "before", "vendor": "vendor-a", "was_blocked": True,
         "post_price_change": False, "exposure_eur": 1000.0, "pre_n_ir": 1,
         "pre_n_gr": 1, "pre_has_gr": True, "invoice_before_gr": False,
         "pre_duplicate_ir": False, "pre_price_change": False, "pre_qty_change": False,
         "gr_ir_count_mismatch": False, "gr_expected": True, "anchor_ts": pd.Timestamp("2019-12-01", tz="UTC")},
        {"case_id": "after", "vendor": "vendor-a", "was_blocked": True,
         "post_price_change": False, "exposure_eur": 1000.0, "pre_n_ir": 1,
         "pre_n_gr": 1, "pre_has_gr": True, "invoice_before_gr": False,
         "pre_duplicate_ir": False, "pre_price_change": False, "pre_qty_change": False,
         "gr_ir_count_mismatch": False, "gr_expected": True, "anchor_ts": pd.Timestamp("2020-01-06", tz="UTC")},
    ])
    cases = pd.concat([cases, extra_cases], ignore_index=True)
    events = pd.concat([events, pd.DataFrame([
        ("before", "Record Invoice Receipt", "2019-12-01T00:00:00Z"),
        ("before", "Set Payment Block", "2019-12-02T00:00:00Z"),
        ("before", "Remove Payment Block", "2019-12-03T00:00:00Z"),
        ("after", "Record Invoice Receipt", "2020-01-06T00:00:00Z"),
        ("after", "Set Payment Block", "2020-01-07T00:00:00Z"),
        ("after", "Remove Payment Block", "2020-01-08T00:00:00Z"),
    ], columns=["case_id", "activity", "timestamp"])], ignore_index=True)
    box = ToolBox(cases, events)
    result = box.call("lookup_vendor_history", "case-0", as_of=pd.Timestamp("2020-01-02", tz="UTC"))
    assert result["vendor_case_count"] == 1
    assert "case-0" not in json.dumps(result, default=str)


def test_vendor_history_reports_same_class_recurrence_from_prior_cases_only():
    cases = pd.DataFrame([
        {"case_id": "current", "vendor": "vendor-a", "exception_class": "NO_EXCEPTION",
         "was_blocked": True, "post_price_change": False, "exposure_eur": 1000.0},
        {"case_id": "same-1", "vendor": "vendor-a", "exception_class": "NO_EXCEPTION",
         "was_blocked": True, "post_price_change": False, "exposure_eur": 1000.0},
        {"case_id": "same-2", "vendor": "vendor-a", "exception_class": "NO_EXCEPTION",
         "was_blocked": True, "post_price_change": True, "exposure_eur": 1000.0},
        {"case_id": "other-class", "vendor": "vendor-a", "exception_class": "DUPLICATE",
         "was_blocked": False, "post_price_change": False, "exposure_eur": 1000.0},
    ])
    events = []
    for case_id, day in [("same-1", "01"), ("same-2", "02"),
                         ("other-class", "03")]:
        events.extend([
            (case_id, config.A_INVOICE_RECEIPT, f"2020-01-{day}T00:00:00Z"),
            (case_id, config.A_REMOVE_BLOCK, f"2020-01-{day}T12:00:00Z"),
        ])
    event_frame = pd.DataFrame(events, columns=["case_id", "activity", "timestamp"])
    box = ToolBox(cases, event_frame)

    result = box.call("lookup_vendor_history", "current",
                      as_of=pd.Timestamp("2020-01-10", tz="UTC"))

    assert result["vendor_case_count"] == 3
    assert result["same_class_case_count"] == 2
    assert result["same_class_block_rate"] == 1.0
    assert result["same_class_correction_rate"] == 0.5
    assert result["same_class_recurrence"] is True


def test_po_change_after_invoice_is_visible_only_after_change_timestamp():
    cases, events = _fixtures(1)
    events = pd.concat([events, pd.DataFrame([
        ("case-0", config.A_CHANGE_PRICE, "2020-01-02T12:00:00Z"),
    ], columns=["case_id", "activity", "timestamp"])], ignore_index=True)
    box = ToolBox(cases, events)

    before_change = box.call("lookup_po", "case-0",
                             as_of=pd.Timestamp("2020-01-02T06:00:00Z"))
    after_change = box.call("lookup_po", "case-0",
                            as_of=pd.Timestamp("2020-01-03T00:00:00Z"))

    assert before_change["po_changed_after_invoice"] is False
    assert after_change["po_changed_after_invoice"] is True
