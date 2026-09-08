"""
rules_engine.py — ARM A.

Pure if-then. No LLM. This models the deterministic automation an ERP already
performs: tolerance keys, GR/IR sequence checks, duplicate detection.

Why it exists: without it, any AI result is unfalsifiable. When an interviewer
asks "isn't this what SAP already does?", this file IS the answer — SAP's
existing automation is Arm A of the experiment, and the AI's contribution is
measured as incremental over it, not confounded with it.

Every rule returns three things:
    prediction  — the outcome label it predicts, or None
    confident   — whether the rule can settle the case at all
    trace       — which check fired, for the audit lineage

`confident=False` is not failure. It is the escalation signal that routes a case
to the agent, and the size of that residual is itself a Stage 2 finding.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List

import numpy as np

import config as C
import labels as L


@dataclass
class RuleResult:
    case_id: str
    prediction: Optional[str]
    confident: bool
    exception_class: str
    variance_pct: Optional[float]
    threshold_tested: Optional[float]
    near_miss: bool
    trace: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _near(value, threshold):
    if value is None or threshold is None or (isinstance(value, float) and np.isnan(value)):
        return False
    return abs(abs(value) - threshold) <= C.NEAR_MISS_BAND_PCT


def evaluate_case(row) -> RuleResult:
    trace = []
    absvar = row["abs_variance_pct"]
    absvar = None if (absvar is None or (isinstance(absvar, float) and np.isnan(absvar))) else float(absvar)
    cls = row["exception_class"]

    # ---- R1 duplicate pattern: control breach, deterministic detection,
    #      but resolution is not deterministic (a duplicate may be legitimate
    #      re-invoicing). Detect, do not decide.
    if row["duplicate_pattern"]:
        trace.append("R1 duplicate_pattern=True -> detected, not resolvable by rule")
        return RuleResult(row["case_id"], None, False, cls, absvar, None, False, trace)

    # ---- R2 sequence violation: GR/IR ordering breach
    if row["invoice_before_gr"]:
        trace.append("R2 invoice_before_gr=True -> sequence violation, not rule-resolvable")
        return RuleResult(row["case_id"], None, False, cls, absvar, None, False, trace)

    # ---- R3 missing goods receipt: policy violation, not a data problem
    if not row["has_gr"]:
        trace.append("R3 has_gr=False -> missing GR, escalation class")
        return RuleResult(row["case_id"], None, False, cls, absvar, None, False, trace)

    # ---- R4 no variance computable
    if absvar is None:
        trace.append("R4 variance not computable -> cannot settle")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    # ---- R5 within tolerance: the three-way match passes, no block expected
    if absvar <= C.PRICE_TOLERANCE_PCT:
        nm = _near(absvar, C.PRICE_TOLERANCE_PCT)
        trace.append(f"R5 |variance|={absvar:.3f}% <= tolerance {C.PRICE_TOLERANCE_PCT}% "
                     f"-> predict {L.OUT_AUTO_CLEARED}")
        if nm:
            trace.append("near_miss: within the boundary band")
        return RuleResult(row["case_id"], L.OUT_AUTO_CLEARED, True, cls,
                          absvar, C.PRICE_TOLERANCE_PCT, nm, trace)

    # ---- R6 over tolerance: a block is expected, but WHICH resolution path the
    #      company took is not deterministic. This is precisely the residual the
    #      agent is tested on.
    nm = _near(absvar, C.PRICE_TOLERANCE_PCT)
    trace.append(f"R6 |variance|={absvar:.3f}% > tolerance {C.PRICE_TOLERANCE_PCT}% "
                 f"-> block expected; resolution path not deterministic")
    return RuleResult(row["case_id"], None, False, cls, absvar,
                      C.PRICE_TOLERANCE_PCT, nm, trace)


def run(f):
    """Score every case. Returns a dataframe aligned to the case table."""
    import pandas as pd
    res = [evaluate_case(r) for _, r in f.iterrows()]
    return pd.DataFrame([r.to_dict() for r in res])
