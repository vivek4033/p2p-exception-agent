# Metric Definitions

## Decision Time

Decision time is the first `Set Payment Block` event for a case. If no payment
block exists, it is the first `Record Invoice Receipt` event. A case with
neither event cannot be evaluated. Tools may inspect only events at or before
this timestamp.

## Evidence Levels

- **STRONG**: required evidence is present, no contradictions, and no near-miss.
- **WEAK**: evidence is present with one contradiction or a near-miss.
- **INSUFFICIENT**: a required source is missing or at least two contradictions
  exist.

## Queue Priority

Queue priority is EUR-days: `exposure_eur * max(class median days, days waited)`.
It is a prioritisation proxy, not a measured financial loss.