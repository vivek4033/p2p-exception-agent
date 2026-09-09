"""Run the evidence-to-owner workflow on a bounded real-log sample."""

import html
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, "src")
import config as C
import data
import labels as L
import policy_engine as P

SAMPLE_CASES = 5000
SOURCE = Path(C.PARQUET_PATH)
SAMPLE_PATH = Path("data/sample_5000.parquet")
QUEUE_PATH = Path("outputs/sample_case_queue.csv")
SUMMARY_PATH = Path("outputs/sample_summary.csv")
DASHBOARD_PATH = Path("docs/sample_dashboard.html")


def esc(value):
    return html.escape(str(value))


def make_sample():
    columns = [C.CASE_COL, C.ACT_COL, C.TS_COL, C.VALUE_COL,
               C.GR_EXPECTED_COL, "case:Purchasing Document"]
    parquet = pq.ParquetFile(SOURCE)
    frames = []
    seen = []
    seen_set = set()
    for batch in parquet.iter_batches(batch_size=100000, columns=columns):
        frame = batch.to_pandas()
        for case_id in frame[C.CASE_COL].drop_duplicates():
            if case_id not in seen_set:
                seen_set.add(case_id)
                seen.append(case_id)
                if len(seen) == SAMPLE_CASES:
                    break
        frames.append(frame)
        if len(seen) >= SAMPLE_CASES:
            break
    sample = pd.concat(frames, ignore_index=True)
    sample = sample[sample[C.CASE_COL].isin(seen[:SAMPLE_CASES])].copy()
    SAMPLE_PATH.parent.mkdir(exist_ok=True)
    sample.to_parquet(SAMPLE_PATH, index=False)
    return sample


def recommendation(row):
    cls = row["exception_class"]
    actions = {
        L.PRIOR_AMENDMENT: ("Procurement", "Confirm the PO amendment was approved before invoice receipt.", P.HUMAN_APPROVAL),
        L.GR_IR_MISMATCH: ("Warehouse / Goods Receiving", "Confirm physical quantity received versus invoice quantity.", P.HUMAN_APPROVAL),
        L.SEQUENCE_VIOLATION: ("AP Team Lead", "Check whether delivery occurred before the GR was posted.", P.HUMAN_APPROVAL),
        L.DUPLICATE: ("AP Manager", "Confirm whether repeated invoice receipts represent a duplicate payment risk.", P.ESCALATE),
        L.MISSING_GR: ("Procurement", "Obtain or confirm the expected goods receipt before release.", P.ESCALATE),
        L.NO_EXCEPTION: ("AP Automation", "No structural irregularity found in the available prefix evidence.", P.AUTO_RESOLVE),
    }
    owner, action, decision = actions[cls]
    if decision == P.AUTO_RESOLVE and float(row.get("exposure_eur") or 0) > C.AUTO_RESOLVE_VALUE_CAP:
        owner, action, decision = "AP Approver", "Review exposure above the autonomous action cap.", P.HUMAN_APPROVAL
    return owner, action, decision


def build_dashboard(queue, sample, stage):
    display_parts = [queue[queue["decision"] == decision].head(20)
                     for decision in [P.ESCALATE, P.HUMAN_APPROVAL, P.AUTO_RESOLVE]]
    display_queue = pd.concat(display_parts).reset_index(drop=True)
    rows = []
    for i, (_, row) in enumerate(display_queue.iterrows()):
        decision = row["decision"]
        status = esc(decision.replace("_", " ").title())
        problem = esc(row["exception_class"].replace("_", " ").title())
        rows.append(
            f"<tr class='case-row' data-status='{esc(decision)}' data-case='{i}'>"
            f"<td class='order'>{esc(row['sap_order_id'])}</td><td>{problem}</td>"
            f"<td><span class='status {esc(decision)}'>{status}</span></td>"
            f"<td>{esc(row['owner'])}</td><td>{esc(row['recommendation'])}</td>"
            f"<td class='money'>{float(row['exposure_eur']):,.0f}</td></tr>"
            f"<tr class='detail' id='detail-{i}'><td colspan='6'><div class='detail-grid'>"
            f"<div><span>Problem</span><b>{problem}</b></div><div><span>Owner</span><b>{esc(row['owner'])}</b></div>"
            f"<div><span>Decision</span><b>{status}</b></div><div><span>Next action</span><b>{esc(row['recommendation'])}</b></div>"
            f"</div><p><b>Evidence:</b> prefix activity evidence from the SAP event log. "
            f"This is a recommended owner action, not a causal finding or SAP write-back.</p></td></tr>"
        )
    counts = queue["decision"].value_counts().to_dict()
    summary = " ".join(f"<span class='summary {esc(k)}'><b>{esc(k.replace('_', ' ').title())}</b><strong>{v:,}</strong></span>" for k, v in counts.items())
    html_page = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>SAP Exception Work Queue - Illustrative Sample</title><style>
