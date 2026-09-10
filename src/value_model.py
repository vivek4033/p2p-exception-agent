"""
value_model.py — Stage 5. Turns the measured autonomy boundary into a business case.

Two things live here.

1. ASYMMETRIC ERROR COST. Not all mistakes cost the same. A false escalation
   wastes a clerk's time. A false automation clears a payment that should not
   have cleared — financial exposure plus a control failure. Treating them as
   equally bad is what makes naive accuracy the wrong metric.

       expected cost of autonomy per class
           = P(incorrect autonomous action) x mean exposure x severity
             + P(unnecessary escalation) x cost per human touch

   This converts the policy matrix from an argued position into an arithmetic
   one: a class earns autonomy when the expected cost of granting it is lower
   than the expected cost of withholding it.

2. SCENARIO VALUE MODEL. Conservative / base / aggressive, with every input
   tagged by provenance so the two categories never blend:

       OBSERVED   counted directly in the log
       MEASURED   produced by the experiment
       ASSUMED    a stated assumption, not evidence
       CALCULATED derived from the above

The model REFUSES TO COMPUTE while any assumption is unset. Guardrail 7 — never
cite a benchmark you have not opened. An empty output here is correct behaviour,
not a bug.
"""

import os

import pandas as pd

import config as C
import policy_engine as P


# ---------------------------------------------------------------- provenance
OBSERVED = "OBSERVED — counted in the log"
MEASURED = "MEASURED — produced by the experiment"
ASSUMED = "ASSUMED — a stated assumption, not evidence"
CALCULATED = "CALCULATED — derived from the above"


def assumptions_ready():
    """Which cost inputs are still unset. Empty list means the model may run."""
    missing = []
    if C.LOADED_HOURLY_COST_EUR is None:
        missing.append("LOADED_HOURLY_COST_EUR")
    if getattr(C, "MINUTES_PER_INVESTIGATION", None) is None:
        missing.append("MINUTES_PER_INVESTIGATION")
    if getattr(C, "FALSE_AUTOMATION_SEVERITY", None) is None:
        missing.append("FALSE_AUTOMATION_SEVERITY")
    return missing


# ------------------------------------------------------- 1. asymmetric error cost
def error_cost_by_class(res):
    """
    Expected cost of granting autonomy to each exception class, against the
    expected cost of withholding it.

    severity is a multiplier on exposure, not a claim that a wrong release costs
    the full invoice value. It represents the share of exposure genuinely at
    risk plus the cost of the control failure, and it is an ASSUMPTION.
    """
    missing = assumptions_ready()
    if missing:
        return None, missing

    touch = C.LOADED_HOURLY_COST_EUR * (C.MINUTES_PER_INVESTIGATION / 60.0)
    sev = C.FALSE_AUTOMATION_SEVERITY

    rows = []
    for cls, g in res.groupby("exception_class_derived"):
        n = len(g)
        if n == 0:
            continue
        p_correct = float(g["B_correct"].mean())
        p_wrong = 1.0 - p_correct
        mean_exposure = float(g["exposure_eur"].fillna(0).mean())

        cost_if_autonomous = p_wrong * mean_exposure * sev
        cost_if_human = touch                      # every case costs one touch
        tier = P.MATRIX_V1_0.get(cls, {}).get("tier", P.ESCALATE)

        rows.append({
            "exception_class": cls,
            "n_cases": n,
            "precision": round(p_correct, 4),
            "mean_exposure_eur": round(mean_exposure, 2),
            "expected_cost_if_autonomous_eur": round(cost_if_autonomous, 2),
            "expected_cost_if_human_eur": round(cost_if_human, 2),
            "net_benefit_of_autonomy_eur": round(cost_if_human - cost_if_autonomous, 2),
            "economically_justified": bool(cost_if_autonomous < cost_if_human),
            "current_tier_v1_0": tier,
            "agrees_with_policy": bool(
                (cost_if_autonomous < cost_if_human) == (tier == P.AUTO_RESOLVE)),
        })

    df = pd.DataFrame(rows).sort_values("net_benefit_of_autonomy_eur", ascending=False)
    return df, []


