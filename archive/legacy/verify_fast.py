"""
verify_fast.py — answers every open question without building case features.

Reads three columns and does set arithmetic. Finishes in seconds on the full
1.6M-event log, so it cannot be cut off by a terminal timeout.

    .\\venv\\Scripts\\python.exe verify_fast.py
"""

import sys
sys.path.insert(0, "src")

import pandas as pd
import config as C

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 60)

print(f"SOURCE : {C.stamp()}")
print(f"PARQUET: {C.PARQUET_PATH}", flush=True)

full = pd.read_parquet(C.PARQUET_PATH)
print(f"events {len(full):,} | cases {full[C.CASE_COL].nunique():,} "
      f"| activities {full[C.ACT_COL].nunique()}\n", flush=True)

print("=" * 72)
print("ALL ACTIVITIES  (the taxonomy must be derived from this list)")
print("=" * 72)
print(full[C.ACT_COL].value_counts().to_string(), flush=True)

d = full[[C.CASE_COL, C.ACT_COL]]
all_cases = set(d[C.CASE_COL].unique())


def cases_with(acts):
    if isinstance(acts, str):
        acts = [acts]
    return set(d.loc[d[C.ACT_COL].isin(acts), C.CASE_COL])


setblk = cases_with(C.A_SET_BLOCK)
remblk = cases_with(C.A_REMOVE_BLOCK)
gr = cases_with(C.GR_ACTS)
inv = cases_with(C.A_INVOICE_RECEIPT)
clr = cases_with(C.A_CLEAR_INVOICE)
canc = cases_with(C.A_CANCEL_INVOICE)
chp = cases_with(C.A_CHANGE_PRICE)
chq = cases_with(C.A_CHANGE_QUANTITY)

blocked = setblk | remblk          # inferred: a removal implies a block existed
corrected = chp | chq

print("\n" + "=" * 72)
print("BLOCK DEFINITION")
print("=" * 72)
n = len(all_cases)
for label, s in [("Set Payment Block", setblk), ("Remove Payment Block", remblk),
                 ("either (inferred blocked)", blocked),
                 ("set but never removed", setblk - remblk)]:
    print(f"  {label:32s} {len(s):>8,}  ({100*len(s)/n:5.2f}% of cases)")

print("\n" + "=" * 72)
print("LABEL GATE — real numbers")
print("=" * 72)
derivable = blocked & (remblk | canc)
print(f"  blocked cases            : {len(blocked):,} ({100*len(blocked)/n:.2f}%)")
print(f"  of those, derivable      : {len(derivable):,} "
      f"({100*len(derivable)/max(len(blocked),1):.2f}%)")
print(f"  GATE (>=60%)             : "
      f"{'PASSED' if len(blocked) and len(derivable)/len(blocked) >= .6 else 'FAILED'}")

print("\n  OUTCOME LABEL DISTRIBUTION")
lab = {
    "CLEARED_WITHOUT_BLOCK": len((all_cases - blocked) & clr),
    "RESOLVED_WITH_OBSERVED_PO_CORRECTION": len(blocked & remblk & corrected - canc),
    "RESOLVED_WITHOUT_OBSERVED_PO_CORRECTION": len(blocked & remblk - corrected - canc),
    "INVOICE_CANCELLED": len(canc),
    "UNRESOLVED_IN_LOG": len(all_cases - clr - blocked),
}
for k, v in lab.items():
    print(f"    {k:42s} {v:>8,}  ({100*v/n:5.2f}%)")

print("\n" + "=" * 72)
print("FLOW-TYPE CONTAMINATION  (no-GR cases wrongly read as exceptions)")
print("=" * 72)
no_gr = all_cases - gr
print(f"  cases with NO goods receipt: {len(no_gr):,} ({100*len(no_gr)/n:.2f}%)")
print("  -> currently ALL of these are classified MISSING_GOODS_RECEIPT\n")

case_attrs = [c for c in full.columns if c.startswith("case:")
              or any(k in c.lower() for k in ("item", "categ", "gr-based",
                                              "goods receipt", "doc", "spend"))]
print(f"  candidate flow-type columns: {case_attrs}\n")

first = full.drop_duplicates(subset=[C.CASE_COL]).set_index(C.CASE_COL)
first["_has_gr"] = first.index.isin(gr)

for col in case_attrs:
    if col in (C.CASE_COL,):
        continue
    nun = first[col].nunique(dropna=True)
    if nun == 0 or nun > 12:
        continue
    t = first.groupby(col).agg(n_cases=("_has_gr", "size"),
                               has_gr_pct=("_has_gr", lambda s: round(100 * s.mean(), 1)))
    t = t.sort_values("n_cases", ascending=False)
    if (t["has_gr_pct"] < 50).any():
        print(f"  *** {col} — values below 50% has_gr are legitimate no-GR flows:")
    else:
        print(f"  {col}:")
    print(t.to_string() + "\n")

print("=" * 72)
print("Paste this whole output back.")
print("=" * 72)
