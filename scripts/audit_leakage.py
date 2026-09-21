"""Audit the pre-v1.2 tools for evidence visible after decision time."""

from datetime import datetime
from pathlib import Path
import json
import re
import sys
import argparse

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.compute as pc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config as C
import data
import labels
from tools import ToolBox
from decision_time import decision_time

TOOLS = ["get_invoice", "lookup_po", "lookup_goods_receipt",
         "check_duplicate_payment", "lookup_vendor_history", "lookup_policy"]
END_ACTIVITIES = {C.A_REMOVE_BLOCK, C.A_CLEAR_INVOICE}


def _sample_features(events, sample_ids):
    rows = []
    for case_id in sample_ids:
        frame = events[events[C.CASE_COL].astype(str) == case_id]
        invoice = frame[frame[C.ACT_COL] == C.A_INVOICE_RECEIPT]
        gr = frame[frame[C.ACT_COL].isin(C.GR_ACTS)]
        vendor = frame[C.VENDOR_COL].dropna().iloc[0] if C.VENDOR_COL in frame and frame[C.VENDOR_COL].notna().any() else None
        rows.append({"case_id": case_id, "vendor": vendor, "was_blocked": True,
                     "post_price_change": False, "exposure_eur": 0.0,
                     "pre_n_ir": len(invoice), "pre_n_gr": len(gr),
                     "pre_has_gr": bool(len(gr)), "invoice_before_gr": False,
                     "pre_duplicate_ir": len(invoice) > 1, "pre_price_change": False,
                     "pre_qty_change": False, "gr_ir_count_mismatch": False,
                     "gr_expected": True, "anchor_ts": decision_time(
                         frame.rename(columns={C.ACT_COL: "activity", C.TS_COL: "timestamp"}))})
    return pd.DataFrame(rows)


def _timestamps(value, path="root"):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(_timestamps(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_timestamps(item, f"{path}[{index}]"))
    elif isinstance(value, (pd.Timestamp, datetime)):
        found.append((path, pd.Timestamp(value)))
    elif isinstance(value, str):
        try:
            parsed = pd.Timestamp(value)
            if parsed is not pd.NaT and parsed.year >= 2000:
                found.append((path, parsed))
        except (TypeError, ValueError):
            pass
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--v12", action="store_true")
    args = parser.parse_args()
    eval_ids = pd.read_csv(ROOT / "outputs" / "eval_set.csv")["case_id"].astype(str)
    sample_ids = eval_ids.sample(n=min(10, len(eval_ids)), random_state=C.RANDOM_SEED).tolist()
    sample_path = ROOT / "outputs" / "audit_sample.parquet"
    if sample_path.exists():
        events = pd.read_parquet(sample_path)
    else:
        dataset = ds.dataset(C.PARQUET_PATH, format="parquet")
        table = dataset.to_table(
            columns=[C.CASE_COL, C.ACT_COL, C.TS_COL, C.VENDOR_COL],
            filter=pc.is_in(ds.field(C.CASE_COL), value_set=pa.array(sample_ids)))
        events = table.to_pandas()
        events.to_parquet(sample_path, index=False)
    features = _sample_features(events, sample_ids)
    box = ToolBox(features, events=events) if args.v12 else ToolBox(features)
    rows = []
    for case_id in sample_ids:
        case_events = events[events[C.CASE_COL].astype(str) == case_id].rename(
            columns={C.ACT_COL: "activity", C.TS_COL: "timestamp"})
        as_of = decision_time(case_events)
        vendor = features.loc[features.case_id.astype(str) == case_id, "vendor"].iloc[0]
        vendor_future = events[
            (events.get(C.VENDOR_COL, pd.Series(index=events.index)) == vendor)
            & (events[C.TS_COL] > as_of if as_of is not None else False)
            & events[C.ACT_COL].isin(END_ACTIVITIES)
        ] if vendor is not None and C.VENDOR_COL in events.columns else pd.DataFrame()
        for tool in TOOLS:
            output = box.call(tool, case_id, as_of=as_of) if args.v12 else box.call(tool, case_id)
            offending = [(path, str(ts)) for path, ts in _timestamps(output)
                         if as_of is not None and ts > as_of]
            if not args.v12 and tool == "lookup_vendor_history" and (not vendor_future.empty or
                                                     output.get("vendor_case_count", 0) > 0):
                offending.append(("vendor_history.future_resolution", str(vendor_future[C.TS_COL].min())))
            rows.append({"case_id": case_id, "decision_time": str(as_of),
                         "tool": tool, "status": "FAIL" if offending else "PASS",
                         "offending_fields": json.dumps(offending)})
    version = "v1.2" if args.v12 else "v1.1"
    out = ROOT / "outputs" / f"leakage_audit_{version}.md"
    lines = [f"# Look-ahead leakage audit {version}", "",
             ("Filtered tools were called with the system decision-time cutoff."
              if args.v12 else "Current tools were called without an `as_of` filter."), "",
             "| Case | Decision time | Tool | Result | Offending field |",
             "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['case_id']} | {row['decision_time']} | {row['tool']} | "
                     f"{row['status']} | {row['offending_fields']} |")
    out.write_text("\n".join(lines) + "\n")
    print(pd.DataFrame(rows).groupby(["tool", "status"]).size())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
