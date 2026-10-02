# Findings Log

**Data source: BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)**

The 181 live agent responses were generated with numeric confidence. Tag
`live-results-numeric-confidence-2026-09-24` is the closest committed state;
cache-key verification matched 0 of 181 filenames. Policy v1.3 outcomes below
are an offline re-score of those cached responses. Categorical confidence has
not been evaluated live; do not present the v1.3 routing counts as a live
categorical-confidence result. See [the decision log](decision_log.md).

| Stage | Metric | Value |
|---|---|---|
| 0 | `events` | 1595923 |
| 0 | `cases` | 251734 |
| 0 | `distinct_activities` | 42 |
| 1 | `touchless_rate_pct` | 69.38 |
| 1 | `blocked_rate_pct` | 22.22 |
| 1 | `mean_cycle_days` | 71.52 |
| 1 | `median_cycle_days` | 64.04 |
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
| 3 | `cached_live_responses` | 181 |
| 3 | `agent_recommendation_accuracy` | 0.586 |
| 3 | `arm_A_coverage` | 0.746 |
| 3 | `arm_A_accuracy_on_covered` | 0.719 |
| 3 | `arm_A_accuracy_overall` | 0.536 |
| 3 | `arm_C_human_review_count` | 121 |
| 3 | `arm_C_human_review_rate` | 0.669 |
| 3 | `arm_C_escalation_count` | 60 |
| 3 | `arm_C_escalation_rate` | 0.331 |
| 3 | `agent_disagreements_with_historical_outcome` | 75 |
| 3 | `agent_disagreement_rate` | 0.414 |
| 3 | `policy_version` | v1.3 (offline rescore) |
| 3 | `categorical_confidence_live_evaluated` | false |
