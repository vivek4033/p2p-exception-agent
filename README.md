# P2P Exception Management: AI Recommendations Under Human Authority

Determining empirically, on 1.6M real SAP procurement events, which invoice
exceptions rules can identify, where an AI agent can support investigation,
and which decisions must stay under human authority.

**Data:** BPI Challenge 2019 — van Dongen, B.F. (2019), 4TU.ResearchData,
DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1. A Dutch coatings and
paints multinational; each case is a purchase-order line item.

---

## Results

The result is a human-authority workflow, not an autonomous payment release.
Policy v1.3 routes cases to human review or escalation. Its offline re-score
covered 181 cached live agent responses; categorical confidence has not been
evaluated live.

| Finding | Result | Scope |
|---|---:|---|
| Agent recommendation accuracy on exceptions | 19.6% | 46 exception cases, cached live responses |
| Agent exception-type accuracy | 84.5% | 181 cached live responses |
| Arm A rules coverage | 74.6% | Same 181 cases |
| Arm A accuracy on covered cases | 71.9% | Same 181 cases |
| Human review under policy v1.3 | 121 | Offline re-score |
| Escalation under policy v1.3 | 60 | Offline re-score |

The historical v1.2 evaluation also found 4 exception cases sent to automatic
resolution, with 0 correct; numeric confidence strictly between 0.8 and 0.9
was correct in 1 of 15 cases. See [the decision log](docs/decision_log.md) for
the version-by-version evidence and scope notes.

The historical live run used numeric confidence. Tag
[`live-results-numeric-confidence-2026-09-24`](https://github.com/vivek4033/p2p-exception-agent/tree/live-results-numeric-confidence-2026-09-24)
is the closest committed state; key verification matched 0 of the 181 cached
responses. Categorical confidence and policy v1.3 have not been evaluated live.

Build the main results page with `python build_dashboard.py`, or publish
`docs/index.html` via Settings → Pages → `main` → `/docs`. Figures come from
pipeline outputs and the page includes its data-source stamp.

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
python archive/legacy/run_sample.py  # writes an illustrative sample page, not the main results page
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
| Harness | `src/evaluate.py` | Three arms, recommendation accuracy, human routing, disagreements |

### Why rules run before the agent

Cost and control. Deterministic checks are free and reproducible, so anything a
rule can settle, a rule settles. It also means the agent's measured contribution
is *incremental over the baseline* rather than confounded with it. Running the
agent on everything would make it impossible to say what the AI was worth.

### Why the policy engine sits outside the model

The agent recommends an outcome and reports categorical confidence. The policy
engine receives that proposal, ERP-sourced exposure, and a deterministic
evidence grade. ERP exposure is authoritative; a differing model-reported value
is recorded as a contradiction. Confidence can lower a case to human review,
but cannot authorize action. Policy v1.3 authorizes no automatic resolution:
non-escalated cases require human disposition. The exhaustive test
`test_policy_v13_cannot_auto_resolve` checks that tested input combinations
return only `HUMAN_APPROVAL` or `ESCALATE`.

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

It demonstrates system-event investigation; it does not measure AP time
reduction. Any value case must therefore label its assumptions separately from
measured log facts.

---

## Limitations, stated up front

1. **The target is historical behaviour, not verified correctness.** The log
   records that a clerk removed a payment block; it does not record whether they
   should have. `outputs/disagreement_sample.csv` sizes that gap by hand
   inspection. It does not eliminate it.
2. **`RESOLVED_WITHOUT_OBSERVED_PO_CORRECTION` records the absence of an
   amendment event.** It does not assign fault to the supplier.
3. **Vendor identifiers are anonymised.** The recurring same-class supplier
   check is designed and unit-tested, but not live-evaluated; external lookup is
   not implemented.
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

The main results page is `docs/index.html`; archived demos and diagnostics are under `archive/legacy/`.
