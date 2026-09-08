"""verify.py — independent check of the real-data run.

Does not trust the pipeline's own audit. Reads the log directly and answers
four questions:

  1. Which of the configured activity names actually exist?
  2. What is the real blocked rate, and is it plausible?
  3. Does the label gate pass, with real numbers?
  4. Are non-three-way-match flows contaminating the exception taxonomy?

    python verify.py
"""

import sys
sys.path.insert(0, "src")

import pandas as pd
import config as C
import data
import labels as L

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 100)

print(f"DATA SOURCE : {C.stamp()}")
print(f"PARQUET     : {C.PARQUET_PATH}")

df = data.load_log()
print(f"\nevents {len(df):,} | cases {df[C.CASE_COL].nunique():,} "
      f"| activities {df[C.ACT_COL].nunique()}")

# ------------------------------------------------------------------ Q1
print("\n" + "=" * 72)
print("Q1 — CONFIGURED ACTIVITY NAMES vs THE LOG")
print("=" * 72)
present = set(df[C.ACT_COL].unique())
configured = {
    "A_CREATE_PO": C.A_CREATE_PO, "A_GOODS_RECEIPT": C.A_GOODS_RECEIPT,
    "A_VENDOR_INVOICE": C.A_VENDOR_INVOICE, "A_INVOICE_RECEIPT": C.A_INVOICE_RECEIPT,
    "A_CLEAR_INVOICE": C.A_CLEAR_INVOICE, "A_REMOVE_BLOCK": C.A_REMOVE_BLOCK,
    "A_SET_BLOCK": C.A_SET_BLOCK, "A_CHANGE_PRICE": C.A_CHANGE_PRICE,
    "A_CHANGE_QUANTITY": C.A_CHANGE_QUANTITY, "A_CANCEL_INVOICE": C.A_CANCEL_INVOICE,
}
counts = df[C.ACT_COL].value_counts()
for k, v in configured.items():
    ok = v in present
    n = int(counts.get(v, 0))
    print(f"  {'OK     ' if ok else 'MISSING'}  {k:20s} '{v}'  events={n:,}")

print("\nALL 42 ACTIVITIES IN THE LOG (this is what the taxonomy must be built from):")
print(counts.to_string())

# ------------------------------------------------------------------ Q2/Q3
print("\n" + "=" * 72)
print("Q2/Q3 — BLOCK RATE AND LABEL GATE, REAL NUMBERS")
print("=" * 72)
f = data.case_features(df)
f = L.build(f, df)

print(f"  cases                     : {len(f):,}")
print(f"  was_blocked (Set Block)   : {f['was_blocked'].sum():,} "
      f"({100*f['was_blocked'].mean():.2f}%)")
print(f"  block_removed (Remove)    : {f['block_removed'].sum():,} "
      f"({100*f['block_removed'].mean():.2f}%)")
print(f"  has_gr                    : {f['has_gr'].sum():,} "
      f"({100*f['has_gr'].mean():.2f}%)")
print(f"  variance computable       : {f['abs_variance_pct'].notna().sum():,} "
      f"({100*f['abs_variance_pct'].notna().mean():.2f}%)")

if f["was_blocked"].sum() == 0 and f["block_removed"].sum() > 0:
    print("\n  >>> CONFIRMED DEFECT: blocks are REMOVED but never SET in this log.")
    print("  >>> was_blocked must be derived from Remove Payment Block, not Set.")

print("\nLABEL GATE:")
for k, v in L.label_coverage_report(f).items():
    print(f"  {k}: {v}")

print("\nOUTCOME LABEL DISTRIBUTION:")
print(f["outcome_label"].value_counts().to_string())

print("\nEXCEPTION CLASS DISTRIBUTION:")
print(f["exception_class"].value_counts().to_string())

# ------------------------------------------------------------------ Q4
print("\n" + "=" * 72)
print("Q4 — FLOW-TYPE CONTAMINATION OF THE TAXONOMY")
print("=" * 72)
print("BPI 2019 mixes four flows. Two-way-match and consignment items have no")
print("goods receipt BY DESIGN, so classifying them MISSING_GOODS_RECEIPT would")
print("fabricate an exception class.\n")

for col in [C.ITEMTYPE_COL, "case:Item Category", C.GR_BASED_IV_COL,
            C.GOODS_RECEIPT_COL, C.DOCTYPE_COL]:
    if col in df.columns:
        print(f"  {col}: {dict(df[col].value_counts().head(8))}")

if "item_type" in f.columns and f["item_type"].notna().any():
    print("\n  has_gr BY ITEM TYPE — any type with low has_gr is a legitimate")
    print("  no-GR flow, not an exception:")
    print(f.groupby("item_type").agg(
        n=("case_id", "size"),
        has_gr_pct=("has_gr", lambda s: round(100 * s.mean(), 1)),
        classified_missing_gr=("exception_class",
                               lambda s: int((s == L.MISSING_GR).sum())),
    ).to_string())

print("\n" + "=" * 72)
print("Paste this entire output back.")
print("=" * 72)
