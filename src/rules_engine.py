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
    return False   # no arithmetic tolerance is computable in this log


def evaluate_case(row) -> RuleResult:
    """
    Deterministic checks on PREFIX evidence only. Models the ERP's existing
    automation: a clean three-way match clears; anything structurally irregular
    stops and waits for a human. The size of that residual is the finding.
    """
    trace = []
    cls = row["exception_class"]

    if cls == L.DUPLICATE:
        trace.append("R1 repeated invoice receipt before anchor -> control breach, "
                     "detected but not resolvable by rule")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    if cls == L.SEQUENCE_VIOLATION:
        trace.append("R2 invoice receipt precedes goods receipt -> GR/IR sequencing "
                     "breach, not rule-resolvable")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    if cls == L.MISSING_GR:
        trace.append("R3 goods receipt expected but absent -> policy violation, "
                     "escalation class")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    if cls == L.GR_IR_MISMATCH:
        n_gr, n_ir = int(row["pre_n_gr"]), int(row["pre_n_ir"])
        trace.append(f"R4 goods receipts={n_gr} invoice receipts={n_ir} -> count "
                     f"mismatch; resolution path not deterministic")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    if cls == L.PRIOR_AMENDMENT:
        trace.append("R5 purchase order amended before the invoice arrived -> "
                     "commercial change, resolution path not deterministic")
        return RuleResult(row["case_id"], None, False, cls, None, None, False, trace)

    trace.append("R6 no structural irregularity in the prefix -> "
                 f"predict {L.OUT_AUTO_CLEARED}")
    return RuleResult(row["case_id"], L.OUT_AUTO_CLEARED, True, cls,
                      None, None, False, trace)


def run(f):
    """Score every case. Returns a dataframe aligned to the case table."""
    import pandas as pd
    res = [evaluate_case(r) for _, r in f.iterrows()]
    return pd.DataFrame([r.to_dict() for r in res])
