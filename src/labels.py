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
NO_EXCEPTION = "NO_EXCEPTION"
PRICE_WITHIN_TOL = "PRICE_VARIANCE_WITHIN_TOLERANCE"
PRICE_OVER_TOL = "PRICE_VARIANCE_OVER_TOLERANCE"
QTY_VARIANCE = "QUANTITY_VARIANCE"
SEQUENCE_VIOLATION = "SEQUENCE_VIOLATION_INVOICE_BEFORE_GR"
DUPLICATE = "DUPLICATE_INVOICE_PATTERN"
MISSING_GR = "MISSING_GOODS_RECEIPT"

# ------------------------------------------------------- historical outcome labels
OUT_AUTO_CLEARED = "CLEARED_WITHOUT_BLOCK"
OUT_PO_CORRECTION = "RESOLVED_WITH_OBSERVED_PO_CORRECTION"
OUT_NO_PO_CORRECTION = "RESOLVED_WITHOUT_OBSERVED_PO_CORRECTION"
OUT_CANCELLED = "INVOICE_CANCELLED"
OUT_UNRESOLVED = "UNRESOLVED_IN_LOG"


def classify_exception(f: pd.DataFrame) -> pd.Series:
    """
    Assign one exception class per case. Order matters: the first matching
    condition wins, most-specific first. Ordering rationale is documented in
    docs/exception_taxonomy.md and is a defensible design choice, not an
    arbitrary one — duplicates and sequence violations are control breaches,
    so they outrank an arithmetic variance on the same case.
    """
    cls = pd.Series(NO_EXCEPTION, index=f.index, dtype=object)
    absvar = f["abs_variance_pct"]

    # least specific first, overwritten by later rules
    cls[absvar.notna() & (absvar <= C.PRICE_TOLERANCE_PCT) & (absvar > 0.001)] = PRICE_WITHIN_TOL
    cls[absvar.notna() & (absvar > C.PRICE_TOLERANCE_PCT)] = PRICE_OVER_TOL
    cls[f["po_qty_changed"] & absvar.notna() & (absvar > C.QTY_TOLERANCE_PCT)] = QTY_VARIANCE
    cls[~f["has_gr"]] = MISSING_GR
    cls[f["invoice_before_gr"]] = SEQUENCE_VIOLATION
    cls[f["duplicate_pattern"]] = DUPLICATE
    return cls


def derive_outcome(f: pd.DataFrame) -> pd.Series:
    """
    What the company historically did. Derived only from downstream events.

    RESOLVED_WITHOUT_OBSERVED_PO_CORRECTION records the ABSENCE of an amendment
    event. It does not mean the invoice was correct and it does not assign fault
    — that distinction is the reason for the wording, and it is the wording used
    in the deck.
    """
    lab = pd.Series(OUT_UNRESOLVED, index=f.index, dtype=object)

    lab[~f["was_blocked"] & f["cleared"]] = OUT_AUTO_CLEARED

    blocked = f["was_blocked"]
    corrected = f["po_price_changed"] | f["po_qty_changed"]
    lab[blocked & f["block_removed"] & corrected] = OUT_PO_CORRECTION
    lab[blocked & f["block_removed"] & ~corrected] = OUT_NO_PO_CORRECTION
    lab[f["cancelled"]] = OUT_CANCELLED
    return lab


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


def build(f: pd.DataFrame, df_events: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    f["exception_class"] = classify_exception(f)
    f["outcome_label"] = derive_outcome(f)
    return f
