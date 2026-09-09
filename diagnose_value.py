"""
diagnose_value.py — is the value field a document amount or a running total?

The taxonomy collapsed into NO_EXCEPTION, which is the fallback when price
variance cannot be computed. This establishes why, and whether an
activity-pattern taxonomy is the correct alternative.

    .\\venv\\Scripts\\python.exe -u diagnose_value.py
"""

import sys
sys.path.insert(0, "src")

import pandas as pd
import config as C

pd.set_option("display.width", 200)

full = pd.read_parquet(C.PARQUET_PATH)
print(f"events {len(full):,} | cases {full[C.CASE_COL].nunique():,}\n", flush=True)

print("=" * 72)
print("Q1 — NUMERIC COLUMNS AVAILABLE")
print("=" * 72)
for c in full.columns:
    if pd.api.types.is_numeric_dtype(full[c]):
        s = full[c].dropna()
        print(f"  {c}: n={len(s):,} min={s.min():,.2f} med={s.median():,.2f} "
              f"max={s.max():,.2f}")
print(f"\n  configured VALUE_COL = '{C.VALUE_COL}' "
      f"({'PRESENT' if C.VALUE_COL in full.columns else 'MISSING'})")

if C.VALUE_COL not in full.columns:
    print("\n  >>> The configured value column does not exist. Pick one above.")
    sys.exit(0)

print("\n" + "=" * 72)
print("Q2 — IS THE VALUE CUMULATIVE WITHIN A CASE?")
print("=" * 72)
d = full[[C.CASE_COL, C.ACT_COL, C.TS_COL, C.VALUE_COL]].sort_values(
    [C.CASE_COL, C.TS_COL])
sample_ids = d[C.CASE_COL].drop_duplicates().head(400)
sub = d[d[C.CASE_COL].isin(sample_ids)]
diffs = sub.groupby(C.CASE_COL)[C.VALUE_COL].diff().dropna()
print(f"  within-case step differences (n={len(diffs):,}):")
print(f"    non-negative : {100*(diffs >= 0).mean():.1f}%")
print(f"    exactly zero : {100*(diffs == 0).mean():.1f}%")
print("\n  >>> If non-negative is near 100%, the field is a RUNNING TOTAL and")
print("  >>> cannot be used as a PO-vs-invoice document comparison.")

print("\n  THREE EXAMPLE CASES, EVENT BY EVENT:")
for cid in sample_ids.head(3):
    print(f"\n  --- case {cid} ---")
    print(sub[sub[C.CASE_COL] == cid][[C.ACT_COL, C.VALUE_COL]].to_string(index=False))

print("\n" + "=" * 72)
print("Q3 — MEAN VALUE BY ACTIVITY (a document amount would not trend)")
print("=" * 72)
print(full.groupby(C.ACT_COL)[C.VALUE_COL].agg(["count", "mean", "median"])
      .sort_values("count", ascending=False).head(15).to_string())

print("\n" + "=" * 72)
print("Q4 — WOULD AN ACTIVITY-PATTERN TAXONOMY WORK INSTEAD?")
print("=" * 72)
e = full[[C.CASE_COL, C.ACT_COL]]
n = e[C.CASE_COL].nunique()


def pct(acts):
    if isinstance(acts, str):
        acts = [acts]
    k = e.loc[e[C.ACT_COL].isin(acts), C.CASE_COL].nunique()
    return k, 100 * k / n


for label, acts in [
    ("Change Price", C.A_CHANGE_PRICE),
    ("Change Quantity", C.A_CHANGE_QUANTITY),
    ("Remove Payment Block", C.A_REMOVE_BLOCK),
    ("Cancel Invoice Receipt", C.A_CANCEL_INVOICE),
    ("Record Goods Receipt", C.GR_ACTS),
    ("Record Invoice Receipt", C.A_INVOICE_RECEIPT),
    ("Clear Invoice", C.A_CLEAR_INVOICE),
]:
    k, p = pct(acts)
    print(f"  {label:26s} {k:>8,} cases ({p:5.2f}%)")

ir = e[e[C.ACT_COL] == C.A_INVOICE_RECEIPT].groupby(C.CASE_COL).size()
gr = e[e[C.ACT_COL].isin(C.GR_ACTS)].groupby(C.CASE_COL).size()
both = pd.concat([gr.rename("gr"), ir.rename("ir")], axis=1).fillna(0)
print(f"\n  GR count != IR count (quantity mismatch signal): "
      f"{int((both['gr'] != both['ir']).sum()):,} cases "
      f"({100*(both['gr'] != both['ir']).mean():.2f}% of cases with either)")
print(f"  multiple invoice receipts : {int((ir > 1).sum()):,} cases")
print(f"  multiple goods receipts   : {int((gr > 1).sum()):,} cases")

print("\n" + "=" * 72)
print("Paste this whole output back.")
print("=" * 72)
