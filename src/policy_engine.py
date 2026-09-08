"""
policy_engine.py — the control layer. NO LLM IN THIS FILE, BY DESIGN.

The single most defensible component in the project. The agent produces a
recommendation; this file decides whether that recommendation may execute.

Interview framing: this is functionally an SAP release strategy applied to a
non-human actor. SAP already solved authority for humans — value-band approvals,
release strategies, segregation of duties: a deterministic table of thresholds
and approvers configured OUTSIDE the transaction. The same control pattern,
applied to an agent.

The load-bearing principle: the agent can be completely confident and completely
correct and still not be permitted to act. Permission is a function of exception
class and transaction value, set outside the model. Confidence is not authority.
"""

from dataclasses import dataclass, asdict
from typing import Optional

import config as C
import labels as L

AUTO_RESOLVE = "AUTO_RESOLVE"
HUMAN_APPROVAL = "HUMAN_APPROVAL"
ESCALATE = "ESCALATE"

# ---------------------------------------------------------- decision-rights matrix
# Every row is policy, and every row needs a justification. This dict IS
# docs/decision_rights.md in executable form — they must not diverge.
#
# v1.0 is the pre-measurement policy. Stage 4 measures precision per class and
# demotes any class below the threshold, producing v1.1. That demotion is the
# project's primary interview story.
MATRIX_V1_0 = {
    L.NO_EXCEPTION: {
        "tier": AUTO_RESOLVE,
        "justification": "Three-way match passes. No exception to adjudicate.",
    },
    L.PRICE_WITHIN_TOL: {
        "tier": AUTO_RESOLVE,
        "justification": "Deterministic arithmetic against a configured tolerance key. "
                         "Near-zero error cost; an ERP already clears these.",
    },
    L.PRICE_OVER_TOL: {
        "tier": HUMAN_APPROVAL,
        "justification": "Variance beyond tolerance may reflect a contractual price "
                         "change. Clearing it without sign-off accepts a commercial "
                         "commitment the system cannot verify.",
    },
    L.QTY_VARIANCE: {
        "tier": HUMAN_APPROVAL,
        "justification": "Quantity variance implies a physical goods discrepancy. "
                         "Resolution requires warehouse confirmation outside the log.",
    },
    L.SEQUENCE_VIOLATION: {
        "tier": HUMAN_APPROVAL,
        "justification": "Invoice received before goods receipt breaks GR/IR "
                         "sequencing. A control breach, not an arithmetic error.",
    },
    L.DUPLICATE: {
        "tier": ESCALATE,
        "justification": "A false positive leaves a supplier unpaid and a false "
                         "negative pays twice. Both failure modes are expensive and "
                         "asymmetric; AP manager owns the call.",
    },
    L.MISSING_GR: {
        "tier": ESCALATE,
        "justification": "Absence of a goods receipt is a policy violation, not a "
                         "data problem. Owned by procurement, not AP.",
    },
}

