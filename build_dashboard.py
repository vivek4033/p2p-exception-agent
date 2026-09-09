"""
build_dashboard.py — turns the pipeline's CSVs into a viewable results page.

    python build_dashboard.py

Reads outputs/*.csv, writes docs/index.html — a single self-contained file, no
server, no dependencies. Open it locally, or publish it with GitHub Pages
(Settings -> Pages -> Deploy from branch -> main -> /docs) and it becomes:

    https://<user>.github.io/p2p-exception-agent/

Design intent: this is an audit exhibit, not a product dashboard. It reads
top-down like a finding memo — the autonomy boundary first, the trade-off that
produced it second, the evidence beneath, and the limitations last rather than
hidden. Tier colours are semantic (they encode authority level), not decoration.

If the run was on synthetic data, the page says so in a way that cannot be
cropped out of a screenshot.
"""

import os
from datetime import date

import pandas as pd

OUT = "docs/index.html"


def read(name):
    p = os.path.join("outputs", name)
    return pd.read_csv(p) if os.path.exists(p) else None


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# --------------------------------------------------------------------- charts
def sensitivity_svg(sens):
    """Automation rate against required precision. The project's key exhibit."""
    if sens is None or sens.empty:
        return "<p class='pending'>Not yet computed. Run the three arms first.</p>"

    d = sens.dropna(subset=["automation_rate"]).sort_values("precision_threshold")
    if d.empty:
        return "<p class='pending'>No permitted classes at any threshold tested.</p>"

    W, H = 640, 300
    PL, PR, PT, PB = 64, 24, 24, 52
    xs = d["precision_threshold"].tolist()
    ys = (d["automation_rate"] * 100).tolist()
    x0, x1 = min(xs), max(xs)
    y1 = max(max(ys), 1) * 1.15

    def px(v):
        return PL + (v - x0) / (x1 - x0 or 1) * (W - PL - PR)

    def py(v):
        return H - PB - v / y1 * (H - PT - PB)

    pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(xs, ys))
    dots = "".join(
        f'<circle cx="{px(a):.1f}" cy="{py(b):.1f}" r="4.5" class="dot"/>'
        f'<text x="{px(a):.1f}" y="{py(b)-14:.1f}" class="dotlab">{b:.0f}%</text>'
        for a, b in zip(xs, ys))
    xlab = "".join(
        f'<text x="{px(a):.1f}" y="{H-PB+22}" class="axlab">{a:.0%}</text>'
        for a in xs)

    grid = ""
    for frac in (0, .25, .5, .75, 1):
        v = y1 * frac
        grid += (f'<line x1="{PL}" y1="{py(v):.1f}" x2="{W-PR}" y2="{py(v):.1f}" '
                 f'class="grid"/>'
                 f'<text x="{PL-10}" y="{py(v)+4:.1f}" class="axlab end">{v:.0f}%</text>')

    return f"""<svg viewBox="0 0 {W} {H}" class="chart" role="img"
      aria-label="Automation rate falls as required precision rises">
      {grid}
      <polyline points="{pts}" class="line"/>
      {dots}{xlab}
      <text x="{PL}" y="{H-8}" class="axtitle">Required precision</text>
      <text x="{PL-46}" y="{PT+2}" class="axtitle">Automated</text>
    </svg>"""


def bar_table(df, label_col, value_col, fmt="{:.0f}"):
    if df is None or df.empty:
        return "<p class='pending'>Not yet computed.</p>"
    m = df[value_col].max() or 1
    rows = ""
    for _, r in df.iterrows():
        w = 100 * r[value_col] / m
        rows += (f"<tr><th scope='row'>{esc(r[label_col])}</th>"
                 f"<td class='barcell'><span class='bar' style='width:{w:.1f}%'></span></td>"
                 f"<td class='num'>{fmt.format(r[value_col])}</td></tr>")
    return f"<table class='bars'>{rows}</table>"


