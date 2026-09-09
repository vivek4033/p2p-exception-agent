"""
evaluate.py — the measurement harness (Stages 3 and 4).

Built before the thing it measures, deliberately.

Three arms on the same held-out cases:
  Arm A  rules engine only          (models the ERP's existing automation)
  Arm B  agent only                 (recommendation taken at face value)
  Arm C  agent + policy engine      (recommendation only executes if permitted)

Arm C is not expected to beat Arm B on raw accuracy. That is the point: the
policy engine trades coverage for precision, and the sensitivity curve prices
that trade.
"""

import json
import os

import numpy as np
import pandas as pd

import config as C
import labels as L
import policy_engine as P
import rules_engine as R
from tools import ToolBox
import agent as A


# ------------------------------------------------------------------ eval set
def build_eval_set(f, n=None, seed=None):
    """Stratified by exception class, held out, frozen to disk."""
    n = n or C.EVAL_SET_SIZE
    seed = seed or C.RANDOM_SEED
    path = "outputs/eval_set.csv"
    if os.path.exists(path):
        ids = pd.read_csv(path)["case_id"].astype(str).tolist()
        return f[f["case_id"].astype(str).isin(ids)].copy()

    parts, rng = [], np.random.default_rng(seed)
    counts = f["exception_class"].value_counts()
    for cls, cnt in counts.items():
        share = max(1, int(round(n * cnt / len(f))))
        sub = f[f["exception_class"] == cls]
        parts.append(sub.sample(min(share, len(sub)), random_state=seed))
    ev = pd.concat(parts).drop_duplicates("case_id")
    if len(ev) > n:
        ev = ev.sample(n, random_state=seed)
    os.makedirs("outputs", exist_ok=True)
    ev[["case_id"]].to_csv(path, index=False)
    return ev.copy()


def freeze_expected_tools(ev, path="docs/expected_tools.json", k=50):
    """
    Guardrail 3: frozen BEFORE the agent runs. Grading after the fact invalidates
    the metric. If the file exists it is never overwritten — the commit timestamp
    is the evidence.
    """
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    os.makedirs("docs", exist_ok=True)
    exp = {}
    for _, r in ev.head(k).iterrows():
        need = ["get_invoice", "lookup_po", "lookup_policy"]
        if r["duplicate_pattern"]:
            need.append("check_duplicate_payment")
        if r["invoice_before_gr"] or not r["has_gr"]:
            need.append("lookup_goods_receipt")
        if r["abs_variance_pct"] is not None and not pd.isna(r["abs_variance_pct"]) \
                and r["abs_variance_pct"] > C.PRICE_TOLERANCE_PCT:
            need.append("lookup_vendor_history")
        exp[str(r["case_id"])] = sorted(set(need))
    with open(path, "w") as fh:
        json.dump(exp, fh, indent=2)
    return exp


# --------------------------------------------------------------------- arms
def run_arms(ev, mock=True, verbose=True):
    box = ToolBox(ev)
    rules = R.run(ev).set_index("case_id")
    rows, trajectories, failures = [], {}, []
    total = len(ev)

    for i, (_, r) in enumerate(ev.iterrows(), 1):
        cid = r["case_id"]
        if verbose and (i % 25 == 0 or i == 1):
            print(f"    case {i}/{total}  {cid}", flush=True)
        try:
            rr = rules.loc[cid]
            if hasattr(rr, "columns"):          # duplicate case_id in the eval set
                rr = rr.iloc[0]
            agent_out, traj = A.investigate(cid, box, mock=mock)
        except Exception as exc:
            failures.append({"case_id": cid, "error": f"{type(exc).__name__}: {exc}"})
            print(f"    SKIPPED {cid}: {type(exc).__name__}: {exc}", flush=True)
            continue
        trajectories[cid] = traj

        pol = P.decide(
            cid,
            agent_out.get("exception_type") or r["exception_class"],
            r["exposure_eur"],
            agent_out.get("confidence"),
            bool(agent_out.get("evidence_complete")),
            near_miss=bool(rr["near_miss"]),
        )

        rows.append({
            "case_id": cid,
            "exception_class_derived": r["exception_class"],
            "outcome_label": r["outcome_label"],
            "exposure_eur": r["exposure_eur"],
            "abs_variance_pct": r["abs_variance_pct"],
            "vendor": r.get("vendor"),
            # Arm A
            "A_prediction": rr["prediction"],
            "A_confident": bool(rr["confident"]),
            "A_correct": bool(rr["confident"] and rr["prediction"] == r["outcome_label"]),
            # Arm B
            "B_exception_type": agent_out.get("exception_type"),
            "B_prediction": agent_out.get("recommendation"),
            "B_confidence": agent_out.get("confidence"),
            "B_correct": agent_out.get("recommendation") == r["outcome_label"],
            # Arm C
            "C_decision": pol.decision,
            "C_acted": pol.decision == P.AUTO_RESOLVE,
            "C_correct_when_acted": (pol.decision == P.AUTO_RESOLVE
                                     and agent_out.get("recommendation") == r["outcome_label"]),
            "near_miss": bool(rr["near_miss"]),
            "policy_version": pol.policy_version,
            "routed_to": pol.routed_to,
            "counterfactual_check": pol.counterfactual_check,
            "n_tool_calls": len(traj),
            "tools_used": "|".join(traj),
            "agent_reasoning": agent_out.get("reasoning"),
        })

    if failures:
        pd.DataFrame(failures).to_csv("outputs/arm_failures.csv", index=False)
        print(f"    {len(failures)} case(s) failed — see outputs/arm_failures.csv",
              flush=True)
    return pd.DataFrame(rows), trajectories


