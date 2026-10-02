# Policy Decision Log

This log records why authority moved from class-based autonomy to human-only resolution. Outcomes below are historical-resolution labels, not verified ground truth.

## Evidence Summary

| Evidence | Result | Scope |
|---|---:|---|
| Agent recommendation accuracy on exceptions | 19.6% (9/46) | 181 cached live cases, offline rescored |
| Agent exception-type accuracy | 76.5% (153/200) | Historical v1.2 evaluation CSV |
| Agent exception-type accuracy | 84.5% (153/181) | Cached live subset joined to historical labels |
| Accuracy for `0.8 < numeric confidence < 0.9` | 6.7% (1/15) | Historical numeric-confidence evaluation; strict interval |
| Accuracy for `0.8 <= numeric confidence < 0.9` | 12.5% (2/16) | Same evaluation; includes the 0.8 boundary |
| v1.2 exception cases sent to autonomous resolution | 4; correct: 0 | Historical v1.2 policy output |

The different exception-type accuracies use different populations. The 200-case v1.2 report is the full evaluation; the 181-row cache is the live subset that can be re-scored today. No percentage here measures objective correctness: the event log records historical outcomes only.

## Version Decisions

| Version | Policy behavior | Evidence and rationale |
|---|---|---|
| v1.0 | Exception-class matrix allowed `NO_EXCEPTION` to resolve automatically; other classes were routed to approval or escalation. | Initial deterministic authority matrix. This granted automation based on class alone. |
| v1.1 | Demoted `NO_EXCEPTION` from the autonomous tier to human approval. | Measured precision was 74.2% on 93 acted cases, below the 95% pilot threshold. |
| v1.2 | Added evidence rules R1–R6, exposure bands, missing-source checks, and the prioritized queue. Numeric model confidence did not grant authority. | Evidence gates improved auditability, but the historical output still contains four exception cases auto-resolved; all four were incorrect. Exception recommendation accuracy was 19.6%, and high numeric confidence was poorly calibrated. |
| v1.3 | Removed the automatic outcome entirely. Every case becomes `HUMAN_APPROVAL` or `ESCALATE`; ERP exposure is authoritative; model/ERP value mismatches are contradictions; PO changes after invoice receipt escalate under R3. | The four false v1.2 autonomous exception outcomes, weak exception recommendation accuracy, and the 6.7% accuracy in the strict 0.8–0.9 confidence band do not justify payment authority. Confidence can downgrade a case but cannot authorize action. |

## Scope and Reproducibility

The historical live responses used numeric confidence. The tag `live-results-numeric-confidence-2026-09-24` points to the closest committed code state, not an exact cache-key match: verification matched 0 of 181 cache filenames. Policy v1.3 and categorical confidence have not been evaluated live; the current v1.3 decisions are an offline re-score of the old cache.

The recurring same-class supplier check is designed and unit-tested using only cases closed before the decision timestamp. The old live cache predates those fields, so this check has not been evaluated live.
