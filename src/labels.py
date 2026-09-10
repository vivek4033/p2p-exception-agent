"""
labels.py — exception taxonomy and outcome label derivation.

Two separate jobs, deliberately kept apart:

  classify_exception()  — what KIND of exception this case is (the input)
  derive_outcome()      — what the company HISTORICALLY DID about it (the target)

Language discipline (guardrail 11): the target is the historically observed
outcome. It is not ground truth. The log records that a clerk removed a payment
block; it does not record whether they should have. The disagreement analysis in
Stage 4 sizes that gap; nothing here closes it.

Guardrail 12: taxonomy classes are derived from activity and value evidence
present in the log. If Stage 0 shows an activity this file references does not
exist, the corresponding class silently returns zero cases and audit_taxonomy()
reports it — it does not fabricate.
"""

import numpy as np
import pandas as pd

import config as C

# ---------------------------------------------------------------- exception classes
# Derived from ACTIVITY PATTERNS visible in the prefix — the evidence a clerk
# has at the moment the invoice arrives. Not from computed price variance:
# Cumulative net worth (EUR) is constant within a case in this log, so no
# arithmetic three-way match is possible. Guardrail 12 — the data decided this.
NO_EXCEPTION = "NO_EXCEPTION"
MISSING_GR = "MISSING_GOODS_RECEIPT"
SEQUENCE_VIOLATION = "SEQUENCE_VIOLATION_INVOICE_BEFORE_GR"
DUPLICATE = "DUPLICATE_INVOICE_RECEIPT_PATTERN"
GR_IR_MISMATCH = "GR_IR_COUNT_MISMATCH"
PRIOR_AMENDMENT = "PRIOR_PO_AMENDMENT"

# ------------------------------------------------- historically observed outcomes
# Derived from the SUFFIX only — what happened after the invoice landed.
OUT_AUTO_CLEARED = "CLEARED_WITHOUT_BLOCK"
OUT_PRICE_CORRECTION = "RESOLVED_WITH_PRICE_CORRECTION"
OUT_QTY_CORRECTION = "RESOLVED_WITH_QUANTITY_CORRECTION"
OUT_NO_CORRECTION = "RESOLVED_WITHOUT_OBSERVED_CORRECTION"
OUT_CANCELLED = "INVOICE_CANCELLED"
OUT_UNRESOLVED = "UNRESOLVED_IN_LOG"

# retained so older references do not break
OUT_PO_CORRECTION = OUT_PRICE_CORRECTION
OUT_NO_PO_CORRECTION = OUT_NO_CORRECTION
PRICE_WITHIN_TOL = NO_EXCEPTION
PRICE_OVER_TOL = PRIOR_AMENDMENT
QTY_VARIANCE = GR_IR_MISMATCH


def classify_exception(f: pd.DataFrame) -> pd.Series:
    """
    PREFIX ONLY. Every field read here must have existed at the anchor moment.
    Reading a suffix field would make the feature the target.

    Order: least specific first, overwritten by more specific. Control breaches
    (duplicates, sequence) outrank counting mismatches on the same case.
    """
    cls = pd.Series(NO_EXCEPTION, index=f.index, dtype=object)
    cls[f["pre_price_change"] | f["pre_qty_change"]] = PRIOR_AMENDMENT
    cls[f["gr_ir_count_mismatch"]] = GR_IR_MISMATCH
    cls[f["gr_expected"] & ~f["pre_has_gr"]] = MISSING_GR
    cls[f["invoice_before_gr"]] = SEQUENCE_VIOLATION
    cls[f["pre_duplicate_ir"]] = DUPLICATE
    return cls


def derive_outcome(f: pd.DataFrame) -> pd.Series:
    """
    SUFFIX ONLY. What the company historically did after the invoice arrived.

    RESOLVED_WITHOUT_OBSERVED_CORRECTION records the ABSENCE of an amendment
    event. It does not mean the invoice was correct and it assigns no fault.
    """
    lab = pd.Series(OUT_UNRESOLVED, index=f.index, dtype=object)
    lab[~f["was_blocked"] & f["cleared"]] = OUT_AUTO_CLEARED

    resolved = f["was_blocked"] & f["block_removed"]
    lab[resolved] = OUT_NO_CORRECTION
    lab[resolved & f["post_qty_change"]] = OUT_QTY_CORRECTION
    lab[resolved & f["post_price_change"]] = OUT_PRICE_CORRECTION
    lab[f["post_cancelled"] | f["cancelled"]] = OUT_CANCELLED
    return lab


def leakage_check(f: pd.DataFrame) -> dict:
    """
    Guards the split. Any exception class that maps almost perfectly onto one
    outcome label is leakage, and the number would be meaningless.
    """
    ct = pd.crosstab(f["exception_class"], f["outcome_label"], normalize="index")
    worst = ct.max(axis=1).sort_values(ascending=False)
    return {
        "max_class_to_label_concentration": round(float(worst.iloc[0]), 4),
        "class": worst.index[0],
        "leak_suspected": bool(worst.iloc[0] > 0.98),
        "note": "a class resolving to one label >98% of the time indicates the "
                "feature and the target are the same event",
    }


