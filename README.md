# Redesigning P2P Exception Management: Where Should AI Autonomy Stop?

Determining empirically, on 1.5M real SAP procurement events, which invoice
exceptions should be closed by deterministic rules, which need an AI agent to
investigate, and which must stay under human authority.

**Data:** BPI Challenge 2019 — van Dongen, B.F. (2019), 4TU.ResearchData,
DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1. A Dutch coatings and
paints multinational; each case is a purchase-order line item.

---

## Results

Generated page: `docs/index.html` — run `python run_sample.py`, or publish
it via Settings → Pages → `main` → `/docs`. Every figure on it is read from the
pipeline outputs; nothing is typed by hand, and the data-source stamp is printed
at the top.

## Quickstart

```bash
pip install -r requirements.txt
# put the BPI 2019 .xes file in data/  (see Data below)
python GO.py            # convert, reconnoitre, run, build the dashboard
python GO.py --live     # same, with the real Claude API agent
```

`GO.py` runs everything in order and stops at the first failed gate. The data
source is auto-detected from what is on disk — there is no flag to set. Every
output carries a stamp recording which mode ran, and the dashboard refuses to
build from fixture data unless you pass `--force`.

## Quickstart (individual steps)

```bash
pip install -r requirements.txt

# one-time: the dataset is not in this repo. Download BPI Challenge 2019 from
# 4TU.ResearchData, then convert it (streaming, low memory):
python xes_to_parquet.py data/BPI_Challenge_2019.xes

python run_all.py            # mock agent — free, proves the pipeline runs
python run_all.py --live     # real Claude API, responses cached to disk
python run_sample.py         # writes the illustrative owner work queue to docs/index.html
```

`src/config.py` is the only file you edit to point this at the real log. Set
`DATA_SOURCE = "real"`, set `PARQUET_PATH` to the converted file, and correct
any activity or column names that `phase0_recon.py` reports differently.

Every output carries a data-source stamp. Nothing produced with
`DATA_SOURCE = "synthetic"` may be reported — the fixture exists to test the
harness, not to generate findings.

After a validated run, build the self-contained results page:

```bash
python build_dashboard.py
```

This writes `docs/index.html`, which can be opened locally or published with
GitHub Pages from `main` and `/docs`. The page reads its figures from the CSVs
under `outputs/`; it does not contain hand-entered results. Do not publish the
page until the taxonomy and value-field diagnostics have been reviewed.

---

## Architecture

| Component | File | Role |
|---|---|---|
| Schema map | `src/config.py` | Single point of correction after reconnaissance |
| Data layer | `src/data.py` | Event log → one row per case, vectorised |
| Taxonomy & labels | `src/labels.py` | Exception classes; historically observed outcomes |
| Rules engine | `src/rules_engine.py` | **Arm A** — models the ERP's existing automation |
| Agent | `src/agent.py` | **Arm B** — Claude API tool calling, 6 tools |
| Policy engine | `src/policy_engine.py` | **Arm C** — decides authority, no LLM |
| Tools | `src/tools.py` | Evidence retrieval, evidence hierarchy enforced |
| Harness | `src/evaluate.py` | Three arms, precision by class, sensitivity, disagreements |

### Why rules run before the agent

Cost and control. Deterministic checks are free and reproducible, so anything a
rule can settle, a rule settles. It also means the agent's measured contribution
is *incremental over the baseline* rather than confounded with it. Running the
agent on everything would make it impossible to say what the AI was worth.

### Why the policy engine sits outside the model

The agent can be completely confident and completely correct and still not be
permitted to act. Permission is a function of exception class and transaction
value, set outside the model. Confidence is not authority.

I designed it using a release-strategy-like control pattern: value bands and
segregation of duties are a deterministic authority table configured outside
the transaction. This is an architectural correspondence, not a claim that
SAP documents define an agent-authority pattern.

### Evidence hierarchy

