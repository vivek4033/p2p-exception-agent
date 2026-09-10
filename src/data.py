"""
data.py — loading and the synthetic test fixture.

The synthetic generator exists so the whole pipeline can be built and tested
before the real log lands. It reproduces the STRUCTURE of BPI 2019 (case per PO
line item, event-level cumulative net worth, batch vs human resources, price and
quantity change events, payment blocks) but none of its content.

Nothing produced from synthetic data may be reported. config.stamp() enforces
the label on every output.
"""

import os
import gc
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import config as C


# --------------------------------------------------------------------- loading
def parquet_stage0(path):
    """Return event/case/activity counts without loading the full parquet."""
    parquet = pq.ParquetFile(path)
    cases, activities, events = set(), set(), 0
    for batch in parquet.iter_batches(batch_size=100000,
                                      columns=[C.CASE_COL, C.ACT_COL]):
        data = batch.to_pydict()
        cases.update(data[C.CASE_COL])
        activities.update(data[C.ACT_COL])
        events += batch.num_rows
    return events, len(cases), len(activities), activities


def load_log():
    """Return a flat event dataframe according to config.DATA_SOURCE."""
    if C.DATA_SOURCE == "synthetic":
        return make_synthetic_log()

    if os.path.exists(C.PARQUET_PATH):
        needed = [C.CASE_COL, C.ACT_COL, C.TS_COL, C.VALUE_COL,
              getattr(C, "GR_EXPECTED_COL", None)]
        return pd.read_parquet(
            C.PARQUET_PATH,
            columns=[c for c in dict.fromkeys(needed) if c],
            dtype_backend="numpy_nullable",
        )

    path = C.REAL_LOG_PATH
    if path.endswith(".csv"):
        df = pd.read_csv(path, sep=None, engine="python")
        df = _standardise_columns(df)
    else:
        import pm4py
        log = pm4py.read_xes(path)
        df = pm4py.convert_to_dataframe(log) if not isinstance(log, pd.DataFrame) else log

    df[C.TS_COL] = pd.to_datetime(df[C.TS_COL], errors="coerce", utc=True)
    df = df.dropna(subset=[C.TS_COL])
    os.makedirs("data", exist_ok=True)
    df.to_parquet(C.PARQUET_PATH, index=False)
    return df


def _standardise_columns(df):
    """Map the BPI 2019 CSV headers onto the XES-style names config expects."""
    rename = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc in ("event activity", "activity", "concept:name"):
            rename[c] = C.ACT_COL
        elif lc in ("event timestamp", "timestamp", "time:timestamp"):
            rename[c] = C.TS_COL
        elif lc in ("event user", "user", "org:resource", "resource"):
            rename[c] = C.USER_COL
        elif "purchasing document" in lc or lc in ("case id", "case:concept:name"):
            rename.setdefault(c, C.CASE_COL)
        elif "cumulative net worth" in lc:
            rename[c] = C.VALUE_COL
    return df.rename(columns=rename)


