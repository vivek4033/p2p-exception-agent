"""Report frozen evaluation split and reference-pool class counts."""

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main():
    eval_frame = pd.read_csv(ROOT / "outputs" / "case_results.csv")
    pool = pd.read_csv(ROOT / "outputs" / "exception_summary.csv")
    eval_counts = eval_frame["exception_class_derived"].value_counts().rename("eval_n")
    pool_counts = pool.set_index("exception_class")["n_cases"].rename("reference_n")
    table = pd.concat([eval_counts, pool_counts], axis=1).fillna(0).astype(int)
    total = int(pool_counts.sum())
    eval_total = int(len(eval_frame))
    lines = ["# Split Statistics", "",
             f"- Total labelled cases: {total:,}",
             f"- Evaluation cases: {eval_total:,}",
             f"- Evaluation share: {100 * eval_total / total:.2f}%", "",
             "| Exception class | Eval n | Reference n | Eval share of class |", "|---|---:|---:|---:|"]
    for name, row in table.sort_index().iterrows():
        lines.append(f"| {name} | {row.eval_n:,} | {row.reference_n:,} | "
                     f"{100 * row.eval_n / row.reference_n:.2f}% |")
    lines += ["", "The frozen evaluation set is stratified by exception class; this report "
              "describes the realized sample rather than claiming equal allocation."]
    output = ROOT / "outputs" / "split_stats.md"
    output.write_text("\n".join(lines) + "\n")
    print(output.read_text())


if __name__ == "__main__":
    main()
