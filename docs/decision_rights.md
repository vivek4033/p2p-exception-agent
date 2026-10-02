# Decision Rights Matrix - v1.3

| Exception class | Tier | Routed to | Justification |
|---|---|---|---|
| NO_EXCEPTION | HUMAN_APPROVAL | AP Team | No structural irregularity was identified; a human must record disposition. |
| PRIOR_PO_AMENDMENT | HUMAN_APPROVAL | Procurement | The purchase order was amended before invoicing. |
| GR_IR_COUNT_MISMATCH | HUMAN_APPROVAL | Warehouse / Goods Receiving | Goods receipt and invoice receipt counts disagree. |
| SEQUENCE_VIOLATION_INVOICE_BEFORE_GR | HUMAN_APPROVAL | AP Team Lead | Invoice arrived before any goods receipt. |
| DUPLICATE_INVOICE_RECEIPT_PATTERN | ESCALATE | AP Manager | A repeated invoice-receipt pattern needs AP review. |
| MISSING_GOODS_RECEIPT | ESCALATE | Procurement | A goods receipt was expected and none exists. |

**Value bands (policy, not findings):**
- Escalation cap: EUR 50,000

Model confidence is categorical: STRONG, INTERMEDIATE, or WEAK. It may only
lower a case to human review; it never grants authority. ERP exposure is the
policy value. A model-reported value mismatch is recorded as a contradiction.
No policy outcome authorizes automatic resolution.

**Ordered policy rules:**
- R1: insufficient evidence, unknown ERP value, or unresolved recommendation -> ESCALATE
- R2: ERP exposure above EUR 50,000 -> ESCALATE
- R3: purchase order changed after invoice receipt -> ESCALATE
- R4: unknown class or class designated for escalation -> ESCALATE
- R5: weak evidence or non-strong model confidence -> HUMAN_APPROVAL
- R6: recommendation conflicts with clean-case evidence -> HUMAN_APPROVAL
- R7: all remaining cases -> HUMAN_APPROVAL

_Data source: BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)_