# ------------------------------------------------------------------- synthetic
def make_synthetic_log(n_cases=2500, seed=None):
    """Structurally faithful fixture. Content is invented and must never be reported."""
    rng = np.random.default_rng(C.RANDOM_SEED if seed is None else seed)
    rows = []

    n_vendors = 60
    # deliberately skewed vendor exception propensity, so the supply-chain
    # concentration layer has something to find in testing
    vendor_risk = rng.beta(1.4, 6.0, n_vendors)

    for i in range(n_cases):
        cid = f"{72000000 + i}_{rng.integers(1, 4):05d}"
        vendor = int(rng.integers(0, n_vendors))
        po_value = float(np.round(rng.lognormal(7.6, 1.15), 2))
        t = pd.Timestamp("2018-01-01", tz="UTC") + pd.Timedelta(days=int(rng.integers(0, 400)))

        def ev(act, ts, value, human=False):
            rows.append({
                C.CASE_COL: cid,
                C.ACT_COL: act,
                C.TS_COL: ts,
                C.USER_COL: (f"user_{rng.integers(1, 90):03d}" if human
                             else f"batch_{rng.integers(1, 6):02d}"),
                C.VENDOR_COL: f"vendor_{vendor:04d}",
                C.VALUE_COL: float(np.round(value, 2)),
                C.DOCTYPE_COL: "Standard PO",
                C.ITEMTYPE_COL: rng.choice(["Standard", "Service", "Consignment"],
                                           p=[0.78, 0.17, 0.05]),
                C.SPEND_COL: rng.choice(["Packaging", "Raw Materials", "MRO",
                                         "Logistics", "Services"]),
                C.GR_BASED_IV_COL: True,
                C.GOODS_RECEIPT_COL: True,
            })

        ev(C.A_CREATE_PO, t, po_value)

        p_exc = 0.10 + 0.55 * vendor_risk[vendor]
        exception = rng.random() < p_exc

        # goods receipt
        t += pd.Timedelta(days=int(rng.integers(2, 25)))
        gr_value = po_value
        invoice_before_gr = exception and rng.random() < 0.18
        if not invoice_before_gr:
            ev(C.A_GOODS_RECEIPT, t, gr_value)

        # invoice
        t += pd.Timedelta(days=int(rng.integers(1, 20)))
        if exception:
            kind = rng.choice(["price", "qty", "seq", "dup"], p=[0.50, 0.26, 0.14, 0.10])
        else:
            kind = "none"

        if kind == "price":
            drift = rng.normal(0, 0.045)
            drift = float(np.clip(abs(drift) + 0.002, 0.002, 0.30)) * rng.choice([1, -1])
            inv_value = po_value * (1 + drift)
        elif kind == "qty":
            inv_value = po_value * (1 + rng.uniform(0.01, 0.22) * rng.choice([1, -1]))
        else:
            inv_value = po_value * (1 + rng.normal(0, 0.002))

        ev(C.A_VENDOR_INVOICE, t, inv_value)
        t += pd.Timedelta(days=int(rng.integers(0, 6)))
        ev(C.A_INVOICE_RECEIPT, t, inv_value)

        if invoice_before_gr:
            t += pd.Timedelta(days=int(rng.integers(1, 12)))
            ev(C.A_GOODS_RECEIPT, t, gr_value)

        if kind == "dup":
            t += pd.Timedelta(days=int(rng.integers(1, 10)))
            ev(C.A_INVOICE_RECEIPT, t, inv_value)
            if rng.random() < 0.6:
                t += pd.Timedelta(days=int(rng.integers(1, 8)))
                ev(C.A_CANCEL_INVOICE, t, inv_value, human=True)

        blocked = exception and abs(inv_value / po_value - 1) * 100 > 1.0
        if blocked:
            t += pd.Timedelta(days=int(rng.integers(0, 3)))
            ev(C.A_SET_BLOCK, t, inv_value)

            # resolution path: with or without an observed PO correction
            corrected = rng.random() < (0.55 if kind == "price" else 0.35)
            if corrected:
                t += pd.Timedelta(days=int(rng.integers(1, 22)))
                ev(C.A_CHANGE_PRICE if kind == "price" else C.A_CHANGE_QUANTITY,
                   t, po_value, human=True)

            t += pd.Timedelta(days=int(rng.integers(1, 30)))
            ev(C.A_REMOVE_BLOCK, t, inv_value, human=True)

        t += pd.Timedelta(days=int(rng.integers(1, 25)))
        ev(C.A_CLEAR_INVOICE, t, inv_value)

    df = pd.DataFrame(rows).sort_values([C.CASE_COL, C.TS_COL]).reset_index(drop=True)
    return df


# --------------------------------------------------------------- case features
# Memory design note.
#
# The naive version filtered the full event frame once per activity lookup —
# about twenty full or partial copies of a 1.6M-row table. That is what gets a
# process killed by the OS with no traceback.
#
# This version does FOUR passes total, on a slim four-column frame with
# categorical keys:
#   1. first timestamp + value per (case, activity)   -> one groupby, unstacked
#   2. event count per (case, activity)               -> one groupby, unstacked
#   3. prefix counts  (events at or before the anchor)
#   4. suffix counts  (events after the anchor)
# Everything else is a column select against those four tables.
#
# Categorical dtypes on case id and activity cut memory by roughly an order of
# magnitude on this log, because 251,734 case ids stored as Python strings is
# most of the footprint.