# ----------------------------------------------------------------------- page
def build():
    os.makedirs("docs", exist_ok=True)

    findings = read("findings_log.csv")
    exc = read("exception_summary.csv")
    sens = read("threshold_sensitivity.csv")
    prec = read("precision_by_class.csv")
    cases = read("case_results.csv")
    vend = read("vendor_concentration.csv")

    stamp = "unknown"
    if findings is not None and "data_source" in findings.columns and len(findings):
        stamp = str(findings["data_source"].iloc[0])
    synthetic = "SYNTHETIC" in stamp.upper()

    def finding(metric, default="—"):
        if findings is None:
            return default
        m = findings[findings["metric"] == metric]
        return str(m["value"].iloc[0]) if len(m) else default

    # headline: the autonomy boundary
    boundary = None
    if sens is not None and not sens.empty:
        row = sens[sens["precision_threshold"] == 0.95]
        if len(row) and pd.notna(row["automation_rate"].iloc[0]):
            boundary = row.iloc[0]

    if boundary is not None:
        hero_num = f"{boundary['automation_rate']*100:.0f}%"
        hero_sub = ("of the evaluated population can be closed without a human "
                    "while holding 95% precision")
        binding = boundary.get("binding_constraint")
        hero_note = (f"The binding constraint is {esc(binding)}."
                     if isinstance(binding, str) and binding else "")
    else:
        hero_num = "not yet"
        hero_sub = ("The three-arm experiment has not been run on the rebuilt "
                    "taxonomy. No autonomy boundary is claimed.")
        hero_note = ""

    banner = ("<div class='banner'>Synthetic test fixture — these figures test "
              "the harness and are not findings.</div>" if synthetic else "")

    buckets = ""
    if cases is not None and "final_bucket" in cases.columns:
        vc = cases["final_bucket"].value_counts(normalize=True)
        names = {"rules_sufficient": "Rules sufficient",
                 "ai_added_value": "Agent added value",
                 "human_necessary": "Human necessary"}
        seg = "".join(
            f"<span class='seg {k}' style='width:{v*100:.2f}%' "
            f"title='{names.get(k,k)} {v*100:.1f}%'></span>"
            for k, v in vc.items())
        key = "".join(f"<li><i class='sw {k}'></i>{names.get(k,k)} "
                      f"<b>{v*100:.1f}%</b></li>" for k, v in vc.items())
        buckets = f"<div class='stack'>{seg}</div><ul class='key'>{key}</ul>"
    else:
        buckets = "<p class='pending'>Not yet computed.</p>"

    exc_block = "<p class='pending'>Not yet computed.</p>"
    if exc is not None and not exc.empty:
        e = exc.sort_values("n_cases", ascending=False)
        exc_block = bar_table(e, "exception_class", "n_cases", "{:,.0f}")

    prec_block = "<p class='pending'>Not yet computed.</p>"
    if prec is not None and not prec.empty:
        rows = "".join(
            f"<tr><th scope='row'>{esc(r['exception_class'])}</th>"
            f"<td class='num'>{int(r['n_acted']):,}</td>"
            f"<td class='num {'below' if r['precision'] < .95 else ''}'>"
            f"{r['precision']*100:.1f}%</td></tr>"
            for _, r in prec.iterrows())
        prec_block = (f"<table class='data'><thead><tr><th>Exception class</th>"
                      f"<th>Acted on</th><th>Precision</th></tr></thead>"
                      f"<tbody>{rows}</tbody></table>")

    vend_block = ""
    if vend is not None and not vend.empty and "cum_share_of_blocked_exposure" in vend:
        top = vend.head(5)["cum_share_of_blocked_exposure"].iloc[-1]
        vend_block = (f"<p>The five suppliers with the largest blocked exposure "
                      f"account for <b>{top*100:.1f}%</b> of all blocked value. "
                      f"Exception concentration is a supplier-management finding, "
                      f"not a technical one.</p>")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P2P Exception Autonomy — Results</title>
<style>
:root {{
  --paper:#FBFBF9; --ink:#191C1F; --muted:#5C6670; --rule:#D8D6CF;
  --steel:#3E5566; --auto:#4F7A5C; --approve:#B0803A; --escalate:#9C4A38;
}}
* {{ box-sizing:border-box }}
body {{
  margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
}}
main {{ max-width:760px; margin:0 auto; padding:48px 24px 96px }}
h1 {{ font-size:26px; line-height:1.25; margin:0 0 6px; font-weight:600;
      letter-spacing:-.01em }}
h2 {{ font-size:15px; font-weight:600; margin:52px 0 12px;
      padding-bottom:7px; border-bottom:1px solid var(--rule) }}
p {{ max-width:68ch }}
.sub {{ color:var(--muted); margin:0 0 4px }}
.stampline {{ color:var(--muted); font-size:13px; margin:0 }}
.banner {{ background:var(--escalate); color:#fff; padding:11px 16px;
           border-radius:2px; margin:20px 0; font-weight:600; font-size:14px }}
.hero {{ margin:34px 0 8px; padding:26px 28px; background:#fff;
         border:1px solid var(--rule); border-left:4px solid var(--steel) }}
.heronum {{ font-size:56px; line-height:1; font-weight:600;
            letter-spacing:-.03em; font-variant-numeric:tabular-nums }}
.herosub {{ margin:10px 0 0; max-width:52ch }}
.heronote {{ margin:12px 0 0; color:var(--muted); font-size:14px }}
.chart {{ width:100%; height:auto; margin:14px 0 4px }}
.line {{ fill:none; stroke:var(--steel); stroke-width:2.5 }}
.dot {{ fill:var(--steel) }}
.dotlab {{ fill:var(--ink); font-size:12px; text-anchor:middle;
           font-variant-numeric:tabular-nums }}
.axlab {{ fill:var(--muted); font-size:11px; text-anchor:middle }}
.axlab.end {{ text-anchor:end }}
.axtitle {{ fill:var(--muted); font-size:11px }}
.grid {{ stroke:var(--rule); stroke-width:1 }}
table {{ border-collapse:collapse; width:100%; margin:8px 0 }}
.data th, .data td {{ text-align:left; padding:8px 10px;
                      border-bottom:1px solid var(--rule); font-size:14px }}