1. ERP transaction data (PO, goods receipt, invoice) — factual
2. Company policy (tolerances, approval limits) — decision authority
3. Internal history (vendor patterns) — supporting evidence only
4. External sources — **not implemented**; vendor IDs are anonymised, so an
   external lookup cannot be evaluated on real cases

Nothing sourced outside the ERP can clear a payment.

### The output loop

The pipeline has three output paths. A deterministic rule can produce an
`AUTO_RESOLVE` decision only where the policy engine permits it. That is the
single path that could eventually write back to SAP: release the payment block
using the case ID, authorising policy version, and audit record, analogous to
the API equivalent of an MRBR action. The implementation is a design target,
not a live SAP integration.

Agent investigation and human-approval decisions write no SAP transaction.
They produce a case packet for a work queue, including evidence, missing
information, recommendation, confidence, and the reason authority was not
granted. A pilot should begin in shadow mode, measure disagreements, and grant
autonomy per exception class only where observed precision supports it.

The dashboard is a view of the measured outputs, not a write-back channel.
It demonstrates system-event investigation; it does not measure AP time
reduction. Any value case must therefore be a scenario model with assumptions
labelled separately from measured log facts.

---

## Limitations, stated up front

1. **The target is historical behaviour, not verified correctness.** The log
   records that a clerk removed a payment block; it does not record whether they
   should have. `outputs/disagreement_sample.csv` sizes that gap by hand
   inspection. It does not eliminate it.
2. **`RESOLVED_WITHOUT_OBSERVED_PO_CORRECTION` records the absence of an
   amendment event.** It does not assign fault to the supplier.
3. **Vendor identifiers are anonymised.** External lookup is a capability
   demonstration only, never an evaluated result.
4. **The manual workflow between system events is modelled, not mined.** The log
   shows system-recorded events; the human investigation steps between them are
   inferred from standard AP practice and labelled as assumption. This is where
   the cycle-time savings estimate is least certain.
5. **The 95% precision threshold is a design choice, not an industry standard**
   — which is why `outputs/threshold_sensitivity.csv` reports the trade-off
   curve across 90/93/95/97 rather than a single point.
6. **Payment-block resolution as a bottleneck is a known finding** in published
   analyses of this log. The contribution here is the agent design and the
   autonomy boundary, not the bottleneck discovery.
7. **Single dataset, single industry, single country.** No claim of
   generalisability beyond direction.

---

## Guardrails enforced in code, not just documented

| # | Guardrail | Where |
|---|---|---|
| 3 | Expected-tools file frozen before the agent runs | `evaluate.freeze_expected_tools` never overwrites |
| 5 | "AI added value" attributed mechanically | `evaluate.final_classification` — both-succeeded goes to rules |
| 7 | No unopened benchmarks | value case refuses to compute while cost inputs are `None` |
| 10 | Tools that change no decision are cut | `evaluate.tool_metrics` reports never-called tools |
| 11 | "Historically observed outcome", never "ground truth" | `labels.py` naming throughout |
| 12 | Taxonomy derived from the data | `labels.audit_taxonomy` reports configured-but-absent activities |

## Scope

Process layer, not configuration layer. No SAP system was configured; no
tolerance key was set in SPRO. What this does is read a P2P process, find where
it breaks, and put a number on it.

## Interview spine

The single question is: **where should AI autonomy stop in P2P exception
management?** The data reconnaissance, taxonomy, rules baseline, agent arm,
policy engine, disagreement review, and dashboard all exist to answer that
question. They are not separate product features.

### Questions to prepare

**Q11 — Where does the output go?**

Only a policy-approved `AUTO_RESOLVE` path could write a payment-block release
back to SAP. Investigation and approval paths produce human work-queue packets
and write nothing autonomously.

**Q12 — Can I see it?**

Run `python build_dashboard.py` after a validated pipeline run and open
`docs/index.html`, or publish `/docs` with GitHub Pages. The page shows the
autonomy boundary, sensitivity curve, case buckets, precision, process facts,
exception mix, and limitations with the data-source stamp visible.