def _slim(df):
    """Four columns, categorical keys, sorted once."""
    cols = [C.CASE_COL, C.ACT_COL, C.TS_COL]
    if C.VALUE_COL in df.columns:
        cols.append(C.VALUE_COL)
    s = df if set(df.columns).issubset(cols + [C.USER_COL,
                                                getattr(C, "GR_EXPECTED_COL", "")]) else df[cols].copy()
    s[C.CASE_COL] = s[C.CASE_COL].astype("category")
    s[C.ACT_COL] = s[C.ACT_COL].astype("category")
    s[C.TS_COL] = pd.to_datetime(s[C.TS_COL], errors="coerce", utc=True)
    if C.VALUE_COL in s.columns:
        # BPI 2019 parquet can carry this as a string. Coerce once, here.
        s[C.VALUE_COL] = pd.to_numeric(s[C.VALUE_COL], errors="coerce")
    else:
        s[C.VALUE_COL] = np.nan
    return s.sort_values([C.CASE_COL, C.TS_COL], kind="mergesort")


def _pivot_first(slim):
    """First timestamp and first value per (case, activity). One pass."""
    g = slim.groupby([C.CASE_COL, C.ACT_COL], observed=True, sort=False)
    agg = g.agg(ts=(C.TS_COL, "first"), val=(C.VALUE_COL, "first"))
    return agg["ts"].unstack(C.ACT_COL), agg["val"].unstack(C.ACT_COL)


def _pivot_count(frame):
    """Event count per (case, activity). One pass."""
    if frame.empty:
        return pd.DataFrame()
    return (frame.groupby([C.CASE_COL, C.ACT_COL], observed=True, sort=False)
            .size().unstack(C.ACT_COL))


def _col(tbl, acts, index, how="first"):
    """Select one or more activity columns out of a pivot, tolerating absence."""
    if isinstance(acts, str):
        acts = [acts]
    have = [a for a in acts if tbl is not None and a in tbl.columns]
    if not have:
        return pd.Series(np.nan, index=index)
    sub = tbl[have]
    return (sub.min(axis=1) if how == "first" else sub.sum(axis=1)).reindex(index)


