# Decision-Rights Matrix � v1.0

| Exception class | Tier | Routed to | Justification |
|---|---|---|---|
| NO_EXCEPTION | AUTO_RESOLVE | � | No structural irregularity in the evidence available when the invoice arrived. An ERP already clears these. |
| PRIOR_PO_AMENDMENT | HUMAN_APPROVAL | Procurement | The purchase order was amended before invoicing. That may reflect a contractual change the system cannot verify; clearing it accepts a commercial commitment. |
| GR_IR_COUNT_MISMATCH | HUMAN_APPROVAL | Warehouse / Goods Receiving | Goods receipt and invoice receipt counts disagree, implying a physical discrepancy. Resolution needs warehouse confirmation outside the log. |
| SEQUENCE_VIOLATION_INVOICE_BEFORE_GR | HUMAN_APPROVAL | AP Team Lead | Invoice received before any goods receipt breaks GR/IR sequencing. A control breach, not an arithmetic error. |
| DUPLICATE_INVOICE_RECEIPT_PATTERN | ESCALATE | AP Manager | A false positive leaves a supplier unpaid; a false negative pays twice. Both failure modes are expensive and asymmetric. AP manager owns the call. |
| MISSING_GOODS_RECEIPT | ESCALATE | Procurement | A goods receipt was expected and none exists. A policy violation owned by procurement, not a data problem. |

**Value bands (policy, not findings):**
- Autonomous action cap: EUR 5,000
- Escalation cap: EUR 50,000
- No arithmetic tolerance: this log carries no per-document amounts, so classes are structural, not variance-based.

_Data source: BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)_

## Evidence levels (policy v1.2)

- **STRONG**: PO, GR, invoice, and policy evidence are present; there are no
	contradictions and the case is not a near-miss.
- **WEAK**: all required evidence is present, but there is one contradiction or
	a near-miss. Human approval is required.
- **INSUFFICIENT**: any required source is missing, or there are two or more
	contradictions. Escalation is required.

Model confidence is retained for calibration testing only. The audit record
also stores `evidence_level`, `rule_fired`, `missing_sources`, and
`contradictions`.

## Ordered rules

| Rule | Condition | Outcome |
|---|---|---|
| R1 | Evidence is INSUFFICIENT or value is unknown | ESCALATE |
| R2 | Value is above EUR 50,000 | ESCALATE |
| R3 | Class is not auto-permitted | Matrix outcome |
| R4 | Value is above EUR 5,000 | HUMAN_APPROVAL |
| R5 | Evidence is WEAK | HUMAN_APPROVAL |
| R6 | All checks pass | AUTO_RESOLVE |
