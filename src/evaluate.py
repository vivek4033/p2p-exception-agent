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
import evidence as EV
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
def run_arms(ev, mock=True, verbose=True, matrix=None, policy_version=None, events=None):
    box = ToolBox(ev, events=events)
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

        agent_exposure = agent_out.get("exposure_eur")
        agent_value_contradictions = EV.exposure_contradictions(
            agent_exposure, r["exposure_eur"])
        pol = P.decide(
            cid,
            agent_out.get("exception_type") or r["exception_class"],
            r["exposure_eur"],
            evidence_level=(ev := EV.evaluate_evidence(
                agent_out.get("exception_type") or r["exception_class"],
                agent_out.get("_tool_outputs", {}), bool(rr["near_miss"]),
                additional_contradictions=agent_value_contradictions))['evidence_level'],
            near_miss=bool(rr["near_miss"]),
            missing_sources=ev["missing_sources"],
            contradictions=ev["contradictions"],
            matrix=matrix,
            policy_version=policy_version,
            confidence=agent_out.get("confidence"),
            recommendation=agent_out.get("recommendation"),
        )

        rows.append({
            "case_id": cid,
            "decision_time": str(box.decision_time(cid)),
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
            "B_exposure_eur": agent_exposure,
            "evidence_level": ev["evidence_level"],
            "missing_sources": "|".join(ev["missing_sources"]),
            "contradictions": "|".join(ev["contradictions"]),
            "B_correct": agent_out.get("recommendation") == r["outcome_label"],
            # Arm C
            "C_decision": pol.decision,
            "C_human_review": pol.decision == P.HUMAN_APPROVAL,
            "near_miss": bool(rr["near_miss"]),
            "policy_version": pol.policy_version,
            "routed_to": pol.routed_to,
            "counterfactual_check": pol.counterfactual_check,
            "rule_fired": pol.rule_fired,
            "n_tool_calls": len(traj),
            "tools_used": "|".join(traj),
            "tools_called": "|".join(traj),
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
    return {
        "n_cases": int(len(res)),
        "arm_A_coverage": round(float(a_cov), 4),
        "arm_A_accuracy_on_covered": round(float(a_acc), 4) if not np.isnan(a_acc) else None,
        "arm_A_accuracy_overall": round(float(res["A_correct"].mean()), 4),
        "arm_B_accuracy": round(float(res["B_correct"].mean()), 4),
        "arm_C_human_review_rate": round(float(res["C_human_review"].mean()), 4),
        "arm_C_escalation_rate": round(float((res["C_decision"] == P.ESCALATE).mean()), 4),
    }


def precision_by_class(res):
    g = res.groupby("exception_class_derived")["B_correct"]
    out = pd.DataFrame({"n_cases": g.size(), "recommendation_accuracy": g.mean()}).reset_index()
    return out.rename(columns={"exception_class_derived": "exception_class"})


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