# ------------------------------------------------------------------ metrics
def arm_scores(res):
    a_cov = res["A_confident"].mean()
    a_acc = res.loc[res["A_confident"], "A_correct"].mean() if res["A_confident"].any() else np.nan
    acted = res["C_acted"]
    return {
        "n_cases": int(len(res)),
        "arm_A_coverage": round(float(a_cov), 4),
        "arm_A_accuracy_on_covered": round(float(a_acc), 4) if not np.isnan(a_acc) else None,
        "arm_A_accuracy_overall": round(float(res["A_correct"].mean()), 4),
        "arm_B_accuracy": round(float(res["B_correct"].mean()), 4),
        "arm_C_automation_rate": round(float(acted.mean()), 4),
        "arm_C_precision_on_acted": (round(float(res.loc[acted, "C_correct_when_acted"].mean()), 4)
                                     if acted.any() else None),
        "arm_C_false_automation_rate": (round(float(1 - res.loc[acted, "C_correct_when_acted"].mean()), 4)
                                        if acted.any() else None),
        "arm_C_escalation_rate": round(float((res["C_decision"] == P.ESCALATE).mean()), 4),
        "arm_C_approval_rate": round(float((res["C_decision"] == P.HUMAN_APPROVAL).mean()), 4),
    }


def precision_by_class(res):
    acted = res[res["C_acted"]]
    if acted.empty:
        return pd.DataFrame(columns=["exception_class", "n_acted", "precision"])
    g = acted.groupby("exception_class_derived")["C_correct_when_acted"]
    out = pd.DataFrame({"n_acted": g.size(), "precision": g.mean()}).reset_index()
    return out.rename(columns={"exception_class_derived": "exception_class"})


def find_demotion(prec, threshold=None, min_n=10):
    """
    Stage 4's primary story. Returns the class to demote, or None.
    If nothing falls below threshold, do NOT manufacture a demotion — report
    where the boundary sits instead (see sensitivity_curve).
    """
    threshold = threshold or C.PRECISION_THRESHOLD
    cand = prec[(prec["precision"] < threshold) & (prec["n_acted"] >= min_n)]
    if cand.empty:
        return None
    row = cand.sort_values("precision").iloc[0]
    return {"exception_class": row["exception_class"],
            "precision": round(float(row["precision"]), 4),
            "n_acted": int(row["n_acted"]), "threshold": threshold}


def candidate_precision(res):
    """
    Precision the agent WOULD achieve on each exception class if it were
    permitted to act — independent of what the current matrix allows.

    This is the input to the sensitivity curve. Sweeping only over classes the
    matrix already permits produces a flat, useless curve: the question a CFO
    is actually asking is "which classes could we let through, and at what
    precision", not "how do the ones we already trust perform".
    """
    g = res.groupby("exception_class_derived")["B_correct"]
    out = pd.DataFrame({"n_cases": g.size(), "precision": g.mean()}).reset_index()
    return out.rename(columns={"exception_class_derived": "exception_class"})


