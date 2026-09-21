"""Replay logged tool calls into agent-cache records without calling Anthropic.

Expected JSONL record shapes are either:
  {"case_id": "...", "trajectory": ["get_invoice", ...]}
or:
  {"case_id": "...", "tool_calls": [{"name": "get_invoice", "case_id": "..."}, ...]}

A trajectory log is required. This script intentionally refuses to infer calls
from model outputs or re-run the agent.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools import ToolBox
import data


def replay_record(record, box):
    case_id = str(record["case_id"])
    calls = record.get("tool_calls")
    if calls is None:
        calls = [{"name": name, "case_id": case_id}
                 for name in record.get("trajectory", [])]
    outputs = {}
    trajectory = []
    for call in calls:
        name = call["name"]
        call_case_id = str(call.get("case_id", case_id))
        outputs[name] = box.call(name, call_case_id)
        trajectory.append(name)
    return case_id, outputs, trajectory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trajectory", type=Path)
    parser.add_argument("--out", type=Path, default=Path("outputs/agent_cache"))
    args = parser.parse_args()
    if not args.trajectory.exists():
        raise SystemExit(f"Trajectory log not found: {args.trajectory}")
    if args.trajectory.suffix.lower() != ".jsonl":
        raise SystemExit("Trajectory must be JSONL; no alternate source is inferred.")

    cases = data.case_features(None, with_variants=False)
    box = ToolBox(cases)
    args.out.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.trajectory.open() as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            case_id, outputs, trajectory = replay_record(record, box)
            result = dict(record.get("agent_output", record.get("result", {})))
            result["_tool_outputs"] = outputs
            result["mode"] = result.get("mode", "replay")
            cache_path = args.out / f"{case_id}_replay.json"
            cache_path.write_text(json.dumps({
                "result": result, "trajectory": trajectory,
                "replayed_from": str(args.trajectory),
            }))
            count += 1
    print(f"Replayed {count} trajectory records into {args.out}")


if __name__ == "__main__":
    main()
