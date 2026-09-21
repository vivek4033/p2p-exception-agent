"""Re-score cached agent results with policy v1.2; never calls the model."""

import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evidence
import policy_engine

CACHE = ROOT / "outputs" / "agent_cache"
OUT = ROOT / "outputs" / "case_results_v12.csv"


def load_cases():
    for path in CACHE.glob("*.json"):
        with path.open() as handle:
            cached = json.load(handle)
        result = cached.get("result", {})
        yield {
            "case_id": path.stem.split("_")[0],
            "exception_type": result.get("exception_type"),
            "value_eur": result.get("exposure_eur"),
            "near_miss": bool(result.get("near_miss", False)),
            "tool_outputs": result.get("_tool_outputs", {}),
            "model_confidence": result.get("confidence"),
            "decision_time": result.get("decision_time"),
            "tools_called": cached.get("trajectory", []),
        }


def main():
    import csv
    rows = []
    for case in load_cases():
        checklist = evidence.evaluate_evidence(
            case["exception_type"], case["tool_outputs"], case["near_miss"])
        decision = policy_engine.decide(
            case["case_id"], case["exception_type"], case["value_eur"],
            checklist["evidence_level"],
            missing_sources=checklist["missing_sources"],
            contradictions=checklist["contradictions"])
        rows.append({
            "case_id": case["case_id"],
            "exception_type": case["exception_type"],
            "value_eur": case["value_eur"],
            "decision_time": case["decision_time"],
            "model_confidence": case["model_confidence"],
            "tools_called": "|".join(case["tools_called"]),
            **checklist,
            "missing_sources": "|".join(checklist["missing_sources"]),
            "contradictions": "|".join(checklist["contradictions"]),
            "decision": decision.decision,
            "rule_fired": decision.rule_fired,
            "reason": decision.reason,
            "policy_version": decision.policy_version,
        })
    if not rows:
        print(f"No cached agent runs found in {CACHE}; no API calls made.")
        return
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} cached cases -> {OUT}")
    print("Decisions:", dict(Counter(row["decision"] for row in rows)))
    print("Rules fired:", dict(Counter(row["rule_fired"] for row in rows)))
    print("Evidence levels:", dict(Counter(row["evidence_level"] for row in rows)))


if __name__ == "__main__":
    main()