def _stream_case_features(path, with_variants=False):
    """Reduce a case-contiguous parquet log without materialising its events."""
    columns = [C.CASE_COL, C.ACT_COL, C.TS_COL, C.VALUE_COL,
               getattr(C, "GR_EXPECTED_COL", None)]
    columns = [c for c in dict.fromkeys(columns) if c]
    parquet = pq.ParquetFile(path)
    records = []
    temp_path = os.path.join("data", f".case_features_{os.getpid()}.csv")
    try:
        os.remove(temp_path)
    except FileNotFoundError:
        pass
    wrote_header = False
    next_report = 25000
    current_id = None
    state = None
    relevant = set(C.GR_ACTS + C.UNBLOCK_ACTS + C.BLOCK_ACTS +
                   C.PRICE_CHANGE_ACTS + C.QTY_CHANGE_ACTS + C.CANCEL_ACTS +
                   [C.A_CREATE_PO, C.A_INVOICE_RECEIPT, C.A_VENDOR_INVOICE,
                    C.A_CLEAR_INVOICE])

    def new_state(case_id):
        return {"case_id": case_id, "n_events": 0, "start_ts": None,
                "end_ts": None, "max_value": np.nan, "gr_expected": True,
                "gr_expected_seen": False, "events": [], "activities": []}

    def finish(s):
        if s is None:
            return None
        events = s["events"]
        by_act = {}
        for act, ts, value in events:
            by_act.setdefault(act, []).append((ts, value))

        def times(acts):
            return [ts for act in acts for ts, _ in by_act.get(act, [])]

        def first_time(acts):
            vals = times(acts)
            return min(vals) if vals else None

        def first_value(acts):
            vals = [value for act in acts for _, value in by_act.get(act, [])
                    if pd.notna(value)]
            return vals[0] if vals else np.nan

        first_ir = first_time([C.A_INVOICE_RECEIPT])
        last_ir = max(times([C.A_INVOICE_RECEIPT]), default=None)
        first_gr = first_time(C.GR_ACTS)
        first_block = first_time(C.BLOCK_ACTS)
        first_unblock = first_time(C.UNBLOCK_ACTS)
        anchor = last_ir or first_ir or first_block or s["end_ts"]
        pre = [(a, t, v) for a, t, v in events if t <= anchor]
        post = [(a, t, v) for a, t, v in events if t > anchor]

        def count(frame, acts):
            return sum(a in acts for a, _, _ in frame)

        po_value = first_value([C.A_CREATE_PO])
        invoice_value = first_value([C.A_INVOICE_RECEIPT])
        if pd.isna(invoice_value):
            invoice_value = first_value([C.A_VENDOR_INVOICE])
        variance = np.nan
        if pd.notna(po_value) and po_value != 0 and pd.notna(invoice_value):
            variance = (invoice_value - po_value) / po_value * 100
        was_blocked = bool(first_unblock or first_block)
        has_gr = bool(first_gr)
        record = {
            "case_id": s["case_id"], "n_events": s["n_events"],
            "start_ts": s["start_ts"], "end_ts": s["end_ts"],
            "cycle_days": (s["end_ts"] - s["start_ts"]).total_seconds() / 86400,
            "vendor": None, "item_type": None, "spend_area": None, "doc_type": None,
            "po_value": po_value, "gr_value": first_value(C.GR_ACTS),
            "invoice_value": invoice_value, "price_variance_pct": variance,
            "abs_variance_pct": abs(variance) if pd.notna(variance) else np.nan,
            "exposure_eur": invoice_value if pd.notna(invoice_value) else s["max_value"],
            "invoice_before_gr": bool(first_ir and first_gr and first_ir < first_gr),
            "block_to_resolution_days": ((first_unblock - first_block).total_seconds() / 86400
                                          if first_unblock and first_block else np.nan),
            "invoice_to_unblock_days": ((first_unblock - anchor).total_seconds() / 86400
                                         if first_unblock and anchor else np.nan),
            "anchor_ts": anchor, "has_gr": has_gr, "gr_expected": s["gr_expected"],
            "gr_expectation_source": getattr(C, "GR_EXPECTED_COL", "assumed_true"),
            "was_blocked": was_blocked, "block_set_event_present": bool(first_block),
            "block_removed": bool(first_unblock),
            "po_price_changed": bool(times(C.PRICE_CHANGE_ACTS)),
            "po_qty_changed": bool(times(C.QTY_CHANGE_ACTS)),
            "cancelled": bool(times(C.CANCEL_ACTS)),
            "cleared": bool(times([C.A_CLEAR_INVOICE])),
            "terminal": bool(times([C.A_CLEAR_INVOICE]) or first_unblock or times(C.CANCEL_ACTS)),
            "n_invoice_receipts": count(events, [C.A_INVOICE_RECEIPT]),
            "duplicate_pattern": count(events, [C.A_INVOICE_RECEIPT]) > 1,
            "pre_n_gr": count(pre, C.GR_ACTS),
            "pre_n_ir": count(pre, [C.A_INVOICE_RECEIPT]),
            "pre_has_gr": count(pre, C.GR_ACTS) > 0,
            "pre_price_change": count(pre, C.PRICE_CHANGE_ACTS) > 0,
            "pre_qty_change": count(pre, C.QTY_CHANGE_ACTS) > 0,
            "pre_duplicate_ir": count(pre, [C.A_INVOICE_RECEIPT]) > 1,
            "pre_duplicate_gr": count(pre, C.GR_ACTS) > 1,
            "gr_ir_count_mismatch": (count(pre, C.GR_ACTS) != count(pre, [C.A_INVOICE_RECEIPT])
                                      and (count(pre, C.GR_ACTS) > 0 or count(pre, [C.A_INVOICE_RECEIPT]) > 0)),
            "post_price_change": count(post, C.PRICE_CHANGE_ACTS) > 0,
            "post_qty_change": count(post, C.QTY_CHANGE_ACTS) > 0,
            "post_cancelled": count(post, C.CANCEL_ACTS) > 0,
            "post_block_removed": count(post, C.UNBLOCK_ACTS) > 0,
            "human_touches": int(bool(was_blocked or times(C.PRICE_CHANGE_ACTS) or
                                       times(C.QTY_CHANGE_ACTS) or times(C.CANCEL_ACTS))),
        }
        if with_variants:
            record["variant"] = " -> ".join(s["activities"])
        return record

    for batch in parquet.iter_batches(batch_size=10000, columns=columns):
        data = batch.to_pydict()
        for values in zip(*(data[c] for c in columns)):
            row = dict(zip(columns, values))
            case_id = row[C.CASE_COL]
            if current_id is not None and case_id != current_id:
                records.append(finish(state))
                if len(records) >= 25000:
                    pd.DataFrame(records).to_csv(temp_path, mode="a",
                                                 header=not wrote_header, index=False)
                    wrote_header = True
                    records.clear()
                    gc.collect()
                state = new_state(case_id)
            elif state is None:
                state = new_state(case_id)
            current_id = case_id
            ts = pd.Timestamp(row[C.TS_COL])
            value = pd.to_numeric(row.get(C.VALUE_COL), errors="coerce")
            act = row[C.ACT_COL]
            state["n_events"] += 1
            state["start_ts"] = ts if state["start_ts"] is None else min(state["start_ts"], ts)
            state["end_ts"] = ts if state["end_ts"] is None else max(state["end_ts"], ts)
            if pd.notna(value):
                state["max_value"] = max(state["max_value"], value) if pd.notna(state["max_value"]) else value
            if not state["gr_expected_seen"] and C.GR_EXPECTED_COL in row:
                state["gr_expected"] = str(row[C.GR_EXPECTED_COL]).lower() in ("true", "1", "yes")
                state["gr_expected_seen"] = True
            if with_variants:
                state["activities"].append(act)
            if act in relevant:
                state["events"].append((act, ts, value))
        if len(records) >= next_report:
            print(f"  streamed {len(records):,} cases", flush=True)
            next_report += 25000
    if state is not None:
        records.append(finish(state))
    if records:
        pd.DataFrame(records).to_csv(temp_path, mode="a",
                                     header=not wrote_header, index=False)
    result = pd.read_csv(temp_path, parse_dates=["start_ts", "end_ts", "anchor_ts"])
    try:
        os.remove(temp_path)
    except PermissionError:
        pass
    return result