.data thead th {{ color:var(--muted); font-weight:500 }}
.num {{ text-align:right; font-variant-numeric:tabular-nums }}
.below {{ color:var(--escalate); font-weight:600 }}
.bars th {{ text-align:left; font-weight:400; font-size:14px; padding:5px 10px 5px 0;
            white-space:nowrap }}
.barcell {{ width:55% }}
.bar {{ display:block; height:11px; background:var(--steel); opacity:.72 }}
.bars .num {{ padding-left:12px; font-size:14px; width:1%; white-space:nowrap }}
.stack {{ display:flex; height:26px; margin:14px 0 12px; overflow:hidden }}
.seg.rules_sufficient {{ background:var(--auto) }}
.seg.ai_added_value {{ background:var(--steel) }}
.seg.human_necessary {{ background:var(--approve) }}
.key {{ list-style:none; padding:0; margin:0; display:flex; gap:22px;
        flex-wrap:wrap; font-size:14px }}
.sw {{ display:inline-block; width:11px; height:11px; margin-right:7px }}
.sw.rules_sufficient {{ background:var(--auto) }}
.sw.ai_added_value {{ background:var(--steel) }}
.sw.human_necessary {{ background:var(--approve) }}
.pending {{ color:var(--muted); font-style:italic }}
.facts {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
          gap:1px; background:var(--rule); border:1px solid var(--rule);
          margin:8px 0 }}
.fact {{ background:#fff; padding:14px 16px }}
.fact b {{ display:block; font-size:23px; font-weight:600;
           font-variant-numeric:tabular-nums; letter-spacing:-.02em }}
.fact span {{ color:var(--muted); font-size:13px }}
ol.lim {{ max-width:68ch; padding-left:20px }}
ol.lim li {{ margin-bottom:9px }}
footer {{ margin-top:56px; padding-top:16px; border-top:1px solid var(--rule);
          color:var(--muted); font-size:13px }}
a {{ color:var(--steel) }}
@media (max-width:520px) {{ .heronum {{ font-size:42px }} main {{ padding:32px 18px 64px }} }}
</style></head><body><main>

<h1>Where should AI autonomy stop in procure-to-pay exception handling?</h1>
<p class="sub">Measured on the BPI Challenge 2019 SAP procurement log</p>
<p class="stampline">Data source: {esc(stamp)} &middot; Generated {date.today().isoformat()}</p>
{banner}

<div class="hero">
  <div class="heronum">{hero_num}</div>
  <p class="herosub">{hero_sub}</p>
  <p class="heronote">{hero_note}</p>
</div>

<h2>The trade-off behind that number</h2>
<p>Every point of precision demanded costs automation. This curve prices that
exchange, so the threshold becomes a decision a finance owner makes rather than
one an engineer assumes.</p>
{sensitivity_svg(sens)}

<h2>Where each case ends up</h2>
<p>Assigned mechanically. A case counts as agent value only where the rules
could not resolve it <em>and</em> the agent did — cases both handled go to
rules, which is deliberately conservative toward the AI.</p>
{buckets}

<h2>Precision by exception class</h2>
<p>Any class below the 95% pilot threshold is demoted from autonomous action to
human approval. That threshold is a design choice, not an industry standard.</p>
{prec_block}

<h2>What the process looks like</h2>
<div class="facts">
  <div class="fact"><b>{finding('events')}</b><span>Events</span></div>
  <div class="fact"><b>{finding('cases')}</b><span>PO line items</span></div>
  <div class="fact"><b>{finding('blocked_rate_pct')}%</b><span>Payment blocked</span></div>
  <div class="fact"><b>{finding('population_evaluable_cases')}</b><span>Evaluable</span></div>
  <div class="fact"><b>{finding('population_excluded_pct')}%</b><span>Excluded, non-terminal</span></div>
  <div class="fact"><b>{finding('exception_classes')}</b><span>Exception classes</span></div>
</div>

<h2>Exception mix</h2>
{exc_block}
{vend_block}

<h2>What this does not show</h2>
<ol class="lim">
<li>The target is what the organisation historically did, not what was
objectively correct. The log records that a clerk released a payment block; it
does not record whether they should have.</li>
<li>Blocked status is inferred from block removal — SAP writes the removal
55,839 times and the block-set event only 122. So this is conditioned on blocks
that were eventually cleared, and resolution times are survivor-biased.</li>
<li>Cases with no terminal outcome are excluded, not relabelled.</li>
<li>The log carries no per-document amounts, so exceptions are structural
rather than variance-based.</li>
<li>Human investigation steps between system events are not recorded. They are
modelled from standard AP practice and treated as assumption.</li>
</ol>

<footer>
BPI Challenge 2019 — van Dongen, B.F. (2019), 4TU.ResearchData,
DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1.
Generated by <code>build_dashboard.py</code> from the pipeline outputs; no
figure on this page is typed by hand.
</footer>
</main></body></html>"""

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"WROTE {OUT}  ({os.path.getsize(OUT)/1024:.1f} KB)")
    print(f"  data source: {stamp}")
    print("  open it locally, or publish via Settings -> Pages -> main /docs")


if __name__ == "__main__":
    build()
