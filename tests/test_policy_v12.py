import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import evidence
import evaluate
import labels
import policy_engine
import rescore_v12
import value_model


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
    assert decision.rule_fired == "R7"
    assert decision.decision == policy_engine.HUMAN_APPROVAL
    assert decision.routed_to == "AP Team"


def test_non_clear_recommendation_for_no_exception_requires_human_approval():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                       strong["evidence_level"], confidence="STRONG",
                       recommendation=labels.OUT_CANCELLED)
    assert decision.rule_fired == "R6"
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


def test_human_matrix_class_stays_human():
    strong = evidence.evaluate_evidence(labels.PRIOR_AMENDMENT, FULL)
    decision = _decide("case", labels.PRIOR_AMENDMENT, 1000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R7"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_value_above_former_autonomy_cap_stays_human():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 6000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R7"
    assert decision.decision == policy_engine.HUMAN_APPROVAL


def test_R2_value_circuit_breaker_beats_class():
    strong = evidence.evaluate_evidence(labels.PRIOR_AMENDMENT, FULL)
    decision = _decide("case", labels.PRIOR_AMENDMENT, 50001,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R2"
    assert decision.decision == policy_engine.ESCALATE


def test_value_at_former_autonomy_cap_stays_human():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 5000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R7"


def test_R2_exact_escalation_cap_is_not_escalated_by_value():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 50000,
                                    strong["evidence_level"])
    assert decision.rule_fired == "R7"
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
    assert decision.rule_fired == "R4"
    assert decision.decision == policy_engine.ESCALATE


def test_po_changed_after_invoice_escalates():
    strong = evidence.evaluate_evidence(labels.NO_EXCEPTION, FULL)
    decision = _decide("case", labels.NO_EXCEPTION, 1000,
                       strong["evidence_level"],
                       contradictions=["PO_CHANGED_AFTER_INVOICE"])
    assert decision.rule_fired == "R3"
    assert decision.decision == policy_engine.ESCALATE


def test_policy_matrix_has_no_automatic_tier():
    assert {row["tier"] for row in policy_engine.MATRIX_V1_3.values()} <= {
        policy_engine.HUMAN_APPROVAL, policy_engine.ESCALATE,
    }


def test_minutes_saved_model_requires_explicit_assumption(monkeypatch):
    monkeypatch.setattr(value_model.C, "MINUTES_SAVED_PER_CASE", None)
    result, missing = value_model.minutes_saved_by_class(pd.DataFrame())
    assert result is None
    assert missing == ["MINUTES_SAVED_PER_CASE"]


def test_minutes_saved_model_counts_only_human_routed_cases(monkeypatch):
    monkeypatch.setattr(value_model.C, "MINUTES_SAVED_PER_CASE", 10)
    cases = pd.DataFrame({
        "case_id": ["review", "escalated", "other"],
        "exception_class_derived": ["A", "A", "B"],
        "C_decision": ["HUMAN_APPROVAL", "ESCALATE", "UNKNOWN"],
    })

    result, missing = value_model.minutes_saved_by_class(cases)

    assert missing == []
    assert result.set_index("exception_class").loc["A", "n_cases"] == 2
    assert result.set_index("exception_class").loc["A", "estimated_minutes_saved"] == 20
    assert "B" not in set(result.exception_class)


def test_run_arms_uses_erp_exposure_and_records_agent_mismatch(monkeypatch):
    cases = pd.DataFrame([{
        "case_id": "case-erp-value",
        "exception_class": labels.NO_EXCEPTION,
        "outcome_label": labels.OUT_AUTO_CLEARED,
        "exposure_eur": 80000.0,
        "abs_variance_pct": None,
        "vendor": "vendor-a",
    }])
    rules = pd.DataFrame([{
        "case_id": "case-erp-value",
        "near_miss": False,
        "prediction": labels.OUT_AUTO_CLEARED,
        "confident": True,
    }])
    tool_outputs = {
        "get_invoice": {"status": "ok", "records": [{
            "invoice_received_before_goods_receipt": False,
        }]},
        "lookup_po": {"status": "ok", "records": [{
            "gr_ir_count_mismatch": False,
            "po_changed_after_invoice": False,
        }]},
        "lookup_goods_receipt": {"status": "ok", "records": [{
            "goods_receipt_recorded": True,
        }]},
        "lookup_policy": {"status": "ok", "records": [{
            "price_tolerance_pct": 2.0,
        }]},
    }

    class FakeToolBox:
        def __init__(self, cases, events=None):
            pass

        def decision_time(self, case_id):
            return pd.Timestamp("2020-01-01", tz="UTC")

    monkeypatch.setattr(evaluate, "ToolBox", FakeToolBox)
    monkeypatch.setattr(evaluate.R, "run", lambda frame: rules)
    monkeypatch.setattr(evaluate.A, "investigate", lambda *args, **kwargs: ({
        "exception_type": labels.NO_EXCEPTION,
        "recommendation": labels.OUT_AUTO_CLEARED,
        "confidence": labels.CONFIDENCE_STRONG,
        "exposure_eur": 1000.0,
        "_tool_outputs": tool_outputs,
    }, []))

    result, _ = evaluate.run_arms(cases, verbose=False)

    row = result.iloc[0]
    assert row["C_decision"] == policy_engine.ESCALATE
    assert row["rule_fired"] == "R2"
    assert row["exposure_eur"] == 80000.0
    assert row["B_exposure_eur"] == 1000.0
    assert "AGENT_EXPOSURE_MISMATCH" in row["contradictions"]


def test_rescore_uses_cached_erp_value_and_recommendation():
    tool_outputs = {
        "get_invoice": {"status": "ok", "records": [{
            "exposure_eur": 80000.0,
            "invoice_received_before_goods_receipt": False,
        }]},
        "lookup_po": {"status": "ok", "records": [{
            "net_worth_eur": 80000.0,
            "gr_ir_count_mismatch": False,
            "po_changed_after_invoice": False,
        }]},
        "lookup_goods_receipt": {"status": "ok", "records": [{
            "goods_receipt_recorded": True,
        }]},
        "lookup_policy": {"status": "ok", "records": [{
            "price_tolerance_pct": 2.0,
        }]},
    }
    case = {
        "case_id": "cached-high-value",
        "exception_type": labels.NO_EXCEPTION,
        "value_eur": rescore_v12.erp_exposure(tool_outputs),
        "agent_exposure_eur": 1000.0,
        "near_miss": False,
        "tool_outputs": tool_outputs,
        "model_confidence": 0.95,
        "recommendation": labels.OUT_AUTO_CLEARED,
    }

    checklist, decision = rescore_v12.score_case(case)

    assert decision.exposure_eur == 80000.0
    assert decision.rule_fired == "R2"
    assert decision.decision == policy_engine.ESCALATE
    assert checklist["contradictions"] == ["AGENT_EXPOSURE_MISMATCH"]
    assert labels.normalize_confidence(0.95) == labels.CONFIDENCE_STRONG
