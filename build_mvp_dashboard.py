"""Build a direct-data MVP dashboard without the unfinished three-arm run."""

import html
import os

import pandas as pd

import sys
sys.path.insert(0, "src")
import config as C


OUT = "docs/index.html"


def esc(value):
    return html.escape(str(value))


def main():
    columns = [C.CASE_COL, C.ACT_COL, C.TS_COL, C.GOODS_RECEIPT_COL,
               C.ITEM_CATEGORY_COL, C.A_INVOICE_RECEIPT, C.A_CLEAR_INVOICE]
    columns = list(dict.fromkeys(c for c in columns if c))
    events = pd.read_parquet(C.PARQUET_PATH)
    cases = events.groupby(C.CASE_COL, sort=False)
    case_ids = events[C.CASE_COL].drop_duplicates()

    activities = events[C.ACT_COL].value_counts()
    has = lambda names: set(events.loc[events[C.ACT_COL].isin(names), C.CASE_COL])
    blocked = has([C.A_SET_BLOCK]) | has([C.A_REMOVE_BLOCK])
    removed = has([C.A_REMOVE_BLOCK])
    cancelled = has([C.A_CANCEL_INVOICE])
    cleared = has([C.A_CLEAR_INVOICE])
    terminal = cleared | removed | cancelled

    gr_expected = (events.groupby(C.CASE_COL)[C.GOODS_RECEIPT_COL].first()
                   .astype(str).str.lower().isin(["true", "1", "yes"]))
    has_gr = set(events.loc[events[C.ACT_COL].isin(C.GR_ACTS), C.CASE_COL])
    expected_missing_gr = set(gr_expected[gr_expected].index) - has_gr
    no_gr = set(case_ids) - has_gr

    invoice_counts = (events[events[C.ACT_COL] == C.A_INVOICE_RECEIPT]
                      .groupby(C.CASE_COL).size())
    duplicate = set(invoice_counts[invoice_counts > 1].index)

    rows = [
        ("Payment block inferred", len(blocked), "Remove Payment Block or Set Payment Block"),
        ("Missing goods receipt", len(expected_missing_gr), "Receipt expected, but no GR event"),
        ("Quantity-change pattern", len(has(C.QTY_CHANGE_ACTS)), "Change Quantity event"),
        ("Price-change pattern", len(has(C.PRICE_CHANGE_ACTS)), "Change Price event"),
        ("Duplicate-payment pattern", len(duplicate), "Repeated invoice receipt"),
        ("Cancelled invoice", len(cancelled), "Cancel Invoice Receipt event"),
    ]
    table = "".join(
        f"<tr><th>{esc(name)}</th><td>{count:,}</td><td>{esc(rule)}</td></tr>"
        for name, count, rule in rows)
    activity_table = "".join(
        f"<tr><th>{esc(name)}</th><td>{count:,}</td></tr>"
        for name, count in activities.head(12).items())

    stamp = "BPI Challenge 2019 (real parquet)"
    html_page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>P2P Exception Autonomy — MVP</title>
<style>
:root {{ --ink:#182126; --muted:#5d6b72; --paper:#f5f3ed; --card:#fff; --line:#d7d8d2; --accent:#1f5f64; --warn:#9d4d32; }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 Georgia,serif }}
main {{ max-width:900px; margin:auto; padding:48px 24px 80px }} h1 {{ font-size:36px; line-height:1.1; max-width:720px }}
h2 {{ margin-top:44px; border-bottom:1px solid var(--line); padding-bottom:8px }} p {{ max-width:72ch }}
.stamp,.muted {{ color:var(--muted); font:14px/1.4 Arial,sans-serif }} .hero {{ background:var(--card); border-left:6px solid var(--accent); padding:24px; margin:28px 0 }}
.hero b {{ display:block; font:600 48px/1 Arial,sans-serif; color:var(--accent) }} .facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:1px; background:var(--line) }}
.fact {{ background:var(--card); padding:18px }} .fact b {{ display:block; font:600 25px Arial,sans-serif }} table {{ width:100%; border-collapse:collapse; background:var(--card); font-family:Arial,sans-serif }}
th,td {{ text-align:left; padding:10px; border-bottom:1px solid var(--line) }} td {{ text-align:right }} th:last-child {{ font-weight:400; color:var(--muted) }}
.pending {{ background:#fff4df; border-left:4px solid #bd7b25; padding:14px 16px; font-family:Arial,sans-serif }}
footer {{ margin-top:56px; color:var(--muted); font:13px Arial,sans-serif }}
</style></head><body><main>
<p class="stamp">Data source: {stamp} · Generated from {esc(C.PARQUET_PATH)}</p>
<h1>Where should AI autonomy stop in P2P exception management?</h1>
<p>This MVP is the evidence layer: it shows what the real event log supports before making claims about agent accuracy or autonomous resolution.</p>
<div class="hero"><b>22.22%</b><p>of PO line-item cases show an inferred payment block, based on a block-set or block-removal event.</p></div>
<div class="facts">
<div class="fact"><b>{len(events):,}</b><span>events</span></div><div class="fact"><b>{len(case_ids):,}</b><span>PO line items</span></div>
<div class="fact"><b>{len(activities)}</b><span>activities</span></div><div class="fact"><b>{len(terminal):,}</b><span>terminal cases</span></div>
<div class="fact"><b>{len(case_ids)-len(terminal):,}</b><span>non-terminal excluded</span></div>
</div>
<h2>What the system can recommend now</h2>
<p>These are deterministic activity-pattern recommendations, not measured AI outcomes. They are suitable for a rules-first review queue and a later shadow-mode experiment.</p>
<table><thead><tr><th>Pattern</th><th>Cases</th><th>Evidence rule</th></tr></thead><tbody>{table}</tbody></table>
<h2>Goods-receipt decision</h2>
<p>{len(no_gr):,} cases have no goods-receipt event. The log's expectation flag identifies {len(expected_missing_gr):,} cases where a receipt was expected; the remaining {len(no_gr)-len(expected_missing_gr):,} are treated as legitimate no-GR flows.</p>
<h2>Most frequent activities</h2><table><thead><tr><th>Activity</th><th>Events</th></tr></thead><tbody>{activity_table}</tbody></table>
<h2>Experiment status</h2>
<div class="pending"><b>Three-arm accuracy and autonomy results are pending.</b><br>The value field is constant within cases, so arithmetic price variance is not used. Run the rebuilt leakage-safe experiment only after its Stage 1 feature calculation completes and reports a clean leakage check.</div>
<footer>Limitations: blocked status is conditioned on observed block removal; non-terminal cases have no historical resolution to predict; this page demonstrates system-event investigation and does not claim AP time savings or live SAP write-back.</footer>
</main></body></html>"""

    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(html_page)
    print(f"WROTE {OUT} ({os.path.getsize(OUT)/1024:.1f} KB)")
    print(f"events={len(events):,} cases={len(case_ids):,} blocked={len(blocked):,} expected_missing_gr={len(expected_missing_gr):,}")


if __name__ == "__main__":
    main()