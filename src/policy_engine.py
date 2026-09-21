"""Policy v1.2: ordered evidence checklist and decision table."""

from dataclasses import dataclass, asdict
from typing import Optional

import config as C
import labels as L
import evidence as E

AUTO_RESOLVE = "AUTO_RESOLVE"
HUMAN_APPROVAL = "HUMAN_APPROVAL"
ESCALATE = "ESCALATE"
AUTO_CAP_EUR = 5_000
ESCALATE_CAP_EUR = 50_000
POLICY_VERSION = "v1.2"

MATRIX_V1_0 = {
    L.NO_EXCEPTION: {"tier": AUTO_RESOLVE, "justification": "No structural irregularity in the ERP evidence."},
    L.PRIOR_AMENDMENT: {"tier": HUMAN_APPROVAL, "justification": "The purchase order was amended before invoicing."},
    L.GR_IR_MISMATCH: {"tier": HUMAN_APPROVAL, "justification": "Goods receipt and invoice receipt counts disagree."},
    L.SEQUENCE_VIOLATION: {"tier": HUMAN_APPROVAL, "justification": "Invoice arrived before any goods receipt."},
    L.DUPLICATE: {"tier": ESCALATE, "justification": "A repeated invoice-receipt pattern needs AP review."},
    L.MISSING_GR: {"tier": ESCALATE, "justification": "A goods receipt was expected and none exists."},
}

ROUTING = {
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
           policy_version=None, missing_sources=(), contradictions=()) -> PolicyDecision:
    """Apply strict-first rules R1-R6 using evidence, class, and value facts."""
    matrix = matrix or MATRIX_V1_0
    policy_version = policy_version or POLICY_VERSION
    row = matrix.get(exception_class)
    routed = ROUTING.get(exception_class)
    missing_sources = tuple(missing_sources)
    contradictions = tuple(contradictions)

    # R1: missing/unknown evidence or value always escalates.
    if evidence_level == E.INSUFFICIENT or exposure_eur is None:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              False, policy_version, near_miss,
                              routed or "AP Manager", "Evidence is insufficient.",
                              "Not auto-resolved: R1 evidence or value gate.", evidence_level,
                              "R1", missing_sources, contradictions)
    # R2: value circuit breaker outranks class routing.
    if exposure_eur > ESCALATE_CAP_EUR:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "Finance",
                              "Transaction value exceeds the escalation cap.",
                              "Not auto-resolved: R2 value circuit breaker.", evidence_level,
                              "R2", missing_sources, contradictions)
    # R3: class must be explicitly permitted for autonomy.
    if row is None:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "Exception class is outside the taxonomy.",
                              "Not auto-resolved: R3 unknown taxonomy class.", evidence_level,
                              "R3", missing_sources, contradictions)
    if row["tier"] != AUTO_RESOLVE:
        tier = row["tier"]
        return PolicyDecision(case_id, tier, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed or "AP Manager",
                              "Exception class is outside delegated authority.",
                              f"Not auto-resolved: R3 class tier is {tier}.", evidence_level,
                              "R3", missing_sources, contradictions)
    # R4: autonomy is limited to the lower value band.
    if exposure_eur > AUTO_CAP_EUR:
        return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed,
                              "Exposure exceeds the autonomous action cap.",
                              "Not auto-resolved: R4 autonomous value band.", evidence_level,
                              "R4", missing_sources, contradictions)
    # R5: complete but weak evidence requires human approval.
    if evidence_level == E.WEAK:
        return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                              True, policy_version, near_miss, routed,
                              "Evidence is present but contradictory or near a boundary.",
                              "Not auto-resolved: R5 weak evidence.", evidence_level,
                              "R5", missing_sources, contradictions)
    # R6: all gates passed.
    return PolicyDecision(case_id, AUTO_RESOLVE, exception_class, exposure_eur,
                          True, policy_version, near_miss, None,
                          row["justification"],
                          "Auto-resolved: R6 strong evidence, permitted class, and value within cap.",
                          evidence_level, "R6", missing_sources, contradictions)


def demote(matrix, exception_class, to_tier=HUMAN_APPROVAL, reason=""):
    new = {k: dict(v) for k, v in matrix.items()}
    if exception_class in new:
        new[exception_class]["tier"] = to_tier
        new[exception_class]["justification"] += f" DEMOTED v1.1: {reason}"
    return new


def matrix_to_markdown(matrix, version):
    lines = [f"# Decision-Rights Matrix — {version}", "",
             "| Exception class | Tier | Routed to | Justification |", "|---|---|---|---|"]
    for key, value in matrix.items():
        lines.append(f"| {key} | {value['tier']} | {ROUTING.get(key, '—')} | {value['justification']} |")
    lines += ["", "**Value bands (policy, not findings):**",
              f"- Autonomous action cap: EUR {AUTO_CAP_EUR:,.0f}",
              f"- Escalation cap: EUR {ESCALATE_CAP_EUR:,.0f}", "",
              "**Ordered policy rules:**",
              "- R1: insufficient evidence or unknown value -> ESCALATE",
              "- R2: value above EUR 50,000 -> ESCALATE",
              "- R3: class not auto-permitted -> matrix outcome",
              "- R4: value above EUR 5,000 -> HUMAN_APPROVAL",
              "- R5: weak evidence -> HUMAN_APPROVAL",
              "- R6: all checks pass -> AUTO_RESOLVE"]
    return "\n".join(lines)