ROUTING = {
    L.PRICE_OVER_TOL: "Procurement",
    L.QTY_VARIANCE: "Warehouse / Goods Receiving",
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
    stated_confidence: Optional[float]
    evidence_complete: bool
    policy_version: str
    near_miss: bool
    routed_to: Optional[str]
    reason: str
    counterfactual_check: str

    def to_dict(self):
        return asdict(self)


def decide(case_id, exception_class, exposure_eur, stated_confidence,
           evidence_complete, near_miss=False, matrix=None,
           policy_version=None) -> PolicyDecision:
    """
    Deterministic. Same inputs always produce the same decision, which is what
    makes the system auditable rather than merely explainable.

    Order of checks is the order of authority: value circuit-breakers outrank
    class permissions, class permissions outrank confidence, and confidence
    can only ever downgrade — never upgrade — an authority level.
    """
    matrix = matrix or MATRIX_V1_0
    policy_version = policy_version or C.POLICY_VERSION
    routed = ROUTING.get(exception_class)

    row = matrix.get(exception_class)
    if row is None:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              stated_confidence, evidence_complete, policy_version,
                              near_miss, routed or "AP Manager",
                              "Exception class outside delegated authority.",
                              "Not auto-resolved: class not present in the "
                              "decision-rights matrix.")

    base = row["tier"]

    # --- C1 hard value circuit breaker, outranks everything
    if exposure_eur is not None and exposure_eur > C.APPROVAL_VALUE_CAP:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              stated_confidence, evidence_complete, policy_version,
                              near_miss, routed or "Finance",
                              f"Exposure EUR {exposure_eur:,.0f} exceeds the escalation "
                              f"cap of EUR {C.APPROVAL_VALUE_CAP:,.0f}.",
                              "Not auto-resolved: value circuit breaker.")

    # --- C2 evidence completeness gate
    if not evidence_complete:
        return PolicyDecision(case_id, ESCALATE, exception_class, exposure_eur,
                              stated_confidence, evidence_complete, policy_version,
                              near_miss, routed or "AP Manager",
                              "Evidence incomplete or contradictory.",
                              "Not auto-resolved: the agent could not assemble a "
                              "complete evidence set.")

    if base == AUTO_RESOLVE:
        # --- C3 value cap on autonomous action
        if exposure_eur is not None and exposure_eur > C.AUTO_RESOLVE_VALUE_CAP:
            return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                                  stated_confidence, evidence_complete, policy_version,
                                  near_miss, routed,
                                  f"Class permits autonomy but exposure EUR "
                                  f"{exposure_eur:,.0f} exceeds the autonomous cap of "
                                  f"EUR {C.AUTO_RESOLVE_VALUE_CAP:,.0f}.",
                                  "Downgraded from AUTO_RESOLVE: value band.")
        # --- C4 confidence may only downgrade
        if stated_confidence is not None and stated_confidence < 0.80:
            return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                                  stated_confidence, evidence_complete, policy_version,
                                  near_miss, routed,
                                  f"Stated confidence {stated_confidence:.2f} below the "
                                  f"0.80 autonomous floor.",
                                  "Downgraded from AUTO_RESOLVE: low stated confidence.")
        # --- C5 near-miss cases sit close to a threshold boundary
        if near_miss:
            return PolicyDecision(case_id, HUMAN_APPROVAL, exception_class, exposure_eur,
                                  stated_confidence, evidence_complete, policy_version,
                                  near_miss, routed,
                                  "Case sits inside the near-miss band of a tolerance "
                                  "boundary.",
                                  "Downgraded from AUTO_RESOLVE: near-miss.")
        return PolicyDecision(case_id, AUTO_RESOLVE, exception_class, exposure_eur,
                              stated_confidence, evidence_complete, policy_version,
                              near_miss, None, row["justification"],
                              "Auto-resolved: class permitted, value within cap, "
                              "evidence complete, not near a boundary.")

    return PolicyDecision(case_id, base, exception_class, exposure_eur,
                          stated_confidence, evidence_complete, policy_version,
                          near_miss, routed, row["justification"],
                          f"Not auto-resolved: class tier is {base}.")


def demote(matrix, exception_class, to_tier=HUMAN_APPROVAL, reason=""):
    """
    Stage 4 produces v1.1 by calling this. Returns a NEW matrix — the v1.0
    object is never mutated, so before/after is reconstructible from the audit
    log rather than asserted.
    """
    new = {k: dict(v) for k, v in matrix.items()}
    if exception_class in new:
        new[exception_class]["tier"] = to_tier
        new[exception_class]["justification"] = (
            new[exception_class]["justification"] + f" DEMOTED v1.1: {reason}")
    return new


def matrix_to_markdown(matrix, version):
    lines = [f"# Decision-Rights Matrix — {version}", "",
             "| Exception class | Tier | Routed to | Justification |",
             "|---|---|---|---|"]
    for k, v in matrix.items():
        lines.append(f"| {k} | {v['tier']} | {ROUTING.get(k, '—')} | {v['justification']} |")
    lines += ["", "**Value bands (policy, not findings):**",
              f"- Autonomous action cap: EUR {C.AUTO_RESOLVE_VALUE_CAP:,.0f}",
              f"- Escalation cap: EUR {C.APPROVAL_VALUE_CAP:,.0f}",
              f"- Price tolerance: {C.PRICE_TOLERANCE_PCT}%",
              f"- Quantity tolerance: {C.QTY_TOLERANCE_PCT}%",
              f"- Near-miss band: ±{C.NEAR_MISS_BAND_PCT}pp of a threshold"]
    return "\n".join(lines)