def policy_disagreements(cost_df):
    """
    Where the arithmetic and the policy matrix disagree. Each row is a finding
    to explain, not a bug to silence — a class the numbers say should be
    autonomous but policy holds back is a deliberate control choice, and one
    the numbers say should be held back but policy permits is a defect.
    """
    if cost_df is None or cost_df.empty:
        return pd.DataFrame()
    d = cost_df[~cost_df["agrees_with_policy"]].copy()
    d["interpretation"] = d.apply(
        lambda r: ("Numbers favour autonomy; policy withholds it. A deliberate "
                   "control choice — state the reason."
                   if r["economically_justified"]
                   else "Policy permits autonomy the numbers do not support. "
                        "Demote this class."), axis=1)
    return d


# ------------------------------------------------------- 2. scenario value model
SCENARIOS = {
    "conservative": {
        "precision_threshold": 0.97,
        "note": "Autonomy only where precision is high and the class is simple.",
    },
    "base": {
        "precision_threshold": 0.95,
        "note": "The pilot threshold. A design choice, not an industry standard.",
    },
    "aggressive": {
        "precision_threshold": 0.90,
        "note": "Higher coverage, materially greater exposure to false automation.",
    },
}


def scenario_model(sens, annual_exception_volume=None):
    """
    Converts measured automation coverage into avoided manual investigations and
    a capacity value. Volume defaults to the observed blocked-case count, which
    keeps the model anchored to this dataset rather than an invented enterprise.
    """
    missing = assumptions_ready()
    if missing:
        return None, missing
    if sens is None or sens.empty:
        return None, ["threshold_sensitivity.csv — run the experiment first"]

    rows = []

    for name, cfg in SCENARIOS.items():
        row = sens[sens["precision_threshold"] == cfg["precision_threshold"]]
        if row.empty or pd.isna(row["automation_rate"].iloc[0]):
            continue
        r = row.iloc[0]
        coverage = float(r["automation_rate"])
        volume = annual_exception_volume or 0
        avoided = coverage * volume
        hours = avoided * (C.MINUTES_PER_INVESTIGATION / 60.0)

        rows.append({
            "scenario": name,
            "investigation_minutes": C.MINUTES_PER_INVESTIGATION,
            "false_automation_severity": C.FALSE_AUTOMATION_SEVERITY,
            "precision_threshold": cfg["precision_threshold"],
            "automation_coverage": round(coverage, 4),
            "classes_permitted": int(r.get("classes_permitted", 0)),
            "binding_constraint": r.get("binding_constraint"),
            "exception_volume": int(volume),
            "manual_investigations_avoided": int(round(avoided)),
            "ap_hours_released": round(hours, 1),
            "capacity_value_eur": round(hours * C.LOADED_HOURLY_COST_EUR, 2),
            "value_under_autonomous_decision_eur": r.get("value_automated_eur"),
            "note": cfg["note"],
        })

    return pd.DataFrame(rows), []


def sensitivity_model(sens, annual_exception_volume=None):
    """Report value across the published time range and severity judgment."""
    missing = assumptions_ready()
    if missing or sens is None or sens.empty:
        return pd.DataFrame()
    volume = annual_exception_volume or 0
    rows = []
    for minutes in getattr(C, "MINUTES_SENSITIVITY", [C.MINUTES_PER_INVESTIGATION]):
        for severity in getattr(C, "FALSE_AUTOMATION_SEVERITY_SENSITIVITY", [C.FALSE_AUTOMATION_SEVERITY]):
            for threshold in C.SENSITIVITY_SWEEP:
                match = sens[sens["precision_threshold"] == threshold]
                if match.empty or pd.isna(match["automation_rate"].iloc[0]):
                    continue
                rate = float(match["automation_rate"].iloc[0])
                avoided = rate * volume
                hours = avoided * minutes / 60.0
                rows.append({
                    "precision_threshold": threshold,
                    "investigation_minutes": minutes,
                    "false_automation_severity": severity,
                    "automation_coverage": round(rate, 4),
                    "manual_investigations_avoided": int(round(avoided)),
                    "ap_hours_released": round(hours, 1),
                    "capacity_value_eur": round(hours * C.LOADED_HOURLY_COST_EUR, 2),
                })
    return pd.DataFrame(rows)


