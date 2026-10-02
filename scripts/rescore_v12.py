"""Re-score cached agent results with policy v1.3; never calls the model."""

import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evidence
import labels
import policy_engine

CACHE = ROOT / "outputs" / "agent_cache"
OUT = ROOT / "outputs" / "case_results_v13.csv"


def erp_exposure(tool_outputs):
    """Read the authoritative exposure from cached ERP tool responses."""
    for tool_name, field in (("get_invoice", "exposure_eur"),
                             ("lookup_po", "net_worth_eur")):
        response = tool_outputs.get(tool_name) or {}
        records = response.get("records") or []
        candidates = records + [response]
        for payload in candidates:
            value = payload.get(field)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
    return None


def score_case(case):
    value = case["value_eur"]
    mismatch = evidence.exposure_contradictions(case["agent_exposure_eur"], value)
    checklist = evidence.evaluate_evidence(
        case["exception_type"], case["tool_outputs"], case["near_miss"],
        additional_contradictions=mismatch)
    decision = policy_engine.decide(
        case["case_id"], case["exception_type"], value,
        checklist["evidence_level"],
        missing_sources=checklist["missing_sources"],
        contradictions=checklist["contradictions"],
        confidence=labels.normalize_confidence(case["model_confidence"]),
        recommendation=case["recommendation"],
    )
    return checklist, decision


def load_cases():
    historical = {}
    baseline_path = ROOT / "outputs" / "case_results.csv"
    if baseline_path.exists():
        import csv
        with baseline_path.open(newline="", encoding="utf-8") as handle:
            historical = {row["case_id"]: row for row in csv.DictReader(handle)}
    for path in CACHE.glob("*.json"):
        with path.open() as handle:
            cached = json.load(handle)
        result = cached.get("result", {})
        tool_outputs = result.get("_tool_outputs", {})
        case_id = str(result.get("case_id") or path.stem.rsplit("_", 1)[0])
        yield {
            **historical.get(case_id, {}),
            "case_id": case_id,
            "exception_type": result.get("exception_type"),
            "value_eur": erp_exposure(tool_outputs),
            "agent_exposure_eur": result.get("exposure_eur"),
            "near_miss": bool(result.get("near_miss", False)),
            "tool_outputs": tool_outputs,
            "model_confidence": result.get("confidence"),
            "recommendation": result.get("recommendation"),
            "decision_time": result.get("decision_time"),
            "tools_called": cached.get("trajectory", []),
        }


def main():
    import csv
    rows = []
    for case in load_cases():
        checklist, decision = score_case(case)
        rows.append({
            "case_id": case["case_id"],
            "exception_class_derived": case.get("exception_class_derived"),
            "outcome_label": case.get("outcome_label"),
            "A_prediction": case.get("A_prediction"),
            "A_confident": case.get("A_confident"),
            "A_correct": case.get("A_correct"),
            "final_bucket": case.get("final_bucket"),
            "B_prediction": case["recommendation"],
            "B_correct": (case["recommendation"] == case.get("outcome_label")
                          if case.get("outcome_label") else None),
            "B_confidence": case["model_confidence"],
            "exception_type": case["exception_type"],
            "value_eur": case["value_eur"],
            "agent_exposure_eur": case["agent_exposure_eur"],
            "recommendation": case["recommendation"],
            "decision_time": case["decision_time"],
            "model_confidence": case["model_confidence"],
            "confidence_band": labels.normalize_confidence(case["model_confidence"]),
            "tools_called": "|".join(case["tools_called"]),
            **checklist,
            "missing_sources": "|".join(checklist["missing_sources"]),
            "contradictions": "|".join(checklist["contradictions"]),
            "decision": decision.decision,
            "C_decision": decision.decision,
            "C_human_review": decision.decision == policy_engine.HUMAN_APPROVAL,
            "routed_to": decision.routed_to,
            "counterfactual_check": decision.counterfactual_check,
            "rule_fired": decision.rule_fired,
            "reason": decision.reason,
            "policy_version": decision.policy_version,
        })
    if not rows:
        print(f"No cached agent runs found in {CACHE}; no API calls made.")
        return
    import pandas as pd
    results = pd.DataFrame(rows)
    accuracy = results.dropna(subset=["B_correct"]).groupby(
        "exception_class_derived")["B_correct"].agg(
            n_cases="size", recommendation_accuracy="mean")
    accuracy.reset_index().rename(
        columns={"exception_class_derived": "exception_class"}
    ).to_csv(ROOT / "outputs" / "recommendation_quality_by_class.csv", index=False)
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results.columns))
        writer.writeheader()
        writer.writerows(results.to_dict("records"))
    accuracy_all = results["B_correct"].dropna()
    print(f"Agent recommendation accuracy on labelled cases: "
          f"{accuracy_all.mean():.3f}" if not accuracy_all.empty else
          "No historical labels matched cached cases.")
    print(f"{len(rows)} cached live cases re-scored offline -> {OUT}")
    print("Decisions:", dict(Counter(row["decision"] for row in rows)))
    print("Rules fired:", dict(Counter(row["rule_fired"] for row in rows)))
    print("Evidence levels:", dict(Counter(row["evidence_level"] for row in rows)))


if __name__ == "__main__":
    main()
