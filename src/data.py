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
import numpy as np
import pandas as pd

import config as C


# --------------------------------------------------------------------- loading
def load_log():
    """Return a flat event dataframe according to config.DATA_SOURCE."""
    if C.DATA_SOURCE == "synthetic":
        return make_synthetic_log()

    if os.path.exists(C.PARQUET_PATH):
        return pd.read_parquet(C.PARQUET_PATH)

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
def _first_by_act(df, acts, col):
    """Per-case first value of `col` restricted to `acts`. Vectorised."""
    m = df[df[C.ACT_COL].isin(acts)]
    if m.empty:
        return pd.Series(dtype="float64")
    return m.groupby(C.CASE_COL)[col].first()


def _has_act(df, acts, index):
    m = df[df[C.ACT_COL].isin(acts)]
    return index.isin(m[C.CASE_COL].unique())


def case_features(df, with_variants=False):
    """
    Collapse the event log to one row per case with the fields the rules engine,
    the agent tools and the label derivation all need.

    This is the single place that reads raw events. Everything downstream reads
    this table, so a schema correction in config propagates from one point.
    Fully vectorised — runs on 1.5M events in seconds, not minutes.
    """
    df = df.sort_values([C.CASE_COL, C.TS_COL])
    g = df.groupby(C.CASE_COL, sort=True)

    out = pd.DataFrame(index=g.size().index)
    out.index.name = "case_id"

    out["n_events"] = g.size()
    out["start_ts"] = g[C.TS_COL].first()
    out["end_ts"] = g[C.TS_COL].last()
    out["cycle_days"] = (out["end_ts"] - out["start_ts"]).dt.total_seconds() / 86400

    for col, name in [(C.VENDOR_COL, "vendor"), (C.ITEMTYPE_COL, "item_type"),
                      (C.SPEND_COL, "spend_area"), (C.DOCTYPE_COL, "doc_type")]:
        out[name] = g[col].first() if col in df.columns else None

    # --- document values, for the three-way match comparison
    out["po_value"] = _first_by_act(df, [C.A_CREATE_PO], C.VALUE_COL)
    out["gr_value"] = _first_by_act(df, C.GR_ACTS, C.VALUE_COL)
    inv = _first_by_act(df, [C.A_INVOICE_RECEIPT], C.VALUE_COL)
    inv_alt = _first_by_act(df, [C.A_VENDOR_INVOICE], C.VALUE_COL)
    out["invoice_value"] = inv.reindex(out.index).fillna(inv_alt.reindex(out.index))

    out["price_variance_pct"] = (out["invoice_value"] - out["po_value"]) / out["po_value"] * 100
    out["abs_variance_pct"] = out["price_variance_pct"].abs()
    out["exposure_eur"] = out["invoice_value"].fillna(out["po_value"])

    # --- sequence: goods receipt before invoice receipt (GR/IR ordering)
    gr_ts = _first_by_act(df, C.GR_ACTS, C.TS_COL).reindex(out.index)
    inv_ts = _first_by_act(df, [C.A_INVOICE_RECEIPT], C.TS_COL).reindex(out.index)
    out["invoice_before_gr"] = (inv_ts.notna() & gr_ts.notna() & (inv_ts < gr_ts))

    # --- payment block timing
    blk_ts = _first_by_act(df, C.BLOCK_ACTS, C.TS_COL).reindex(out.index)
    unblk_ts = _first_by_act(df, C.UNBLOCK_ACTS, C.TS_COL).reindex(out.index)
    # The block-set timestamp is almost never present, so anchor the resolution
    # clock on invoice receipt instead and name the metric for what it measures.
    anchor = blk_ts.fillna(inv_ts)
    out["block_to_resolution_days"] = (unblk_ts - blk_ts).dt.total_seconds() / 86400
    out["invoice_to_unblock_days"] = (unblk_ts - anchor).dt.total_seconds() / 86400

    # --- structural flags
    idx = out.index
    out["has_gr"] = _has_act(df, C.GR_ACTS, idx)

    # Was a goods receipt expected at all? Absence is only an exception if so.
    gr_col = getattr(C, "GR_EXPECTED_COL", None)
    if gr_col and gr_col in df.columns:
        exp = df.groupby(C.CASE_COL)[gr_col].first().reindex(out.index)
        out["gr_expected"] = exp.astype(str).str.lower().isin(["true", "1", "yes"])
        out["gr_expectation_source"] = gr_col
    else:
        cat_col = getattr(C, "ITEM_CATEGORY_COL", None)
        if cat_col and cat_col in df.columns:
            cat = df.groupby(C.CASE_COL)[cat_col].first().reindex(out.index).astype(str)
            pat = "|".join(getattr(C, "NO_GR_ITEM_CATEGORIES", []))
            out["gr_expected"] = ~cat.str.contains(pat, case=False, na=False)
            out["gr_expectation_source"] = cat_col
        else:
            out["gr_expected"] = True
            out["gr_expectation_source"] = "assumed_true_no_field_available"
    _set_block = _has_act(df, C.BLOCK_ACTS, idx)
    _removed = _has_act(df, C.UNBLOCK_ACTS, idx)
    out["was_blocked"] = ((_set_block | _removed)
                          if getattr(C, "BLOCK_INFERRED_FROM_REMOVAL", False)
                          else _set_block)
    out["block_set_event_present"] = _set_block
    out["block_removed"] = _has_act(df, C.UNBLOCK_ACTS, idx)
    out["po_price_changed"] = _has_act(df, C.PRICE_CHANGE_ACTS, idx)
    out["po_qty_changed"] = _has_act(df, C.QTY_CHANGE_ACTS, idx)
    out["cancelled"] = _has_act(df, C.CANCEL_ACTS, idx)
    out["cleared"] = _has_act(df, [C.A_CLEAR_INVOICE], idx)

    # Terminal state: the case reached an observable end. Non-terminal cases have
    # no resolution to predict and are excluded from evaluation, not relabelled.
    out["terminal"] = (out["cleared"] | out["block_removed"]
                       | _has_act(df, C.CANCEL_ACTS, idx))

    ir = df[df[C.ACT_COL] == C.A_INVOICE_RECEIPT].groupby(C.CASE_COL).size()
    out["n_invoice_receipts"] = ir.reindex(out.index).fillna(0).astype(int)
    out["duplicate_pattern"] = out["n_invoice_receipts"] > 1

    # --- touchless rate input: events performed by non-batch users
    if C.USER_COL in df.columns:
        pat = "|".join(C.BATCH_USER_PATTERNS)
        is_human = ~df[C.USER_COL].astype(str).str.contains(pat, case=False, na=False)
        out["human_touches"] = (df.assign(_h=is_human).groupby(C.CASE_COL)["_h"]
                                .sum().reindex(out.index).fillna(0).astype(int))
    else:
        # No user field: touchless rate is redefined structurally.
        # Documented in docs/metric_definitions.md as a fallback definition.
        out["human_touches"] = (out["was_blocked"] | out["po_price_changed"]
                                | out["po_qty_changed"] | out["cancelled"]).astype(int)

    # The variant string is a groupby-apply over every event and costs minutes on
    # the full log. Stage 1 needs it; nothing else does. Off by default.
    if with_variants:
        out["variant"] = g[C.ACT_COL].apply(lambda s: " -> ".join(s))

    return out.reset_index()
