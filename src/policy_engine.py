"""Policy v1.2: ordered evidence checklist and decision table."""

from dataclasses import dataclass, asdict
import math
from typing import Optional

import config as C
if not hasattr(C, "APPROVAL_VALUE_CAP"):
    from src import config as C
import labels as L
import evidence as E

HUMAN_APPROVAL = "HUMAN_APPROVAL"
ESCALATE = "ESCALATE"
ESCALATE_CAP_EUR = C.APPROVAL_VALUE_CAP
POLICY_VERSION = "v1.3"

MATRIX_V1_3 = {
    L.NO_EXCEPTION: {"tier": HUMAN_APPROVAL, "justification": "No structural irregularity was identified; human disposition is still required."},
    L.PRIOR_AMENDMENT: {"tier": HUMAN_APPROVAL, "justification": "The purchase order was amended before invoicing."},
    L.GR_IR_MISMATCH: {"tier": HUMAN_APPROVAL, "justification": "Goods receipt and invoice receipt counts disagree."},
    L.SEQUENCE_VIOLATION: {"tier": HUMAN_APPROVAL, "justification": "Invoice arrived before any goods receipt."},
    L.DUPLICATE: {"tier": ESCALATE, "justification": "A repeated invoice-receipt pattern needs AP review."},
    L.MISSING_GR: {"tier": ESCALATE, "justification": "A goods receipt was expected and none exists."},
}

ROUTING = {
    L.NO_EXCEPTION: "AP Team",
    L.PRIOR_AMENDMENT: "Procurement",
    L.GR_IR_MISMATCH: "Warehouse / Goods Receiving",
    L.DUPLICATE: "AP Manager",
    L.MISSING_GR: "Procurement",
    L.SEQUENCE_VIOLATION: "AP Team Lead",
}


@dataclass
class PolicyDecision:
    case_id: str
    decision: str
    exception_class: str
    exposure_eur: Optional[float]
    evidence_complete: bool
    policy_version: str
    near_miss: bool
    routed_to: Optional[str]
    reason: str
    counterfactual_check: str
    evidence_level: str = E.INSUFFICIENT
    rule_fired: str = "R1"
    missing_sources: tuple = ()
    contradictions: tuple = ()

    def to_dict(self):
        return asdict(self)


def decide(case_id, exception_class, exposure_eur,
           evidence_level=E.INSUFFICIENT, near_miss=False, matrix=None,
           policy_version=None, missing_sources=(), contradictions=(),
           confidence=None, recommendation=None) -> PolicyDecision:
    """Apply policy v1.3; every non-escalated recommendation requires a human."""
    matrix = matrix or MATRIX_V1_3
    policy_version = policy_version or POLICY_VERSION
    row = matrix.get(exception_class)
    routed = ROUTING.get(exception_class)
    missing_sources = tuple(missing_sources)
    contradictions = tuple(contradictions)

    try:
        exposure_eur = float(exposure_eur)
    except (TypeError, ValueError):
        exposure_eur = None
    if exposure_eur is not None and not math.isfinite(exposure_eur):
        exposure_eur = None
    confidence = L.normalize_confidence(confidence)

    recommendations = {
        L.OUT_AUTO_CLEARED, L.OUT_PRICE_CORRECTION, L.OUT_QTY_CORRECTION,
        L.OUT_NO_CORRECTION, L.OUT_CANCELLED, L.OUT_UNRESOLVED,
    }

    # R1: missing/unknown evidence, value, or actionable recommendation escalates.
    if (evidence_level == E.INSUFFICIENT or exposure_eur is None
            or recommendation not in recommendations
            or recommendation == L.OUT_UNRESOLVED):
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              False, policy_version, near_miss,
                              routed or "AP Manager",
                              "Evidence, exposure, or agent recommendation is insufficient.",
                              "Escalated: R1 evidence, value, or recommendation gate.", evidence_level,
                              "R1", missing_sources, contradictions)
    # R2: the authoritative ERP value circuit breaker.
    if exposure_eur > ESCALATE_CAP_EUR:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "Finance",
                              "Transaction value exceeds the escalation cap.",
                              "Escalated: R2 ERP value circuit breaker.", evidence_level,
                              "R2", missing_sources, contradictions)
    # R3: a PO changed after invoice receipt is a control breach.
    if "PO_CHANGED_AFTER_INVOICE" in contradictions:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "The purchase order changed after invoice receipt.",
                              "Escalated: R3 post-invoice PO change requires investigation.", evidence_level,
                              "R3", missing_sources, contradictions)
    # R4: unknown classes and classes designated for escalation stay escalated.
    if row is None:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "Exception class is outside the taxonomy.",
                              "Escalated: R4 unknown taxonomy class.", evidence_level,
                              "R4", missing_sources, contradictions)
    if row["tier"] == ESCALATE:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "Exception class is designated for escalation.",
                              "Escalated: R4 class policy requires review.", evidence_level,
                              "R4", missing_sources, contradictions)
    # R5: weak evidence or non-strong model confidence requires human review.
    if evidence_level == E.WEAK or confidence != L.CONFIDENCE_STRONG:
        return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed,
                              "Evidence or agent confidence is not strong enough for autonomy.",
                              "Human approval required: R5 weak evidence or non-strong agent confidence.", evidence_level,
                              "R5", missing_sources, contradictions)
    # R6: a clean case must not receive a contradictory resolution proposal.
    if (exception_class == L.NO_EXCEPTION
            and recommendation != L.OUT_AUTO_CLEARED):
        return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "The recommendation conflicts with the clean-case evidence.",
                              "Human approval required: R6 recommendation mismatch.", evidence_level,
                              "R6", missing_sources, contradictions)
    # R7: no automated resolution is authorized by this policy version.
    return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                          True, policy_version, near_miss, routed or "AP Manager",
                          row["justification"],
                          "Human approval required: R7 automated resolution is not authorized.",
                          evidence_level, "R7", missing_sources, contradictions)


def matrix_to_markdown(matrix, version):
    lines = [f"# Decision Rights Matrix - {version}", "",
             "| Exception class | Tier | Routed to | Justification |", "|---|---|---|---|"]
    for key, value in matrix.items():
        lines.append(f"| {key} | {value['tier']} | {ROUTING.get(key, '—')} | {value['justification']} |")
    lines += ["", "**Value band (policy, not a finding):**",
              f"- Exposure above EUR {ESCALATE_CAP_EUR:,.0f} -> ESCALATE",
              "- All other non-escalated cases require HUMAN_APPROVAL; this policy authorizes no automatic resolution.", "",
              "**Ordered policy rules:**",
              "- R1: insufficient evidence, unknown ERP value, or unresolved recommendation -> ESCALATE",
              "- R2: ERP exposure above EUR 50,000 -> ESCALATE",
              "- R3: purchase order changed after invoice receipt -> ESCALATE",
              "- R4: unknown class or class designated for escalation -> ESCALATE",
              "- R5: weak evidence or non-strong model confidence -> HUMAN_APPROVAL",
              "- R6: recommendation conflicts with clean-case evidence -> HUMAN_APPROVAL",
              "- R7: all remaining cases -> HUMAN_APPROVAL"]
    return "\n".join(lines)