def provenance_table():
    """Printed alongside every value figure. The separation is the deliverable."""
    return pd.DataFrame([
        {"input": "Exception volume", "provenance": OBSERVED,
         "source": "blocked cases counted in the log"},
        {"input": "Automation coverage", "provenance": MEASURED,
         "source": "threshold_sensitivity.csv from the three-arm experiment"},
        {"input": "Precision by class", "provenance": MEASURED,
         "source": "precision_by_class.csv"},
        {"input": "Mean exposure per class", "provenance": OBSERVED,
         "source": "case-level net worth in the log"},
        {"input": "Minutes per manual investigation", "provenance": ASSUMED,
         "source": f"base {getattr(C,'MINUTES_PER_INVESTIGATION',None)}; "
                   f"sensitivity {getattr(C,'MINUTES_SENSITIVITY',None)}; "
                   "Nexus AP published range, not captured in the event log"},
        {"input": "Loaded AP hourly cost", "provenance": ASSUMED,
         "source": f"set to {C.LOADED_HOURLY_COST_EUR}; SalaryExpert Netherlands "
                   "gross benchmark, employer burden not included"},
        {"input": "False-automation severity", "provenance": ASSUMED,
         "source": f"base {getattr(C,'FALSE_AUTOMATION_SEVERITY',None)}; "
                   f"sensitivity {getattr(C,'FALSE_AUTOMATION_SEVERITY_SENSITIVITY',None)}; "
                   "judgment, not a benchmark"},
        {"input": "Hours released, capacity value", "provenance": CALCULATED,
         "source": "derived from the rows above"},
    ])


# --------------------------------------------------------------- 3. work queue
def priority_queue(res, top=25):
    """
    The second business outcome. Automation reduces how many cases humans touch;
    prioritisation improves what they do with the ones that remain.

    Ranked by exposure x uncertainty, so the highest-value least-certain cases
    surface first rather than whatever arrived earliest.
    """
    d = res[res["C_decision"] != P.AUTO_RESOLVE].copy()
    if d.empty:
        return d
    d["uncertainty"] = 1 - d["B_confidence"].fillna(0.5)
    d["priority_score"] = d["exposure_eur"].fillna(0) * d["uncertainty"]
    d = d.sort_values("priority_score", ascending=False).head(top)
    return d[["case_id", "exception_class_derived", "exposure_eur",
              "B_confidence", "uncertainty", "priority_score",
              "C_decision", "routed_to"]]


# ------------------------------------------------------------------- reporting
def run(res, sens, outdir="outputs"):
    os.makedirs(outdir, exist_ok=True)
    missing = assumptions_ready()

    if missing:
        print("  VALUE MODEL NOT COMPUTED. Unset assumptions: " + ", ".join(missing))
        print("  Set them in src/config.py from sources you have opened.")
        print("  Guardrail 7 — an empty value case is correct, an invented one is not.")
        provenance_table().to_csv(f"{outdir}/value_provenance.csv", index=False)
        return None

    cost, _ = error_cost_by_class(res)
    cost.to_csv(f"{outdir}/error_cost_by_class.csv", index=False)
    print("\n  EXPECTED COST OF AUTONOMY BY CLASS")
    print(cost.to_string(index=False))

    dis = policy_disagreements(cost)
    if not dis.empty:
        dis.to_csv(f"{outdir}/policy_vs_economics.csv", index=False)
        print("\n  WHERE THE ARITHMETIC AND THE POLICY MATRIX DISAGREE")
        print(dis[["exception_class", "current_tier_v1_0",
                   "economically_justified", "interpretation"]].to_string(index=False))

    volume = int(res["case_id"].nunique())
    scen, _ = scenario_model(sens, annual_exception_volume=volume)
    if scen is not None and not scen.empty:
        scen.to_csv(f"{outdir}/value_scenarios.csv", index=False)
        print("\n  SCENARIO VALUE MODEL")
        print(scen.to_string(index=False))

    value_sens = sensitivity_model(sens, annual_exception_volume=volume)
    if not value_sens.empty:
        value_sens.to_csv(f"{outdir}/value_sensitivity.csv", index=False)
        print("\n  VALUE SENSITIVITY (TIME RANGE x SEVERITY ASSUMPTION)")
        print(value_sens.to_string(index=False))

    q = priority_queue(res)
    if not q.empty:
        q.to_csv(f"{outdir}/priority_queue.csv", index=False)
        print(f"\n  PRIORITY QUEUE: top {len(q)} cases by exposure x uncertainty")

    provenance_table().to_csv(f"{outdir}/value_provenance.csv", index=False)
    print("\n  Provenance table written. Never present a CALCULATED figure "
          "without the ASSUMED rows beside it.")
    return scen
