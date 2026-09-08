"""
config.py — THE ONLY FILE YOU EDIT AFTER STAGE 0.

Every other module reads names from here. When phase0_recon.py prints the real
activity list and column list, correct anything below that doesn't match, and
the whole pipeline follows.

Defaults reflect the structure reported in published BPI Challenge 2019 work.
They are STARTING GUESSES. Stage 0 output overrides them. If recon disagrees
with this file, recon wins.
"""

# ---------------------------------------------------------------- data source
# "synthetic" = test fixture, safe to run tonight, NEVER report these numbers.
# "real"      = the BPI 2019 log.
DATA_SOURCE = "real"

REAL_LOG_PATH = "data/BPI_Challenge_2019.csv"
PARQUET_PATH = "data/bpi2019.parquet"

# ------------------------------------------------------------- core XES columns
CASE_COL = "case:concept:name"
ACT_COL = "concept:name"
TS_COL = "time:timestamp"
USER_COL = "org:resource"          # if absent, touchless rate is redefined structurally

# ------------------------------------------------------------ attribute columns
VENDOR_COL = "case:Vendor"
VALUE_COL = "Cumulative net worth (EUR)"
DOCTYPE_COL = "case:Document Type"
ITEMTYPE_COL = "case:Item Type"
SPEND_COL = "case:Spend area text"
GR_BASED_IV_COL = "case:GR-Based Inv. Verif."
GOODS_RECEIPT_COL = "case:Goods Receipt"

# --------------------------------------------------------------- activity names
# Correct these against Stage 0 section 2. Anything left unmatched is inert:
# the pipeline reports it as "activity not found" rather than silently failing.
A_CREATE_PO = "Create Purchase Order Item"
A_GOODS_RECEIPT = "Record Goods Receipt"
A_VENDOR_INVOICE = "Vendor creates invoice"
A_INVOICE_RECEIPT = "Record Invoice Receipt"
A_CLEAR_INVOICE = "Clear Invoice"
A_REMOVE_BLOCK = "Remove Payment Block"
A_CHANGE_PRICE = "Change Price"
A_CHANGE_QUANTITY = "Change Quantity"
A_CANCEL_INVOICE = "Cancel Invoice Receipt"
A_SET_BLOCK = "Set Payment Block"
A_DELETE_LINE = "Delete Purchase Order Item"
A_CHANGE_APPROVAL = "Change Approval for Purchase Order"

# Grouping used by the taxonomy and the rules engine.
PRICE_CHANGE_ACTS = [A_CHANGE_PRICE]
QTY_CHANGE_ACTS = [A_CHANGE_QUANTITY]
BLOCK_ACTS = [A_SET_BLOCK]
UNBLOCK_ACTS = [A_REMOVE_BLOCK]
INVOICE_ACTS = [A_VENDOR_INVOICE, A_INVOICE_RECEIPT, A_CLEAR_INVOICE]
CANCEL_ACTS = [A_CANCEL_INVOICE]
GR_ACTS = [A_GOODS_RECEIPT]

# ------------------------------------------------------- user classification
# Touchless rate depends on separating batch/system actors from human clerks.
# Stage 0 section 5 prints the real values. Correct this list.
BATCH_USER_PATTERNS = ["batch", "system", "auto", "nonhuman", "_wf"]

# ------------------------------------------------------------------ thresholds
# Company policy layer. These are POLICY, not findings — they belong in
# docs/decision_rights.md and they are read by both engines.
PRICE_TOLERANCE_PCT = 2.0       # SAP tolerance key analogue, price variance
QTY_TOLERANCE_PCT = 5.0         # quantity variance
AUTO_RESOLVE_VALUE_CAP = 5000.0    # EUR — above this, never auto-resolve
APPROVAL_VALUE_CAP = 50000.0       # EUR — above this, always escalate
NEAR_MISS_BAND_PCT = 0.5        # within this of a threshold = near_miss flag

POLICY_VERSION = "v1.0"
PRECISION_THRESHOLD = 0.95      # pilot design choice, NOT an industry standard
SENSITIVITY_SWEEP = [0.90, 0.93, 0.95, 0.97]

# -------------------------------------------------------------------- eval set
EVAL_SET_SIZE = 200
RANDOM_SEED = 42

# ------------------------------------------------------------------ cost model
# Fill from an opened source before reporting. Placeholders are flagged loudly.
LOADED_HOURLY_COST_EUR = None       # e.g. 35.0 — MUST be sourced, not guessed
EARLY_PAY_DISCOUNT_PCT = None       # e.g. 2.0 — from the log's payment terms if present
INFERENCE_COST_PER_CASE_EUR = None  # measured in Stage 3, not assumed


def stamp():
    """Every output file carries this. Prevents reporting synthetic numbers."""
    if DATA_SOURCE == "synthetic":
        return "SYNTHETIC TEST FIXTURE — NOT FOR REPORTING"
    return "BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)"