def analysis_population(f: pd.DataFrame):
    """
    Split the case table into the evaluable population and the stated exclusion.
    Returns (population, exclusion_report). Losing coverage is survivable;
    losing label integrity is not.
    """
    if not getattr(C, "EXCLUDE_NON_TERMINAL_CASES", False):
        return f, {"excluded": 0, "rule": "no exclusion applied"}
    keep = f[f["terminal"]]
    return keep, {
        "total_cases": int(len(f)),
        "evaluable_cases": int(len(keep)),
        "excluded_non_terminal": int((~f["terminal"]).sum()),
        "excluded_pct": round(100 * (~f["terminal"]).mean(), 2),
        "rule": "excluded: no Clear Invoice, no Remove Payment Block and no "
                "Cancel Invoice Receipt in the extract — in flight, deleted, or "
                "terminating outside this log. No resolution exists to predict.",
    }


def label_coverage_report(f: pd.DataFrame) -> dict:
    """
    Stage 1 decision gate. If derivable coverage is low on blocked cases, the
    scope narrows to the classes where labels ARE derivable and the exclusion is
    stated. Never invent a proxy label to preserve coverage.
    """
    blocked = f[f["was_blocked"]]
    derivable = blocked["outcome_label"] != OUT_UNRESOLVED
    return {
        "n_cases": int(len(f)),
        "n_blocked": int(len(blocked)),
        "blocked_pct": round(100 * len(blocked) / max(len(f), 1), 2),
        "derivable_on_blocked_pct": round(100 * derivable.mean(), 2) if len(blocked) else 0.0,
        "gate_passed": bool(len(blocked) and derivable.mean() >= 0.60),
        "gate_rule": "proceed if >=60% of blocked cases carry a derivable outcome; "
                     "otherwise narrow scope to derivable classes and state the exclusion",
    }


def audit_taxonomy(df_events: pd.DataFrame) -> dict:
    """
    Guardrail 12 enforcement. Reports which configured activity names are absent
    from the log so a class can never be silently built on an activity that does
    not exist.
    """
    present = set(df_events[C.ACT_COL].unique())
    configured = {
        "A_CREATE_PO": C.A_CREATE_PO, "A_GOODS_RECEIPT": C.A_GOODS_RECEIPT,
        "A_VENDOR_INVOICE": C.A_VENDOR_INVOICE, "A_INVOICE_RECEIPT": C.A_INVOICE_RECEIPT,
        "A_CLEAR_INVOICE": C.A_CLEAR_INVOICE, "A_REMOVE_BLOCK": C.A_REMOVE_BLOCK,
        "A_SET_BLOCK": C.A_SET_BLOCK, "A_CHANGE_PRICE": C.A_CHANGE_PRICE,
        "A_CHANGE_QUANTITY": C.A_CHANGE_QUANTITY, "A_CANCEL_INVOICE": C.A_CANCEL_INVOICE,
    }
    missing = {k: v for k, v in configured.items() if v not in present}
    return {
        "activities_in_log": len(present),
        "configured_not_found": missing,
        "action_required": ("Correct these names in src/config.py from the Stage 0 "
                            "activity inventory before trusting any class counts."
                            if missing else "All configured activities present."),
    }


def audit_taxonomy_names(present) -> dict:
    """Audit configured activities from a streaming set of activity names."""
    configured = {
        "A_CREATE_PO": C.A_CREATE_PO, "A_GOODS_RECEIPT": C.A_GOODS_RECEIPT,
        "A_VENDOR_INVOICE": C.A_VENDOR_INVOICE, "A_INVOICE_RECEIPT": C.A_INVOICE_RECEIPT,
        "A_CLEAR_INVOICE": C.A_CLEAR_INVOICE, "A_REMOVE_BLOCK": C.A_REMOVE_BLOCK,
        "A_SET_BLOCK": C.A_SET_BLOCK, "A_CHANGE_PRICE": C.A_CHANGE_PRICE,
        "A_CHANGE_QUANTITY": C.A_CHANGE_QUANTITY, "A_CANCEL_INVOICE": C.A_CANCEL_INVOICE,
    }
    missing = {k: v for k, v in configured.items() if v not in present}
    return {
        "activities_in_log": len(present),
        "configured_not_found": missing,
        "action_required": ("Correct these names in src/config.py from the Stage 0 "
                            "activity inventory before trusting any class counts."
                            if missing else "All configured activities present."),
    }


def build(f: pd.DataFrame, df_events: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["exception_class"] = classify_exception(f)
    f["outcome_label"] = derive_outcome(f)
    return f
