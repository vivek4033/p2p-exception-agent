"""
GO.py — one command, whole pipeline, gates enforced.

    python GO.py

Runs in order: convert if needed, reconnaissance, full pipeline, dashboard.
Stops at the first failed gate rather than producing output you should not
trust. Prints exactly what to do next.

Nothing here needs editing. The data source is auto-detected from what is on
disk; the stamp on every output records which mode actually ran.
"""

import os
import subprocess
import sys

PY = sys.executable


def run(cmd, label):
    print(f"\n{'='*72}\n{label}\n{'='*72}", flush=True)
    r = subprocess.run([PY, "-u"] + cmd)
    if r.returncode != 0:
        print(f"\nFAILED: {label}")
        print("Fix the error above before continuing. Nothing downstream is valid.")
        sys.exit(1)


def find_raw():
    if not os.path.isdir("data"):
        return None
    for f in sorted(os.listdir("data")):
        if f.lower().endswith((".xes", ".xes.gz")):
            return os.path.join("data", f)
    return None


def find_parquet():
    for p in ("data/bpi2019.parquet", "data/log.parquet",
              "data/BPI_Challenge_2019.parquet"):
        if os.path.exists(p):
            return p
    return None


def main():
    print("P2P Exception Agent — full pipeline")

    # ---- step 1: convert, only if needed
    pq = find_parquet()
    if pq:
        print(f"\nUsing existing converted log: {pq}")
    else:
        raw = find_raw()
        if raw:
            run(["xes_to_parquet.py", raw], f"STEP 1 — Converting {raw}")
            pq = find_parquet()
        else:
            print("\nNo dataset found in data/.")
            print("The pipeline will run on the SYNTHETIC FIXTURE — useful for")
            print("checking the code works, but those numbers are not findings.")
            print("\nTo use real data: download BPI Challenge 2019 from")
            print("  https://data.4tu.nl/articles/dataset/BPI_Challenge_2019/12715853")
            print("put the .xes file in data/, and run this again.")

    # ---- step 2: reconnaissance
    if pq:
        run(["phase0_recon.py", pq], "STEP 2 — Reconnaissance")
        print("\n  -> docs/activity_inventory.md written. Read sections 2, 4, 5, 6.")

    # ---- step 3: the pipeline
    run(["run_all.py"] + (["--live"] if "--live" in sys.argv else []),
        "STEP 3 — Pipeline, Stage 0 through Stage 5")

    # ---- step 4: the dashboard
    args = ["build_dashboard.py"]
    if find_parquet() is None:
        args.append("--force")   # fixture preview, page carries a loud banner
    run(args, "STEP 4 — Results dashboard")

    print(f"\n{'='*72}\nDONE\n{'='*72}")
    print("\nOpen this in a browser:")
    print(f"  {os.path.abspath('docs/index.html')}")
    print("\nKey files:")
    for p in ("docs/findings_log.md", "docs/activity_inventory.md",
              "docs/decision_rights.md", "outputs/case_packets_sample.txt",
              "outputs/threshold_sensitivity.csv", "outputs/disagreement_sample.csv"):
        if os.path.exists(p):
            print(f"  {p}")

    print("\nBefore trusting any number, check these three lines in the output above:")
    print("  DATA SOURCE      — must not say SYNTHETIC")
    print("  LEAKAGE CHECK    — must say clean")
    print("  LABEL GATE       — must say PASSED")
    print("\nIf you ran without --live, the agent was a deterministic mock and the")
    print("three-arm scores are not an AI result. Rerun with --live for that.")


if __name__ == "__main__":
    main()
