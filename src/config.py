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
# AUTO-DETECTED. If a converted log exists on disk, the pipeline uses it and
# runs in real mode. If not, it falls back to the synthetic fixture so the
# harness still runs. You do not need to edit anything here.
#
# This is deliberate: hand-editing a source flag before every run is a step that
# gets forgotten, and forgetting it means reporting fixture numbers as findings.
# The stamp on every output tells you which mode actually ran.
import os as _os

_CANDIDATES = [
    "data/bpi2019.parquet",
    "data/log.parquet",
    "data/BPI_Challenge_2019.parquet",
]

_found = next((p for p in _CANDIDATES if _os.path.exists(p)), None)

DATA_SOURCE = "real" if _found else "synthetic"
PARQUET_PATH = _found or "data/log.parquet"
REAL_LOG_PATH = "data/BPI_Challenge_2019.xes"

# Force a mode if you ever need to:
#   DATA_SOURCE = "synthetic"   (ignore the real log, test the harness)

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

# BPI 2019 logs "Remove Payment Block" ~57k times but "Set Payment Block" only
# ~124 times: SAP does not write the block-set event to this log. A block that
# was removed must have existed, so blocked status is inferred from the removal.
#
# Consequence, and it goes in the limitations section: the analysis is
# conditioned on blocks that were EVENTUALLY REMOVED. Blocks still open at the
# end of the log are invisible, so resolution times are survivor-biased.
BLOCK_INFERRED_FROM_REMOVAL = True
UNBLOCK_ACTS = [A_REMOVE_BLOCK]
INVOICE_ACTS = [A_VENDOR_INVOICE, A_INVOICE_RECEIPT, A_CLEAR_INVOICE]
CANCEL_ACTS = [A_CANCEL_INVOICE]
GR_ACTS = [A_GOODS_RECEIPT]

# ------------------------------------------------- flow types / GR expectation
# BPI 2019 mixes four flows. Two-way-match and some consignment lines have NO
# goods receipt BY DESIGN. Classifying those MISSING_GOODS_RECEIPT fabricates an
# exception class, so absence of a GR is only an exception where a GR was
# EXPECTED. The case:Goods Receipt boolean states that expectation directly and
# is the correct discriminator; item category is a fallback.
GR_EXPECTED_COL = "case:Goods Receipt"
ITEM_CATEGORY_COL = "case:Item Category"
NO_GR_ITEM_CATEGORIES = ["2-way match", "2-way", "Consignment"]

# ---------------------------------------------------- analysis population
# ~25% of cases never reach a terminal state in the extract: still in flight,
# deleted, or completing outside this log. They carry no resolution to predict,
# so they are EXCLUDED from evaluation and the exclusion is reported. This is
# the Stage 1 scope-narrowing decision, taken on evidence rather than silently.
EXCLUDE_NON_TERMINAL_CASES = True

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
LOADED_HOURLY_COST_EUR = 25.59      # Dutch AP Analyst gross hourly benchmark; burden not included
# Source: https://www.salaryexpert.com/salary/job/accounts-payable-analyst/netherlands
EARLY_PAY_DISCOUNT_PCT = None       # e.g. 2.0 — from the log's payment terms if present
INFERENCE_COST_PER_CASE_EUR = None  # measured in Stage 3, not assumed

# --- assumptions for the value model. All three are ASSUMPTIONS, not evidence.
# The event log records system events only; it does not capture how long a human
# spent investigating. Leaving these as None is correct until each has a source
# you have actually opened — the value model refuses to run while any is unset.
MINUTES_PER_INVESTIGATION = 30      # base case from Nexus AP's published 15–45 min range
MINUTES_SENSITIVITY = [15, 30, 45]  # published range, retained rather than collapsed
# Source: https://www.nexusap.com/research/invoice-processing-time-benchmarks
FALSE_AUTOMATION_SEVERITY = 0.15    # judgment: 15% of exposure at risk in a wrong release
# Judgment only; no benchmark is claimed. Sensitivity bounds the assumption.
FALSE_AUTOMATION_SEVERITY_SENSITIVITY = [0.10, 0.15, 0.25]
                                    # risk when a payment clears wrongly, plus the
                                    # cost of the control failure. Sensitivity-test
                                    # this; it is the softest number in the model.


def stamp():
    """Every output file carries this. Prevents reporting synthetic numbers."""
    if DATA_SOURCE == "synthetic":
        return "SYNTHETIC TEST FIXTURE — NOT FOR REPORTING"
    return "BPI Challenge 2019 (4TU.ResearchData, DOI 10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1)"
