# Redesigning P2P Exception Management: Where Should AI Autonomy Stop?

Determining empirically, on 1.6M real SAP procurement events, which invoice
exceptions rules can identify, where an AI agent can support investigation,
and which decisions must stay under human authority.

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

tested only; it is not authority. Authority comes from a deterministic ERP
evidence checklist: STRONG, WEAK, or INSUFFICIENT. No numeric score or weight
The agent recommends an outcome and reports categorical confidence. The policy
engine receives that proposal, the ERP-sourced exposure, and a deterministic
evidence grade. ERP exposure is authoritative; a differing model-reported value
is recorded as a contradiction. Confidence can lower a case to human review,
but cannot authorize action. Policy v1.3 authorizes no automatic resolution:
non-escalated cases require human disposition.

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

The pipeline produces human-review or escalation decisions. Neither the agent
nor the policy engine writes a SAP transaction. Each case packet includes the
evidence, missing information, agent recommendation, confidence, ERP exposure,
and policy reason. The dashboard is a view of measured outputs, not a write-back
channel.

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
5. **Time savings are not present in the event log.** `MINUTES_SAVED_PER_CASE`
   is unset until measured in a shadow pilot; no time-savings figure is claimed.
6. **Early-payment discount capture is not measured.** The discount field is
   retained as an explicit assumption and is excluded from the current value model.
7. **Payment-block resolution as a bottleneck is a known finding** in published
   analyses of this log. The contribution here is agent-supported human
   investigation and evidence-based routing, not the bottleneck discovery.
8. **Single dataset, single industry, single country.** No claim of
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

No path writes a payment-block release back to SAP. Arm C assigns human review
or escalation; the assigned owner records the disposition.

**Q12 — Can I see it?**

Run `python build_dashboard.py` after a validated pipeline run and open
`docs/index.html`, or publish `/docs` with GitHub Pages. The page shows the
human-review and escalation mix, recommendation quality, case buckets, process
facts, exception mix, and limitations with the data-source stamp visible.

### Live-results provenance

The historical live run used numeric model confidence. Its code state is tagged
[`live-results-numeric-confidence-2026-09-24`](https://github.com/vivek4033/p2p-exception-agent/tree/live-results-numeric-confidence-2026-09-24).
The September 24 cache contains 181 live responses. Categorical confidence and
policy v1.3 are later design changes and have **not been evaluated live**. Cache
keys include the system prompt, so a live run with the newer prompt will not
reuse those responses; `scripts/rescore_v12.py` rescales cached data offline and
does not call the API.
