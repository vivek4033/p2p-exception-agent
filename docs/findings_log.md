# Findings Log

**Data source: BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)**

| Stage | Metric | Value |
|---|---|---|
| 0 | `events` | 1595923 |
| 0 | `cases` | 251734 |
| 0 | `distinct_activities` | 42 |
| 1 | `touchless_rate_pct` | 69.38 |
| 1 | `blocked_rate_pct` | 22.22 |
| 1 | `mean_cycle_days` | 71.52 |
| 1 | `median_cycle_days` | 64.04 |
| 1 | `mean_block_to_resolution_days` | -19.0 |
| 1 | `exception_classes` | 6 |
| 1 | `population_total_cases` | 251734 |
| 1 | `population_evaluable_cases` | 189462 |
| 1 | `population_excluded_non_terminal` | 62272 |
| 1 | `population_excluded_pct` | 24.74 |
| 1 | `cases_without_goods_receipt` | 17255 |
| 1 | `of_which_gr_was_expected` | 16211 |
| 1 | `gr_expectation_source` | case:Goods Receipt |
| 1 | `max_class_to_label_concentration` | 0.9576 |
| 1 | `label_derivable_on_blocked_pct` | 99.96 |
| 2 | `eval_set_size` | 200 |
| 2 | `expected_tools_frozen_for_cases` | 50 |
| 3 | `n_cases` | 200 |
| 3 | `arm_A_coverage` | 0.77 |
| 3 | `arm_A_accuracy_on_covered` | 0.7403 |
| 3 | `arm_A_accuracy_overall` | 0.57 |
| 3 | `arm_B_accuracy` | 0.69 |
| 3 | `arm_C_automation_rate` | 0.705 |
| 3 | `arm_C_precision_on_acted` | 0.7376 |
| 3 | `arm_C_false_automation_rate` | 0.2624 |
| 3 | `arm_C_escalation_rate` | 0.15 |
| 3 | `arm_C_approval_rate` | 0.145 |
| 3 | `tool_recall` | 0.0 |
| 3 | `tool_precision` | None |
| 4 | `demoted_class` | NO_EXCEPTION |
| 4 | `demoted_class_precision` | 0.7376 |
| 4 | `automated_resolutions_given_up` | 141 |
| 4 | `disagreements_sampled_for_hand_inspection` | 30 |
| 4 | `bucket_rules_sufficient_pct` | 57.0 |
| 4 | `bucket_human_necessary_pct` | 31.0 |
| 4 | `bucket_ai_added_value_pct` | 12.0 |

## Cycle-Time Reference Table

Generated from closed, non-evaluation cases on 2026-09-21 by
`scripts/build_cycle_time_reference.py`; values are committed in
`config/cycle_time_reference.csv` and were not typed by hand.

| Exception class | Median days | n |
|---|---:|---:|
| DUPLICATE_INVOICE_RECEIPT_PATTERN | 23.9 | 9,328 |
| GR_IR_COUNT_MISMATCH | 24.0 | 3,865 |
| MISSING_GOODS_RECEIPT | 11.9 | 192 |
| NO_EXCEPTION | 32.4 | 145,421 |
| PRIOR_PO_AMENDMENT | 31.0 | 14,541 |
| SEQUENCE_VIOLATION_INVOICE_BEFORE_GR | 2.4 | 15,010 |
| **__ALL__ fallback** | **28.5** | **188,357** |
