"""Deterministic ERP evidence checklist for policy authority."""

from dataclasses import dataclass, asdict
import math

import labels as L

STRONG = "STRONG"
WEAK = "WEAK"
INSUFFICIENT = "INSUFFICIENT"

REQUIRED_TOOLS = {
    L.NO_EXCEPTION: {"get_invoice": True, "lookup_po": True,
                     "lookup_goods_receipt": True, "lookup_policy": True},
    L.PRIOR_AMENDMENT: {"get_invoice": True, "lookup_po": True,
                        "lookup_goods_receipt": True, "lookup_policy": True},
    L.GR_IR_MISMATCH: {"get_invoice": True, "lookup_po": True,
                       "lookup_goods_receipt": True, "lookup_policy": True},
    L.SEQUENCE_VIOLATION: {"get_invoice": True, "lookup_po": True,
                           "lookup_goods_receipt": False, "lookup_policy": True},
    L.DUPLICATE: {"get_invoice": True, "lookup_po": True,
                  "lookup_goods_receipt": True, "lookup_policy": True,
                  "check_duplicate_payment": True},
    L.MISSING_GR: {"get_invoice": True, "lookup_po": True,
                   "lookup_goods_receipt": False, "lookup_policy": True},
}


@dataclass
class EvidenceCheck:
    evidence_level: str
    missing_sources: list
    contradictions: list
    near_miss: bool

    def to_dict(self):
        return asdict(self)


def extract_facts(tool_results):
    """Map current tool fields to auditable yes/no contradiction facts."""
    def payload(name):
        result = tool_results.get(name) or {}
        records = result.get("records") if isinstance(result, dict) else None
        return (records[0] if records else result) or {}
    inv = payload("get_invoice")
    po = payload("lookup_po")
    gr = payload("lookup_goods_receipt")
    return {
        "invoice_before_gr": bool(
            inv.get("invoice_received_before_goods_receipt",
                    gr.get("invoice_before_goods_receipt", False))),
        "po_changed_after_invoice": bool(po.get("po_changed_after_invoice", False)),
        "gr_ir_count_mismatch": bool(po.get("gr_ir_count_mismatch", False)),
    }


def _satisfies(result, must_have_records):
    if not result or result.get("status") == "error" or result.get("error"):
        return False
    if must_have_records and not result.get("records"):
        return False
    return True


def exposure_contradictions(agent_exposure, erp_exposure):
    """Flag a finite model-reported value that differs from the ERP value."""
    try:
        agent_value = float(agent_exposure)
        erp_value = float(erp_exposure)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(agent_value) or not math.isfinite(erp_value):
        return []
    if round(agent_value, 2) != round(erp_value, 2):
        return ["AGENT_EXPOSURE_MISMATCH"]
    return []


def evaluate_evidence(exception_type, tool_results, near_miss=False,
                      additional_contradictions=()):
    """Return the deterministic evidence grade; confidence is a separate policy gate."""
    tool_results = tool_results or {}
    requirements = REQUIRED_TOOLS.get(exception_type, REQUIRED_TOOLS[L.NO_EXCEPTION])
    missing = [name for name, must_have_records in requirements.items()
               if not _satisfies(tool_results.get(name), must_have_records)]
    facts = extract_facts(tool_results)
    contradictions = []
    if facts["po_changed_after_invoice"]:
        contradictions.append("PO_CHANGED_AFTER_INVOICE")
    if facts["invoice_before_gr"] and exception_type != L.SEQUENCE_VIOLATION:
        contradictions.append("INVOICE_BEFORE_GR")
    if facts["gr_ir_count_mismatch"]:
        contradictions.append("GR_IR_QUANTITY_MISMATCH")
    contradictions.extend(c for c in additional_contradictions if c not in contradictions)

    if missing or len(contradictions) >= 2:
        level = INSUFFICIENT
    elif contradictions or near_miss:
        level = WEAK
    else:
        level = STRONG
    return EvidenceCheck(level, missing, contradictions, bool(near_miss)).to_dict()