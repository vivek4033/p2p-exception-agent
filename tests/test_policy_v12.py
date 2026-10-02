import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import evidence
import labels
import policy_engine


FULL = {
    "get_invoice": {"status": "ok", "records": [{"invoice_received_before_goods_receipt": False}]},
    "lookup_po": {"status": "ok", "records": [{"gr_ir_count_mismatch": False, "po_changed_after_invoice": False}]},
    "lookup_goods_receipt": {"status": "ok", "records": [{"goods_receipt_recorded": True}]},
    "lookup_policy": {"status": "ok", "records": [{"price_tolerance_pct": 2.0}]},
}


def _decide(*args, **kwargs):
    kwargs.setdefault("confidence", "STRONG")
    kwargs.setdefault("recommendation", labels.OUT_AUTO_CLEARED)
    return policy_engine.decide(*args, **kwargs)


def test_strong_complete_consistent():
    assert evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)["evidence_level"] == evidence.STRONG


def test_weak_near_miss():
    assert evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL, True)["evidence_level"] == evidence.WEAK


def test_weak_one_contradiction():
    tools = {**FULL, "lookup_po": {"status": "ok", "records": [{"po_changed_after_invoice": True}]}}
    result = evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)
    assert result["evidence_level"] == evidence.WEAK
    assert result["contradictions"] == ["PO_CHANGED_AFTER_INVOICE"]


def test_insufficient_missing_source():
    tools = dict(FULL)
    del tools["lookup_goods_receipt"]
    result = evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)
    assert result["evidence_level"] == evidence.INSUFFICIENT


def test_insufficient_two_contradictions():
    tools = {**FULL,
             "get_invoice": {"status": "ok", "records": [{"invoice_received_before_goods_receipt": True}]},
             "lookup_po": {"status": "ok", "records": [{"po_changed_after_invoice": True}]}}
    result = evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)
    assert result["evidence_level"] == evidence.INSUFFICIENT


def test_sequence_definition_is_not_contradiction():
    tools = {**FULL,
             "get_invoice": {"status": "ok", "records": [{"invoice_received_before_goods_receipt": True}]},
             "lookup_goods_receipt": {"status": "ok", "records": []}}
    result = evidence.evaluate_evidence(labels.SEQUENCE_VIOLATION, tools)
    assert result["contradictions"] == []
    assert result["missing_sources"] == []


def test_price_case_empty_goods_receipt_is_insufficient():
    tools = {**FULL, "lookup_goods_receipt": {"status": "ok", "records": []}}
    result = evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)
    assert "lookup_goods_receipt" in result["missing_sources"]
    assert result["evidence_level"] == evidence.INSUFFICIENT


def test_tool_error_is_insufficient():
    tools = {**FULL, "lookup_po": {"status": "error", "records": [], "error": "failed"}}
    assert evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)["evidence_level"] == evidence.INSUFFICIENT


def test_required_tool_not_called_is_insufficient():
    tools = dict(FULL)
    del tools["lookup_policy"]
    assert evidence.evaluate_evidence(labels.NO_EXCEPTION, tools)["evidence_level"] == evidence.INSUFFICIENT


def test_strong_agent_confidence_can_pass_policy_gates():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                                    strong["evidence_level"],
                                    confidence="STRONG",
                                    recommendation=labels.OUT_AUTO_CLEARED,
                                    missing_sources=strong["missing_sources"],
                                    contradictions=strong["contradictions"])
    assert decision.rule_fired == "R6"
    assert decision.decision == policy_engine.AUTO_RESOLVE


def test_non_clear_recommendation_for_no_exception_requires_human_approval():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                       strong["evidence_level"], confidence="STRONG",
                       recommendation=labels.OUT_CANCELLED)
    assert decision.rule_fired == "R5"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_intermediate_agent_confidence_requires_human_approval():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                                    strong["evidence_level"],
                                    confidence="INTERMEDIATE",
                                    recommendation=labels.OUT_AUTO_CLEARED)
    assert decision.rule_fired == "R5"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_weak_agent_confidence_requires_human_approval():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                                    strong["evidence_level"],
                                    confidence="WEAK",
                                    recommendation=labels.OUT_AUTO_CLEARED)
    assert decision.rule_fired == "R5"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_unresolved_agent_recommendation_escalates():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                                    strong["evidence_level"],
                                    confidence="STRONG",
                                    recommendation=labels.OUT_UNRESOLVED)
    assert decision.rule_fired == "R1"
    assert decision.decision == policy_engine.ESCALATE


def test_insufficient_beats_high_value():
    incomplete = evidence.evaluate_evidence(labels.NO_EXCEPTION, {})
    decision = _decide("case", labels.NO_EXCEPTION, 999999,
                                    incomplete["evidence_level"],
                                    missing_sources=incomplete["missing_sources"])
    assert decision.rule_fired == "R1"
    assert decision.decision == policy_engine.ESCALATE


def test_R3_non_permitted_class():
    strong = evidence.evaluate_evidence(labels.PRIOR_AMENDMENT, FULL)
    decision = _decide("case", labels.PRIOR_AMENDMENT, 1000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R3"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_R4_value_above_autonomous_cap():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 6000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R4"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_R2_value_circuit_breaker_beats_class():
    strong = evidence.evaluate_evidence(labels.PRIOR_AMENDMENT, FULL)
    decision = _decide("case", labels.PRIOR_AMENDMENT, 50001,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R2"
    assert decision.decision == policy_engine.ESCALATE


def test_R4_exact_autonomous_cap_is_allowed():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 5000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R6"


def test_R2_exact_escalation_cap_is_not_escalated_by_value():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 50000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R4"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_R4_weak_evidence_requires_approval():
    weak = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL, near_miss=True)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                                    weak["evidence_level"])
    assert decision.rule_fired == "R5"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_unknown_class_escalates_under_R3():
    strong = evidence.evaluate_evidence("UNKNOWN", FULL)
    decision = _decide("case", "UNKNOWN", 1000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R3"
    assert decision.decision == policy_engine.ESCALATE