body{{margin:0;background:#eef2f1;color:#182126;font:15px/1.45 Arial,sans-serif}}main{{max-width:1250px;margin:auto;padding:38px 22px 70px}}h1{{font:600 34px Georgia,serif}}h2{{margin-top:36px;border-bottom:1px solid #cfd8d5;padding-bottom:8px}}.stamp{{color:#647177;font-size:13px}}.hero{{background:#173e43;color:#f5fbf8;border-radius:12px;padding:26px 30px;margin:22px 0;box-shadow:0 8px 24px #173e4320}}.hero b{{font-size:30px;color:#b9eee0}}.facts{{display:flex;gap:10px;flex-wrap:wrap}}.fact{{background:#fff;padding:15px 20px;border:1px solid #d5dfdc;border-radius:8px;min-width:150px}}.fact b{{display:block;font-size:22px;color:#173e43}}.summary{{display:inline-flex;flex-direction:column;gap:3px;margin:18px 8px 4px 0;padding:12px 18px;border-radius:8px;background:#fff;border:1px solid #d5dfdc}}.summary strong{{font-size:25px}}.summary.ESCALATE{{border-left:5px solid #bd583d}}.summary.HUMAN_APPROVAL{{border-left:5px solid #bd8b3d}}.summary.AUTO_RESOLVE{{border-left:5px solid #398267}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}}.filter{{border:1px solid #b9c8c4;background:#fff;border-radius:99px;padding:9px 15px;cursor:pointer}}.filter.active{{background:#173e43;color:#fff}}table{{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border:1px solid #d5dfdc;border-radius:10px;overflow:hidden}}th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid #e1e8e5;vertical-align:top}}th{{color:#5d6b72;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}.order{{font-family:ui-monospace,monospace;color:#1f5f64;font-weight:600}}.money{{text-align:right;font-variant-numeric:tabular-nums}}.status{{display:inline-block;padding:5px 9px;border-radius:99px;font-size:12px;font-weight:700}}.status.ESCALATE{{background:#f8dfd8;color:#8b3725}}.status.HUMAN_APPROVAL{{background:#faedcf;color:#8b6420}}.status.AUTO_RESOLVE{{background:#dff1e8;color:#24634e}}.case-row{{cursor:pointer}}.case-row:hover{{background:#f2f8f5}}.detail{{display:none;background:#f7faf8}}.detail td{{padding:18px 22px;color:#42534f}}.detail-grid{{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:14px}}.detail-grid span{{display:block;color:#71827e;font-size:11px;text-transform:uppercase}}.detail-grid b{{display:block;margin-top:4px}}.note{{background:#fff4df;border-left:4px solid #bd7b25;padding:12px 15px;border-radius:5px}}
</style></head><body><main><p class='stamp'>Illustrative sample: {len(sample):,} of 251,734 cases from {esc(SOURCE)} | Stage: {stage}</p><h1>Work queue — illustrative sample ({len(sample):,} of 251,734 cases)</h1>
<div class='hero'><b>What needs attention now?</b><p>Click any case to open its owner, decision, and next action. Filter the queue by authority status. Policy tier assignment is shown before precision demotion; the full experiment permits 7.5% automation at 90–93% precision and none at 95%.</p><p><strong>Agent mode:</strong> deterministic stand-in — not an AI result. This sample demonstrates routing and evidence presentation, not measured model performance or live SAP write-back.</p></div>
<div class='facts'><div class='fact'><b>{len(sample):,}</b>events</div><div class='fact'><b>{len(queue):,}</b>evaluable cases</div><div class='fact'><b>{queue['exception_class'].nunique()}</b>problem classes</div></div><div>{summary}</div>
<h2>Owner queue</h2><div class='filters'><button class='filter active' data-filter='ALL'>All cases</button><button class='filter' data-filter='ESCALATE'>Escalate</button><button class='filter' data-filter='HUMAN_APPROVAL'>Human approval</button><button class='filter' data-filter='AUTO_RESOLVE'>Auto resolve</button></div><table><thead><tr><th>SAP order ID</th><th>Problem</th><th>Decision</th><th>Owner</th><th>Recommended next action</th><th>Exposure EUR</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class='note'>Showing 20 cases per status so the work mix is visible. Click a row for details. Full queue: <code>outputs/sample_case_queue.csv</code>.</p><script>document.querySelectorAll('.case-row').forEach(function(row){{row.addEventListener('click',function(){{var d=document.getElementById('detail-'+row.dataset.case);d.style.display=d.style.display==='table-row'?'none':'table-row';}});}});document.querySelectorAll('.filter').forEach(function(button){{button.addEventListener('click',function(){{document.querySelectorAll('.filter').forEach(function(x){{x.classList.remove('active');}});button.classList.add('active');var f=button.dataset.filter;document.querySelectorAll('.case-row').forEach(function(row){{var show=f==='ALL'||row.dataset.status===f;row.style.display=show?'table-row':'none';var d=document.getElementById('detail-'+row.dataset.case);if(!show)d.style.display='none';}});}});}});</script></main></body></html>"""
    DASHBOARD_PATH.parent.mkdir(exist_ok=True)
    DASHBOARD_PATH.write_text(html_page, encoding="utf-8")


def main():
    sample = make_sample()
    original_path = C.PARQUET_PATH
    C.PARQUET_PATH = str(SAMPLE_PATH)
    features = data.case_features(None, with_variants=False)
    features = L.build(features, None)
    features, exclusion = L.analysis_population(features)
    queue = features.copy()
    po = sample.groupby(C.CASE_COL)["case:Purchasing Document"].first()
    queue["sap_order_id"] = queue["case_id"].map(po).fillna(queue["case_id"])
    decisions = queue.apply(recommendation, axis=1, result_type="expand")
    decisions.columns = ["owner", "recommendation", "decision"]
    queue = pd.concat([queue, decisions], axis=1)
    queue = queue.sort_values(["decision", "exposure_eur"], ascending=[True, False])
    QUEUE_PATH.parent.mkdir(exist_ok=True)
    queue.to_csv(QUEUE_PATH, index=False)
    SUMMARY_PATH.write_text(pd.DataFrame([{
        "sample_cases": len(sample[C.CASE_COL].unique()),
        "sample_events": len(sample),
        "evaluable_cases": len(queue),
        "excluded_non_terminal": exclusion.get("excluded_non_terminal", 0),
        "problem_classes": queue["exception_class"].nunique(),
        "stage": "sample taxonomy + owner/action policy",
    }]).to_csv(index=False), encoding="utf-8")
    build_dashboard(queue, sample, "sample taxonomy + owner/action policy")
    C.PARQUET_PATH = original_path
    print(f"SAMPLE EVENTS: {len(sample):,}")
    print(f"SAMPLE CASES: {sample[C.CASE_COL].nunique():,}")
    print(f"EVALUABLE CASES: {len(queue):,}")
    print(f"EXCLUDED NON-TERMINAL: {exclusion.get('excluded_non_terminal', 0):,}")
    print(f"WROTE: {QUEUE_PATH}")
    print(f"WROTE: {DASHBOARD_PATH}")


if __name__ == "__main__":
    main()
