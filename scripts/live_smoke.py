"""Run a bounded live Arm B smoke test and report cached token usage."""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import data
import evaluate as E
import labels as L


INPUT_PRICE_PER_MILLION = 3.0
OUTPUT_PRICE_PER_MILLION = 15.0


def cache_records(case_ids):
    records = []
    for case_id in case_ids:
        for path in glob.glob(f"outputs/agent_cache/{case_id}_*.json"):
            with open(path, encoding="utf-8") as handle:
                record = json.load(handle)
            if record.get("result", {}).get("mode") == "live":
                records.append(record)
                break
    return records


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    if count < 1:
        raise SystemExit("case count must be positive")
    features = L.build(data.case_features(None, with_variants=False), None)
    features, _ = L.analysis_population(features)
    eval_set = E.build_eval_set(features).head(count).copy()
    events = data.load_log()
    result, _ = E.run_arms(eval_set, mock=False, verbose=True, events=events)
    case_ids = result["case_id"].tolist() if "case_id" in result else []
    records = cache_records(case_ids)
    input_tokens = sum(r["result"].get("_usage", {}).get("input_tokens", 0) for r in records)
    output_tokens = sum(r["result"].get("_usage", {}).get("output_tokens", 0) for r in records)
    cost = (input_tokens / 1_000_000 * INPUT_PRICE_PER_MILLION
            + output_tokens / 1_000_000 * OUTPUT_PRICE_PER_MILLION)
    print("\nCASES")
    for record in records:
        result_data = record["result"]
        print(f"{result_data.get('mode')} case={result_data.get('exception_type')} "
              f"recommendation={result_data.get('recommendation')} "
              f"confidence={result_data.get('confidence')}")
    print("\nCOST")
    print(f"cases={len(records)}")
    print(f"input_tokens={input_tokens}")
    print(f"output_tokens={output_tokens}")
    print(f"estimated_cost_usd={cost:.6f}")
    print(f"extrapolated_200_usd={cost / len(records) * 200:.6f}" if records else "extrapolated_200_usd=n/a")
    print(f"cache_live_files={len(records)}")
    if not records:
        print("status=no live cases completed; check outputs/arm_failures.csv")
        raise SystemExit(1)


if __name__ == "__main__":
    main()