def case_features(df, with_variants=False):
    """
    Collapse the event log to one row per case. Everything downstream reads this
    table, so a schema correction in config propagates from one point.
    """
    if C.DATA_SOURCE != "synthetic" and os.path.exists(C.PARQUET_PATH):
        return _stream_case_features(C.PARQUET_PATH, with_variants)

    slim = _slim(df)
    first_ts, first_val = _pivot_first(slim)
    counts = _pivot_count(slim)
    idx = first_ts.index

    out = pd.DataFrame(index=idx)
    out.index.name = "case_id"

    # ---- scale and timing, from the count and timestamp pivots
    out["n_events"] = counts.sum(axis=1).astype(int)
    out["start_ts"] = first_ts.min(axis=1)
    end = slim.groupby(C.CASE_COL, observed=True, sort=False)[C.TS_COL].max()
    out["end_ts"] = end.reindex(idx)
    out["cycle_days"] = (out["end_ts"] - out["start_ts"]).dt.total_seconds() / 86400

    # ---- optional case-level attributes
    for col, name in [(C.VENDOR_COL, "vendor"), (C.ITEMTYPE_COL, "item_type"),
                      (C.SPEND_COL, "spend_area"), (C.DOCTYPE_COL, "doc_type")]:
        if col in df.columns:
            out[name] = df.groupby(C.CASE_COL, observed=True, sort=False)[col].first().reindex(idx)
        else:
            out[name] = None

    # ---- document values
    out["po_value"] = _col(first_val, C.A_CREATE_PO, idx)
    out["gr_value"] = _col(first_val, C.GR_ACTS, idx)
    inv_v = _col(first_val, C.A_INVOICE_RECEIPT, idx)
    out["invoice_value"] = inv_v.fillna(_col(first_val, C.A_VENDOR_INVOICE, idx))

    with np.errstate(divide="ignore", invalid="ignore"):
        out["price_variance_pct"] = ((out["invoice_value"] - out["po_value"])
                                     / out["po_value"].replace(0, np.nan) * 100)
    out["abs_variance_pct"] = out["price_variance_pct"].abs()
    out["exposure_eur"] = out["invoice_value"].fillna(out["po_value"])
    if out["exposure_eur"].isna().all():
        # no per-document amounts in this log; net worth is case-level
        out["exposure_eur"] = (slim.groupby(C.CASE_COL, observed=True, sort=False)
                               [C.VALUE_COL].max().reindex(idx))

    # ---- sequencing and block timing
    gr_ts = _col(first_ts, C.GR_ACTS, idx)
    inv_ts = _col(first_ts, C.A_INVOICE_RECEIPT, idx)
    blk_ts = _col(first_ts, C.BLOCK_ACTS, idx)
    unblk_ts = _col(first_ts, C.UNBLOCK_ACTS, idx)

    out["invoice_before_gr"] = (inv_ts.notna() & gr_ts.notna() & (inv_ts < gr_ts))
    out["block_to_resolution_days"] = (unblk_ts - blk_ts).dt.total_seconds() / 86400

    # ---- the anchor: the moment the case enters exception handling
    #
    # This is the LAST invoice receipt, not the first, and the distinction
    # matters. An AP clerk opening a blocked case sees every invoice that has
    # arrived by then — including a duplicate. Anchoring on the first receipt
    # puts every subsequent receipt in the suffix by construction, which makes
    # duplicate detection structurally impossible: the class fires only on
    # timestamp ties.
    #
    # Anchoring on the last receipt also moves a PO amendment that preceded the
    # final invoice into the prefix, which is correct — the clerk can see it.
    # Amendments AFTER the last invoice remain suffix, and those are the
    # resolution action. The leakage check is what guards this boundary.
    last_ir = (slim[slim[C.ACT_COL] == C.A_INVOICE_RECEIPT]
               .groupby(C.CASE_COL, observed=True)[C.TS_COL].max().reindex(idx))
    anchor = last_ir.fillna(inv_ts).fillna(blk_ts).fillna(out["end_ts"])
    out["invoice_to_unblock_days"] = (unblk_ts - anchor).dt.total_seconds() / 86400
    out["anchor_ts"] = anchor

    # ---- structural flags, all from the count pivot
    def has(acts):
        return _col(counts, acts, idx, how="sum").fillna(0) > 0

    out["has_gr"] = has(C.GR_ACTS)
    _set_block = has(C.BLOCK_ACTS)
    _removed = has(C.UNBLOCK_ACTS)
    out["was_blocked"] = ((_set_block | _removed)
                          if getattr(C, "BLOCK_INFERRED_FROM_REMOVAL", False)
                          else _set_block)
    out["block_set_event_present"] = _set_block
    out["block_removed"] = _removed
    out["po_price_changed"] = has(C.PRICE_CHANGE_ACTS)
    out["po_qty_changed"] = has(C.QTY_CHANGE_ACTS)
    out["cancelled"] = has(C.CANCEL_ACTS)
    out["cleared"] = has(C.A_CLEAR_INVOICE)
    out["terminal"] = out["cleared"] | out["block_removed"] | out["cancelled"]
    out["n_invoice_receipts"] = _col(counts, C.A_INVOICE_RECEIPT, idx,
                                     how="sum").fillna(0).astype(int)
    out["duplicate_pattern"] = out["n_invoice_receipts"] > 1

    # ---- goods-receipt expectation
    gr_col = getattr(C, "GR_EXPECTED_COL", None)
    cat_col = getattr(C, "ITEM_CATEGORY_COL", None)
    if gr_col and gr_col in df.columns:
        exp = df.groupby(C.CASE_COL, observed=True, sort=False)[gr_col].first().reindex(idx)
        out["gr_expected"] = exp.astype(str).str.lower().isin(["true", "1", "yes"])
        out["gr_expectation_source"] = gr_col
    elif cat_col and cat_col in df.columns:
        cat = df.groupby(C.CASE_COL, observed=True, sort=False)[cat_col].first().reindex(idx).astype(str)
        pat = "|".join(getattr(C, "NO_GR_ITEM_CATEGORIES", []))
        out["gr_expected"] = ~cat.str.contains(pat, case=False, na=False)
        out["gr_expectation_source"] = cat_col
    else:
        out["gr_expected"] = True
        out["gr_expectation_source"] = "assumed_true_no_field_available"

    # ---- prefix / suffix split (leakage control)
    # Evidence available AT THE MOMENT the invoice arrived must stay strictly
    # separate from what happened afterwards. Without this, "a price change
    # occurred" would be both the feature and the target.
    anchor_per_event = slim[C.CASE_COL].map(anchor)
    is_pre = slim[C.TS_COL] <= anchor_per_event
    pre_counts = _pivot_count(slim[is_pre])
    post_counts = _pivot_count(slim[~is_pre])
    del anchor_per_event, is_pre

    def pre_n(acts):
        return _col(pre_counts, acts, idx, how="sum").fillna(0).astype(int)

    def post_has(acts):
        return _col(post_counts, acts, idx, how="sum").fillna(0) > 0

    out["pre_n_gr"] = pre_n(C.GR_ACTS)
    out["pre_n_ir"] = pre_n(C.A_INVOICE_RECEIPT)
    out["pre_has_gr"] = out["pre_n_gr"] > 0
    out["pre_price_change"] = pre_n(C.PRICE_CHANGE_ACTS) > 0
    out["pre_qty_change"] = pre_n(C.QTY_CHANGE_ACTS) > 0
    out["pre_duplicate_ir"] = out["pre_n_ir"] > 1
    out["pre_duplicate_gr"] = out["pre_n_gr"] > 1
    out["gr_ir_count_mismatch"] = ((out["pre_n_gr"] != out["pre_n_ir"])
                                   & ((out["pre_n_gr"] > 0) | (out["pre_n_ir"] > 0)))

    out["post_price_change"] = post_has(C.PRICE_CHANGE_ACTS)
    out["post_qty_change"] = post_has(C.QTY_CHANGE_ACTS)
    out["post_cancelled"] = post_has(C.CANCEL_ACTS)
    out["post_block_removed"] = post_has(C.UNBLOCK_ACTS)

    # ---- touchless rate input
    if C.USER_COL in df.columns:
        pat = "|".join(C.BATCH_USER_PATTERNS)
        u = df[[C.CASE_COL, C.USER_COL]]
        is_human = ~u[C.USER_COL].astype(str).str.contains(pat, case=False, na=False)
        out["human_touches"] = (u.assign(_h=is_human)
                                .groupby(C.CASE_COL, observed=True)["_h"].sum()
                                .reindex(idx).fillna(0).astype(int))
    else:
        out["human_touches"] = (out["was_blocked"] | out["po_price_changed"]
                                | out["po_qty_changed"] | out["cancelled"]).astype(int)

    if with_variants:
        out["variant"] = (slim.groupby(C.CASE_COL, observed=True, sort=False)[C.ACT_COL]
                          .apply(lambda s: " -> ".join(s.astype(str))).reindex(idx))

    return out.reset_index()
