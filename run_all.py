"""
run_all.py — one command, Stage 0 through Stage 5.

    python run_all.py            # mock agent, free, proves the pipeline
    python run_all.py --live     # real Claude API, cached to disk

Writes every artifact the deck and the dashboards need into outputs/ and docs/.
Every file carries a data-source stamp so synthetic numbers can never be
mistaken for reportable ones.
"""

import json
import gc
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import config as C          # noqa: E402
import data                 # noqa: E402
import labels as L          # noqa: E402
import policy_engine as P   # noqa: E402
import evaluate as E        # noqa: E402
import value_model as V     # noqa: E402
import case_packet as CP    # noqa: E402
import rules_engine as R    # noqa: E402
import agent as AG          # noqa: E402
from tools import ToolBox   # noqa: E402

MOCK = "--live" not in sys.argv
FINDINGS = []


def log(name, value, stage):
    """Guardrail 6: log the number the moment it is produced."""
    FINDINGS.append({"stage": stage, "metric": name, "value": value})
    print(f"  {name}: {value}")


def hr(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main():
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("docs", exist_ok=True)

    print(f"DATA SOURCE: {C.stamp()}")
    print(f"AGENT MODE : {'MOCK (no API calls, no cost)' if MOCK else 'LIVE Claude API'}")

    # ---------------------------------------------------------------- STAGE 0
    hr("STAGE 0 — Reconnaissance")
    if C.DATA_SOURCE != "synthetic" and os.path.exists(C.PARQUET_PATH):
        n_events, n_cases, n_activities, activity_names = data.parquet_stage0(C.PARQUET_PATH)
        log("events", n_events, 0)
        log("cases", n_cases, 0)
        log("distinct_activities", n_activities, 0)
        audit = L.audit_taxonomy_names(activity_names)
        df = None
    else:
        df = data.load_log()
        log("events", len(df), 0)
        log("cases", df[C.CASE_COL].nunique(), 0)
        log("distinct_activities", df[C.ACT_COL].nunique(), 0)
        audit = L.audit_taxonomy(df)
    print(f"  taxonomy audit: {audit['action_required']}")
    if audit["configured_not_found"]:
        print(f"  MISSING ACTIVITY NAMES: {audit['configured_not_found']}")

    # ---------------------------------------------------------------- STAGE 1
    hr("STAGE 1 — Baseline and taxonomy")
    del df
    gc.collect()
    f = data.case_features(None, with_variants=False)
    f = L.build(f, None)

    if "variant" in f.columns:
        log("variants", f["variant"].nunique(), 1)
        log("top5_variant_coverage_pct", round(100 * f["variant"].value_counts()
                                               .head(5).sum() / len(f), 2), 1)
    log("touchless_rate_pct", round(100 * (f["human_touches"] == 0).mean(), 2), 1)
    log("blocked_rate_pct", round(100 * f["was_blocked"].mean(), 2), 1)
    log("mean_cycle_days", round(float(f["cycle_days"].mean()), 2), 1)
    log("median_cycle_days", round(float(f["cycle_days"].median()), 2), 1)
    log("mean_block_to_resolution_days",
        round(float(f["block_to_resolution_days"].mean()), 2), 1)
    log("exception_classes", int(f["exception_class"].nunique()), 1)

    # Stage 1 scope decision, taken on evidence and reported
    f_all = f
    f, excl = L.analysis_population(f)
    for k, v in excl.items():
        if k != "rule":
            log(f"population_{k}", v, 1)
    print(f"  EXCLUSION RULE: {excl['rule']}")
    if "gr_expectation_source" in f_all.columns:
        n_no_gr = int((~f_all["has_gr"]).sum())
        n_exc = int((f_all["gr_expected"] & ~f_all["has_gr"]).sum())
        log("cases_without_goods_receipt", n_no_gr, 1)
        log("of_which_gr_was_expected", n_exc, 1)
        log("gr_expectation_source", f_all["gr_expectation_source"].iloc[0], 1)
        print(f"  {n_no_gr - n_exc:,} no-GR cases are legitimate no-GR flows, "
              f"NOT exceptions")
        # sanity check: is gr_expected real, or is it mirroring the events?
        ct = pd.crosstab(f_all["gr_expected"], [f_all["has_gr"], f_all["terminal"]])
        print("\n  GR EXPECTATION SANITY CHECK  (rows: gr_expected)")
        print("  columns: has_gr / terminal")
        print("  " + ct.to_string().replace("\n", "\n  "))
        print("  If the gr_expected=False row is ~identical to the has_gr=False")
        print("  column, the field mirrors the events and is circular — say so.")

    leak = L.leakage_check(f)
    log("max_class_to_label_concentration", leak["max_class_to_label_concentration"], 1)
    print(f"  LEAKAGE CHECK: {'SUSPECTED — investigate' if leak['leak_suspected'] else 'clean'}"
          f" (worst class: {leak['class']})")

    gate = L.label_coverage_report(f)
    log("label_derivable_on_blocked_pct", gate["derivable_on_blocked_pct"], 1)
    print(f"  LABEL GATE: {'PASSED' if gate['gate_passed'] else 'FAILED — narrow scope'}")

    exc = (f.groupby("exception_class")
           .agg(n_cases=("case_id", "size"),
                mean_cycle_days=("cycle_days", "mean"),
                mean_abs_variance_pct=("abs_variance_pct", "mean"),
                exposure_eur=("exposure_eur", "sum"),
                block_rate=("was_blocked", "mean"))
           .reset_index())
    exc["cost_of_deviation_days"] = exc["n_cases"] * exc["mean_cycle_days"]
    exc = exc.sort_values("cost_of_deviation_days", ascending=False)
    exc.to_csv("outputs/exception_summary.csv", index=False)
    print("\n" + exc.to_string(index=False))

    vend = E.vendor_concentration(f)
    if not vend.empty:
        vend.to_csv("outputs/vendor_concentration.csv", index=False)
        top5 = float(vend["cum_share_of_blocked_exposure"].iloc[min(4, len(vend) - 1)])
        log("top5_vendor_share_of_blocked_exposure_pct", round(100 * top5, 2), 1)

    # ---------------------------------------------------------------- STAGE 2
    hr("STAGE 2 — Rules baseline, governance, frozen eval set")
    ev = E.build_eval_set(f)
    log("eval_set_size", len(ev), 2)
    expected = E.freeze_expected_tools(ev)
    log("expected_tools_frozen_for_cases", len(expected), 2)

    with open("docs/decision_rights.md", "w") as fh:
        fh.write(P.matrix_to_markdown(P.MATRIX_V1_0, "v1.0") +
                 f"\n\n_Data source: {C.stamp()}_\n")
    print("  wrote docs/decision_rights.md (v1.0)")

    # ---------------------------------------------------------------- STAGE 3
    hr("STAGE 3 — Three arms")
    res, traj = E.run_arms(ev, mock=MOCK)
    scores = E.arm_scores(res)
    for k, v in scores.items():
        log(k, v, 3)

    tm = E.tool_metrics(traj, expected)
    log("tool_recall", tm["tool_recall"], 3)
    log("tool_precision", tm["tool_precision"], 3)
    if tm["never_called"]:
        print(f"  GUARDRAIL 10: never called -> {tm['never_called']} — cut or justify")

    # ---------------------------------------------------------------- STAGE 4
    hr("STAGE 4 — Measurement and tightening")
    prec = E.precision_by_class(res)
    print(prec.to_string(index=False))
    prec.to_csv("outputs/precision_by_class.csv", index=False)

    dem = E.find_demotion(prec)
    matrix, version = P.MATRIX_V1_0, "v1.0"
    if dem:
        print(f"\n  DEMOTION: {dem['exception_class']} precision "
              f"{dem['precision']:.3f} < {dem['threshold']} (n={dem['n_acted']})")
        matrix = P.demote(P.MATRIX_V1_0, dem["exception_class"],
                          reason=f"precision {dem['precision']:.3f} on n={dem['n_acted']} "
                                 f"below the {dem['threshold']} pilot threshold")
        version = "v1.1"
        res2, _ = E.run_arms(ev, mock=MOCK)
        given_up = int((res["C_acted"] & (res["exception_class_derived"]
                                          == dem["exception_class"])).sum())
        log("demoted_class", dem["exception_class"], 4)
        log("demoted_class_precision", dem["precision"], 4)
        log("automated_resolutions_given_up", given_up, 4)
        with open("docs/decision_rights.md", "w") as fh:
            fh.write(P.matrix_to_markdown(matrix, version) +
                     f"\n\n_Data source: {C.stamp()}_\n")
    else:
        print("\n  No class below threshold. Do NOT manufacture a demotion — "
              "report where the boundary sits instead (see sensitivity curve).")
        log("demotion_found", False, 4)

    sens = E.sensitivity_curve(res)
    sens.to_csv("outputs/threshold_sensitivity.csv", index=False)
    print("\n" + sens.to_string(index=False))

    dis = E.disagreement_sample(res)
    dis.to_csv("outputs/disagreement_sample.csv", index=False)
    log("disagreements_sampled_for_hand_inspection", len(dis), 4)
    print(f"  wrote outputs/disagreement_sample.csv — "
          f"{len(dis)} cases, manual_classification column left EMPTY on purpose")

    res = E.final_classification(res)
    buckets = res["final_bucket"].value_counts(normalize=True).round(4).to_dict()
    for k, v in buckets.items():
        log(f"bucket_{k}_pct", round(100 * v, 2), 4)
    res.to_csv("outputs/case_results.csv", index=False)

    # ---------------------------------------------------------------- STAGE 5
    hr("STAGE 5 — Findings log")
    fl = pd.DataFrame(FINDINGS)
    fl["data_source"] = C.stamp()
    fl.to_csv("outputs/findings_log.csv", index=False)

    with open("docs/findings_log.md", "w") as fh:
        fh.write(f"# Findings Log\n\n**Data source: {C.stamp()}**\n\n")
        fh.write("| Stage | Metric | Value |\n|---|---|---|\n")
        for r in FINDINGS:
            fh.write(f"| {r['stage']} | `{r['metric']}` | {r['value']} |\n")

    # sample case packets — the human-facing deliverable, incl. counterparty routing
    box = ToolBox(ev)
    samples = []
    for cls in [L.PRICE_OVER_TOL, L.QTY_VARIANCE, L.DUPLICATE, L.SEQUENCE_VIOLATION]:
        sub = ev[ev["exception_class"] == cls]
        if sub.empty:
            continue
        row = sub.iloc[0]
        a, tj = AG.investigate(row["case_id"], box, mock=MOCK)
        a["_tools"] = tj
        rr = R.evaluate_case(row)
        pol = P.decide(row["case_id"], a.get("exception_type") or cls, row["exposure_eur"],
                       a.get("confidence"), bool(a.get("evidence_complete")), rr.near_miss,
                       matrix=matrix, policy_version=version)
        samples.append(CP.render_text(CP.build(row, a, pol, rr.trace)))
    if samples:
        with open("outputs/case_packets_sample.txt", "w") as fh:
            fh.write(f"Data source: {C.stamp()}\n\n" + ("\n\n" + "#" * 72 + "\n\n").join(samples))
        log("case_packets_generated", len(samples), 5)

    hr("STAGE 5 — Business case")
    V.run(res, sens)

    print("\nOutputs:")
    for p in sorted(os.listdir("outputs")):
        if p.endswith((".csv", ".json", ".txt")):
            print(f"  outputs/{p}")
    for p in sorted(os.listdir("docs")):
        print(f"  docs/{p}")
    print(f"\nDATA SOURCE: {C.stamp()}")


if __name__ == "__main__":
    main()
