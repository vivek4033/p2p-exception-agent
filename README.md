# Redesigning P2P Exception Management: Where Should AI Autonomy Stop?

Determining empirically, on 1.5M real SAP procurement events, which invoice
exceptions should be closed by deterministic rules, which need an AI agent to
investigate, and which must stay under human authority.

**Data:** BPI Challenge 2019 — van Dongen, B.F. (2019), 4TU.ResearchData,
DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1. A Dutch coatings and
paints multinational; each case is a purchase-order line item.

---

## Quickstart

```bash
pip install pandas numpy pyarrow anthropic pm4py
python run_all.py            # mock agent — free, proves the pipeline runs
python run_all.py --live     # real Claude API, responses cached to disk
```

Download the BPI Challenge 2019 XES log from [4TU.ResearchData](https://data.4tu.nl/)
and place it at `data/BPI_Challenge_2019.xes`. Convert it before running the
real-data pipeline:

```bash
python xes_to_parquet.py data/BPI_Challenge_2019.xes
```

This creates `data/bpi2019.parquet`, which is intentionally ignored by Git.

`src/config.py` is the only file you edit to point this at the real log. Set
`DATA_SOURCE = "real"`, put the CSV at `data/BPI_Challenge_2019.csv`, and correct
any activity or column names that `phase0_recon.py` reports differently.

Every output carries a data-source stamp. Nothing produced with
`DATA_SOURCE = "synthetic"` may be reported — the fixture exists to test the
harness, not to generate findings.

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

This is functionally an SAP release strategy applied to a non-human actor —
value-band approvals and segregation of duties are a deterministic table of
thresholds configured outside the transaction. The same control pattern, applied
to an agent.

### Evidence hierarchy

1. ERP transaction data (PO, goods receipt, invoice) — factual
2. Company policy (tolerances, approval limits) — decision authority
3. Internal history (vendor patterns) — supporting evidence only
4. External sources — **not implemented**; vendor IDs are anonymised, so an
   external lookup cannot be evaluated on real cases

Nothing sourced outside the ERP can clear a payment.

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
