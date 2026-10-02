"""Stage 5: report explicitly assumed minutes saved per human-reviewed case."""

import math
import os

import pandas as pd

import config as C
if not hasattr(C, "MINUTES_SAVED_PER_CASE"):
    from src import config as C
import labels as L
import policy_engine as P


# ---------------------------------------------------------------- provenance
OBSERVED = "OBSERVED — counted in the log"
MEASURED = "MEASURED — produced by the experiment"
ASSUMED = "ASSUMED — a stated assumption, not evidence"
CALCULATED = "CALCULATED — derived from the above"


def assumptions_ready():
    """Return unset inputs; investigation time is not present in the event log."""
    return [] if C.MINUTES_SAVED_PER_CASE is not None else ["MINUTES_SAVED_PER_CASE"]


def minutes_saved_by_class(res):
    """Apply the explicitly assumed minutes saved per human-reviewed case."""
    missing = assumptions_ready()
    if missing:
        return None, missing
    minutes = float(C.MINUTES_SAVED_PER_CASE)
    if not math.isfinite(minutes) or minutes < 0:
        return None, ["MINUTES_SAVED_PER_CASE must be a finite non-negative number"]
    reviewed = res[res["C_decision"].isin([P.HUMAN_APPROVAL, P.ESCALATE])]
    groups = reviewed.groupby("exception_class_derived")["case_id"].nunique()
    out = pd.DataFrame({"n_cases": groups}).reset_index()
    out = out.rename(columns={"exception_class_derived": "exception_class"})
    out["assumed_minutes_saved_per_case"] = minutes
    out["estimated_minutes_saved"] = out.n_cases * minutes
    out["estimated_hours_saved"] = out.estimated_minutes_saved / 60
    return out, []


def provenance_table():
    """Keep observed counts, measured routing, and assumed time distinct."""
    return pd.DataFrame([
        {"input": "Cases routed to human review", "provenance": MEASURED,
         "source": "case_results.csv, policy v1.3"},
        {"input": "Minutes saved per reviewed case", "provenance": ASSUMED,
         "source": f"MINUTES_SAVED_PER_CASE={C.MINUTES_SAVED_PER_CASE}; "
                   "must be measured in a shadow pilot, not inferred from the event log"},
        {"input": "Early-payment discount capture", "provenance": ASSUMED,
         "source": f"EARLY_PAY_DISCOUNT_PCT={C.EARLY_PAY_DISCOUNT_PCT}; "
               "not measured or included in this value model"},
        {"input": "Estimated minutes saved", "provenance": CALCULATED,
         "source": "human-reviewed case count multiplied by the explicit minutes-per-case assumption"},
    ])


# --------------------------------------------------------------- 3. work queue
def priority_queue(res, top=25):
    """
    Surface high-exposure, low-confidence cases first for human review.

    Confidence is categorical; it is mapped to a documented ordinal weight.
    """
    d = res[res["C_decision"].isin([P.HUMAN_APPROVAL, P.ESCALATE])].copy()
    if d.empty:
        return d
    uncertainty = {L.CONFIDENCE_STRONG: 0.25,
                   L.CONFIDENCE_INTERMEDIATE: 0.5,
                   L.CONFIDENCE_WEAK: 1.0}
    d["uncertainty"] = d["B_confidence"].map(uncertainty).fillna(0.75)
    d["priority_score"] = d["exposure_eur"].fillna(0) * d["uncertainty"]
    d = d.sort_values("priority_score", ascending=False).head(top)
    return d[["case_id", "exception_class_derived", "exposure_eur",
              "B_confidence", "uncertainty", "priority_score",
              "C_decision", "routed_to"]]


# ------------------------------------------------------------------- reporting
def run(res, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    missing = assumptions_ready()

    if missing:
        print("  VALUE MODEL NOT COMPUTED. Unset assumptions: " + ", ".join(missing))
        print("  Measure the minutes saved per human-reviewed case during a shadow pilot.")
        provenance_table().to_csv(f"{outdir}/value_provenance.csv", index=False)
        return None

    saved, _ = minutes_saved_by_class(res)
    saved.to_csv(f"{outdir}/minutes_saved_by_case.csv", index=False)
    print("\n  ESTIMATED MINUTES SAVED BY CASE CLASS (ASSUMPTION-DRIVEN)")
    print(saved.to_string(index=False))

    q = priority_queue(res)
    if not q.empty:
        q.to_csv(f"{outdir}/priority_queue.csv", index=False)
        print(f"\n  PRIORITY QUEUE: top {len(q)} cases by exposure x uncertainty")

    provenance_table().to_csv(f"{outdir}/value_provenance.csv", index=False)
    print("\n  Provenance table written. Never present a CALCULATED figure "
          "without the ASSUMED rows beside it.")
    return saved