def sensitivity_curve(res, sweep=None, min_n=10):
    """
    Automation rate vs precision across candidate thresholds. The best single
    exhibit in the project: it shows a trade-off, not a result. It tells a CFO
    exactly how much automation they give up per point of precision demanded.

    At each threshold, every class whose achieved precision meets it becomes
    eligible for autonomous action; classes below it fall back to human
    authority. Classes with n below min_n are never permitted regardless of
    precision — thin samples do not buy autonomy.
    """
    sweep = sweep or C.SENSITIVITY_SWEEP
    cand = candidate_precision(res)
    rows = []
    for t in sweep:
        ok = cand[(cand["precision"] >= t) & (cand["n_cases"] >= min_n)]
        allowed = set(ok["exception_class"])
        elig = res["exception_class_derived"].isin(allowed)
        # value cap still binds: autonomy is class AND value, never class alone
        within_cap = res["exposure_eur"].fillna(0) <= C.AUTO_RESOLVE_VALUE_CAP
        acted = elig & within_cap
        below = cand[(cand["n_cases"] >= min_n) & (cand["precision"] < t)]
        rows.append({
            "precision_threshold": t,
            "classes_permitted": len(allowed),
            "permitted_classes": "|".join(sorted(allowed)),
            "automation_rate": round(float(acted.mean()), 4),
            "n_automated": int(acted.sum()),
            "realised_precision": (round(float(res.loc[acted, "B_correct"].mean()), 4)
                                   if acted.any() else None),
            "value_automated_eur": round(float(res.loc[acted, "exposure_eur"].sum()), 2),
            "binding_constraint": (below.sort_values("precision", ascending=False)
                                   ["exception_class"].iloc[0] if not below.empty else None),
        })
    return pd.DataFrame(rows)


def tool_metrics(trajectories, expected):
    """Recall and precision of tool selection against the frozen expectation."""
    rec, pre, per_tool = [], [], {}
    for cid, exp in expected.items():
        got = set(trajectories.get(cid, []))
        exp = set(exp)
        if exp:
            rec.append(len(got & exp) / len(exp))
        if got:
            pre.append(len(got & exp) / len(got))
        for t in got:
            per_tool[t] = per_tool.get(t, 0) + 1
    return {"n_graded": len(rec),
            "tool_recall": round(float(np.mean(rec)), 4) if rec else None,
            "tool_precision": round(float(np.mean(pre)), 4) if pre else None,
            "call_counts": per_tool,
            "never_called": [t for t in
                             ["get_invoice", "lookup_po", "lookup_goods_receipt",
                              "check_duplicate_payment", "lookup_vendor_history",
                              "lookup_policy"] if t not in per_tool]}


def disagreement_sample(res, n=30, seed=None):
    """
    Required deliverable. Cases where the agent diverged from the historically
    observed outcome, sampled for hand inspection. The classification column is
    left EMPTY on purpose — it is filled by hand, not by code. That is the whole
    value of the exercise.
    """
    d = res[~res["B_correct"]].copy()
    if d.empty:
        return d
    d = d.sample(min(n, len(d)), random_state=seed or C.RANDOM_SEED)
    d["manual_classification"] = ""   # agent_wrong | agent_defensible | undeterminable
    d["inspector_note"] = ""
    cols = ["case_id", "exception_class_derived", "abs_variance_pct", "exposure_eur",
            "outcome_label", "B_prediction", "B_confidence", "tools_used",
            "agent_reasoning", "manual_classification", "inspector_note"]
    return d[cols]


def final_classification(res):
    """
    Mechanical bucketing. Cases where both rules and agent succeeded go in the
    RULES bucket — deliberately conservative toward the AI.
    """
    def bucket(r):
        if r["A_correct"]:
            return "rules_sufficient"
        if not r["A_confident"] and r["B_correct"]:
            return "ai_added_value"
        return "human_necessary"
    return res.assign(final_bucket=res.apply(bucket, axis=1))


def vendor_concentration(f, top=15):
    """
    Supply-chain surface layer. Exception concentration by vendor, using fields
    already in the log. A concentrated tail is a supplier-management finding, not
    a technical one.
    """
    if "vendor" not in f.columns or f["vendor"].isna().all():
        return pd.DataFrame()
    g = f.groupby("vendor")
    out = pd.DataFrame({
        "n_cases": g.size(),
        "block_rate": g["was_blocked"].mean(),
        "mean_abs_variance_pct": g["abs_variance_pct"].mean(),
        "exposure_eur": g["exposure_eur"].sum(),
        "blocked_exposure_eur": f[f["was_blocked"]].groupby("vendor")["exposure_eur"].sum(),
    }).fillna(0).sort_values("blocked_exposure_eur", ascending=False)
    out["cum_share_of_blocked_exposure"] = (out["blocked_exposure_eur"].cumsum()
                                            / out["blocked_exposure_eur"].sum())
    return out.head(top).reset_index()
