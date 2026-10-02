"""
headline_numbers.py - the numbers you need for the interview. No API calls.

Run from the repo root:
    venv/Scripts/python.exe scripts/headline_numbers.py
Then open: outputs/headline_numbers.md
"""
import json
import os
from pathlib import Path

import pandas as pd

RESULTS = Path("outputs/case_results_v13.csv")
LEGACY_RESULTS = Path("outputs/case_results.csv")
CACHE = Path("outputs/agent_cache")
OUT = Path("outputs/headline_numbers.md")
NO_EXC = "NO_EXCEPTION"


def pct(x):
    return "n/a" if x is None or pd.isna(x) else f"{x * 100:.1f}%"


def run_provenance():
    """Count cached results by the mode stored inside each JSON file."""
    if not CACHE.exists():
        return "cache files: 0 live, 0 mock, 0 unknown, 0 total"
    counts = {"live": 0, "mock": 0, "unknown": 0}
    total = 0
    for path in CACHE.iterdir():
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        total += 1
        try:
            with path.open(encoding="utf-8") as handle:
                mode = json.load(handle).get("result", {}).get("mode")
        except (OSError, ValueError, TypeError, AttributeError):
            mode = None
        counts[mode if mode in ("live", "mock") else "unknown"] += 1
    return (f"cache files: {counts['live']} live, {counts['mock']} mock, "
            f"{counts['unknown']} unknown, {total} total")


def arm_block(df, title):
    a_cov = df["A_confident"].mean()
    a_on_cov = df.loc[df["A_confident"], "A_correct"].mean() if df["A_confident"].any() else None
    human_review = df["C_decision"] == "HUMAN_APPROVAL"
    escalated = df["C_decision"] == "ESCALATE"
    lines = [
        f"### {title} (n={len(df)})\n",
        "| Metric | Value |", "|---|---|",
        f"| Arm A - coverage (rules confident) | {pct(a_cov)} |",
        f"| Arm A - accuracy on covered cases | {pct(a_on_cov)} |",
        f"| Arm A - accuracy overall | {pct(df['A_correct'].mean())} |",
        f"| Arm B - accuracy | {pct(df['B_correct'].mean())} |",
        f"| Arm C - human review | {int(human_review.sum())} ({pct(human_review.mean())}) |",
        f"| Arm C - escalation | {int(escalated.sum())} ({pct(escalated.mean())}) |",
    ]
    for dec, n in df["C_decision"].value_counts().items():
        lines.append(f"| Arm C - {dec} | {n} ({pct(n / len(df))}) |")
    return lines


def main():
    results = RESULTS if RESULTS.exists() else LEGACY_RESULTS
    if not results.exists():
        print(f"Not found: {RESULTS} or {LEGACY_RESULTS}")
        return
    df = pd.read_csv(results)
    if "n_tool_calls" in df.columns:
        df = df[df["n_tool_calls"].fillna(0) > 0].copy()
    for col in ("A_confident", "A_correct", "B_correct"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().isin(["true", "1", "1.0", "yes"])

    exc = df[df["exception_class_derived"] != NO_EXC]

    L = ["# Headline numbers\n",
         f"Source: `{results}` (modified {pd.Timestamp(os.path.getmtime(results), unit='s')})  ",
         f"Run provenance: {run_provenance()}  ",
         f"Policy version(s) in file: {sorted(df['policy_version'].dropna().unique())}\n",
         "Categorical confidence and policy v1.3 have not been evaluated live.\n",
         f"{len(df)} cases - {len(exc)} exceptions, {len(df) - len(exc)} clean\n"]

    L += arm_block(df, "All cases") + [""] + arm_block(exc, "Exception cases only")

    L += ["\n## Per exception class\n",
          "| Class | n | A coverage | A correct | B correct | Human review | Escalated |",
          "|---|---|---|---|---|---|---|"]
    for cls, g in df.groupby("exception_class_derived"):
        human_review = g["C_decision"] == "HUMAN_APPROVAL"
        escalated = g["C_decision"] == "ESCALATE"
        L.append(f"| {cls} | {len(g)} | {pct(g['A_confident'].mean())} | "
                 f"{pct(g['A_correct'].mean())} | {pct(g['B_correct'].mean())} | "
                 f"{int(human_review.sum())} | {int(escalated.sum())} |")

    for col, title in [("evidence_level", "Evidence level"), ("rule_fired", "Rule fired")]:
        if col in df.columns and df[col].notna().any():
            L += [f"\n## {title}\n", f"| {title} | All | Exceptions |", "|---|---|---|"]
            for v, n in df[col].value_counts().items():
                L.append(f"| {v} | {n} | {(exc[col] == v).sum()} |")

    dis = df[~df["B_correct"]]
    dis_exc = dis[dis["exception_class_derived"] != NO_EXC]
    L += ["\n## Disagreements (agent vs historically observed outcome)\n",
          f"- All cases: **{len(dis)}** of {len(df)} ({pct(len(dis) / len(df))})",
          f"- Exception cases: **{len(dis_exc)}** of {len(exc)}"
          f"{' (' + pct(len(dis_exc) / len(exc)) + ')' if len(exc) else ''}",
          "- By class: " + ", ".join(f"{k}={v}" for k, v in
                                     dis["exception_class_derived"].value_counts().items())]

    if "B_confidence" in df.columns and df["B_confidence"].notna().any():
        confidence = df.get("confidence_band", df["B_confidence"])
        g = df.assign(_confidence=confidence).groupby("_confidence", dropna=False)["B_correct"].agg(["size", "mean"])
        L += ["\n## Stated confidence vs actual accuracy (diagnostic only; not authority)\n",
              "| Confidence | n | Accuracy |", "|---|---|---|"]
        L += [f"| {i} | {int(r['size'])} | {pct(r['mean'])} |" for i, r in g.iterrows()]

    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\nWritten to {OUT}")


if __name__ == "__main__":
    main()
