# Decision-Rights Matrix — v1.1

| Exception class | Tier | Routed to | Justification |
|---|---|---|---|
| NO_EXCEPTION | HUMAN_APPROVAL | — | Three-way match passes. No exception to adjudicate. DEMOTED v1.1: precision 0.855 on n=131 below the 0.95 pilot threshold |
| PRICE_VARIANCE_WITHIN_TOLERANCE | AUTO_RESOLVE | — | Deterministic arithmetic against a configured tolerance key. Near-zero error cost; an ERP already clears these. |
| PRICE_VARIANCE_OVER_TOLERANCE | HUMAN_APPROVAL | Procurement | Variance beyond tolerance may reflect a contractual price change. Clearing it without sign-off accepts a commercial commitment the system cannot verify. |
| QUANTITY_VARIANCE | HUMAN_APPROVAL | Warehouse / Goods Receiving | Quantity variance implies a physical goods discrepancy. Resolution requires warehouse confirmation outside the log. |
| SEQUENCE_VIOLATION_INVOICE_BEFORE_GR | HUMAN_APPROVAL | AP Team Lead | Invoice received before goods receipt breaks GR/IR sequencing. A control breach, not an arithmetic error. |
| DUPLICATE_INVOICE_PATTERN | ESCALATE | AP Manager | A false positive leaves a supplier unpaid and a false negative pays twice. Both failure modes are expensive and asymmetric; AP manager owns the call. |
| MISSING_GOODS_RECEIPT | ESCALATE | Procurement | Absence of a goods receipt is a policy violation, not a data problem. Owned by procurement, not AP. |

**Value bands (policy, not findings):**
- Autonomous action cap: EUR 5,000
- Escalation cap: EUR 50,000
- Price tolerance: 2.0%
- Quantity tolerance: 5.0%
- Near-miss band: ±0.5pp of a threshold

_Data source: BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)_
