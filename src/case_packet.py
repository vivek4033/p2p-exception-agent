"""
case_packet.py — the dossier a human receives.

The point of the packet: the human's job becomes DECIDING, not INVESTIGATING.
It states what was checked, what was found, what is missing, what is
recommended, why it was not auto-resolved, and what action is required.

Counterparty notification is prepared here and never sent autonomously.

The no-fault rule, enforced in the wording:
    The log records that an invoice and a goods receipt disagree. It does not
    record who caused the disagreement. The supplier may have mis-billed, the
    warehouse may have mis-counted, or the PO may have been amended after the
    invoice was issued. The packet states the discrepancy and its direction and
    names who owns the next action. It does not assign fault.

This is why the draft is a draft. An agent that autonomously tells a supplier
they underdelivered is asserting a conclusion the evidence does not support, and
doing it at scale against real commercial relationships.
"""

import config as C
import labels as L
import policy_engine as P

# who the discrepancy is raised WITH, once a human has decided to raise it
COUNTERPARTY = {
    L.PRICE_OVER_TOL: ("Supplier", "Price billed differs from the agreed PO price."),
    L.QTY_VARIANCE: ("Supplier / Goods Receiving",
                     "Quantity billed differs from the quantity recorded as received."),
    L.DUPLICATE: ("Supplier", "A repeated invoice-receipt pattern was detected on this line."),
    L.SEQUENCE_VIOLATION: ("Internal — Goods Receiving",
                           "Invoice arrived before any goods receipt was recorded."),
    L.MISSING_GR: ("Internal — Procurement",
                   "No goods receipt exists against this line item."),
}


def direction(variance_pct):
    """Which way the discrepancy runs. Descriptive, never accusatory."""
    if variance_pct is None:
        return "undetermined"
    if variance_pct > 0:
        return "invoice exceeds purchase order value"
    if variance_pct < 0:
        return "invoice is below purchase order value"
    return "no variance"


def build(case_row, agent_result, policy_decision, rule_trace=None):
    """Returns a dict; render_text() turns it into the human-readable dossier."""
    cls = agent_result.get("exception_type") or case_row["exception_class"]
    var = case_row.get("price_variance_pct")
    var = None if var is None or var != var else float(var)   # NaN-safe
    party, basis = COUNTERPARTY.get(cls, (None, None))

    packet = {
        "case_id": case_row["case_id"],
        "exception_class": cls,
        "exposure_eur": case_row.get("exposure_eur"),
        "po_value_eur": case_row.get("po_value"),
        "invoice_value_eur": case_row.get("invoice_value"),
        "variance_pct": round(var, 3) if var is not None else None,
        "variance_direction": direction(var),
        "tolerance_applied_pct": C.PRICE_TOLERANCE_PCT,
        "checks_performed": rule_trace or [],
        "tools_called": agent_result.get("_tools", []),
        "evidence": agent_result.get("evidence", []),
        "recommendation": agent_result.get("recommendation"),
        "stated_confidence": agent_result.get("confidence"),
        "evidence_complete": agent_result.get("evidence_complete"),
        "decision": policy_decision.decision,
        "why_not_auto_resolved": (policy_decision.counterfactual_check
                                  if policy_decision.decision != P.AUTO_RESOLVE else None),
        "policy_version": policy_decision.policy_version,
        "near_miss": policy_decision.near_miss,
        "internal_owner": policy_decision.routed_to,
        "counterparty": party,
        "counterparty_basis": basis,
        "action_required": _action(policy_decision),
        "fault_attribution": "NOT DETERMINED — the log records the discrepancy, "
                             "not its cause. Fault is a human judgment.",
    }
    packet["draft_notification"] = _draft(packet) if party else None
    return packet


def _action(pd_):
    if pd_.decision == P.AUTO_RESOLVE:
        return "None. Resolved under delegated authority; recorded in the audit log."
    if pd_.decision == P.HUMAN_APPROVAL:
        return f"Review the recommendation and approve or reject. Owner: {pd_.routed_to}."
    return f"Investigate and decide. Escalated to: {pd_.routed_to}."


def _draft(p):
    """
    Draft only. Never sent by the agent. Deliberately states the observation and
    requests confirmation — it does not allege an error.
    """
    lines = [
        f"Subject: Query on invoice for PO line {p['case_id']}",
        "",
        "Hello,",
        "",
        f"Our records show a discrepancy on this line item: {p['variance_direction']}.",
    ]
    if p["po_value_eur"] and p["invoice_value_eur"]:
        lines.append(f"Purchase order value EUR {p['po_value_eur']:,.2f}; "
                     f"invoiced value EUR {p['invoice_value_eur']:,.2f}"
                     + (f" ({p['variance_pct']:+.2f}%)." if p['variance_pct'] is not None else "."))
    lines += [
        f"This sits outside our agreed tolerance of {p['tolerance_applied_pct']}%, "
        f"so payment is currently held pending confirmation.",
        "",
        "We have not concluded that either party is in error. Could you confirm the "
        "basis for the invoiced amount so we can reconcile it against the purchase "
        "order and goods receipt?",
        "",
        "Regards,",
        "Accounts Payable",
        "",
        "[DRAFT — requires human review and release before sending]",
    ]
    return "\n".join(lines)


def render_text(p):
    L_ = []
    A = L_.append
    A(f"CASE PACKET — {p['case_id']}")
    A("=" * 60)
    A(f"Exception class     : {p['exception_class']}")
    A(f"Exposure            : EUR {p['exposure_eur']:,.2f}" if p['exposure_eur'] else "Exposure: n/a")
    A(f"PO / Invoice        : EUR {p['po_value_eur']:,.2f} vs EUR {p['invoice_value_eur']:,.2f}"
      if p['po_value_eur'] and p['invoice_value_eur'] else "PO / Invoice: incomplete")
    A(f"Variance            : {p['variance_pct']}% ({p['variance_direction']})")
    A(f"Tolerance applied   : {p['tolerance_applied_pct']}%")
    A("")
    A("WHAT WAS CHECKED")
    for t in p["checks_performed"]:
        A(f"  - {t}")
    A(f"  - tools called: {', '.join(p['tools_called']) or 'none'}")
    A("")
    A("WHAT WAS FOUND")
    for e in p["evidence"]:
        A(f"  - {e}")
    A("")
    A(f"RECOMMENDATION      : {p['recommendation']}  (confidence {p['stated_confidence']})")
    A(f"POLICY DECISION     : {p['decision']}  (policy {p['policy_version']})")
    if p["why_not_auto_resolved"]:
        A(f"WHY NOT AUTONOMOUS  : {p['why_not_auto_resolved']}")
    if p["near_miss"]:
        A("NEAR MISS           : sits inside the boundary band of a tolerance threshold")
    A("")
    A(f"INTERNAL OWNER      : {p['internal_owner'] or '—'}")
    A(f"COUNTERPARTY        : {p['counterparty'] or '—'}")
    if p["counterparty_basis"]:
        A(f"BASIS               : {p['counterparty_basis']}")
    A(f"FAULT               : {p['fault_attribution']}")
    A("")
    A(f"ACTION REQUIRED     : {p['action_required']}")
    if p["draft_notification"]:
        A("")
        A("DRAFT COUNTERPARTY NOTIFICATION (not sent)")
        A("-" * 60)
        A(p["draft_notification"])
    return "\n".join(L_)
