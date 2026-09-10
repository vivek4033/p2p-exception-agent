"""
tools.py — the agent's six tools.

Design rule (guardrail 10): if a tool would not change any decision, it does not
belong in the system. After 30 cases, read the trajectory log; cut anything that
is never called or never influences the recommendation, and say why in the README.

Evidence hierarchy, enforced here rather than asserted in a doc:
  L1 ERP transaction data  — get_invoice, lookup_po, lookup_goods_receipt
  L2 company policy        — lookup_policy
  L3 internal history      — lookup_vendor_history, check_duplicate_payment
  L4 external             — NOT IMPLEMENTED. Vendor IDs are anonymised, so an
                            external lookup cannot be evaluated on real cases.
                            It stays a Tier B capability demonstration.

Note the tool name: check_duplicate_payment, not check_duplicate_invoice.
BPI 2019 exposes repeated invoice-receipt and clearing patterns, not invoice
document identifiers. Naming the tool for what the data supports is the
difference between a scoped capability and a fabricated one.
"""

import numpy as np
import pandas as pd

import config as C


class ToolBox:
    """Holds the case table and vendor aggregates; serves tool calls."""

    def __init__(self, cases: pd.DataFrame):
        self.cases = cases.set_index("case_id", drop=False)
        self._vendor_stats = self._build_vendor_stats(cases)

    @staticmethod
    def _build_vendor_stats(cases):
        if "vendor" not in cases.columns or cases["vendor"].isna().all():
            return None
        g = cases.groupby("vendor")
        return pd.DataFrame({
            "n_cases": g.size(),
            "n_blocked": g["was_blocked"].sum(),
            "block_rate": g["was_blocked"].mean(),
            "correction_rate": g["post_price_change"].mean(),
            "total_exposure_eur": g["exposure_eur"].sum(),
        })

    # ------------------------------------------------------------- L1: ERP data
    def get_invoice(self, case_id):
        r = self.cases.loc[case_id]
        return {
            "case_id": case_id,
            "exposure_eur": _f(r["exposure_eur"]),
            "n_invoice_receipts": int(r["pre_n_ir"]),
            "repeated_receipt_pattern": bool(r["pre_duplicate_ir"]),
            "invoice_received_before_goods_receipt": bool(r["invoice_before_gr"]),
            "goods_receipt_present": bool(r["pre_has_gr"]),
        }

    def lookup_po(self, case_id):
        r = self.cases.loc[case_id]
        return {
            "case_id": case_id,
            "net_worth_eur": _f(r["exposure_eur"]),
            "item_type": r.get("item_type"),
            "spend_area": r.get("spend_area"),
            "goods_receipt_count": int(r["pre_n_gr"]),
            "invoice_receipt_count": int(r["pre_n_ir"]),
            "gr_ir_count_mismatch": bool(r["gr_ir_count_mismatch"]),
            "po_amended_before_invoice": bool(r["pre_price_change"]
                                              or r["pre_qty_change"]),
            "goods_receipt_expected": bool(r["gr_expected"]),
            "note": "This log carries no per-document amounts. Net worth is a "
                    "case-level value used for exposure banding only.",
        }

    def lookup_goods_receipt(self, case_id):
        r = self.cases.loc[case_id]
        return {
            "case_id": case_id,
            "goods_receipt_recorded": bool(r["pre_has_gr"]),
            "goods_receipt_count": int(r["pre_n_gr"]),
            "goods_receipt_expected": bool(r["gr_expected"]),
            "sequence_ok_gr_before_invoice": not bool(r["invoice_before_gr"]),
        }

    # -------------------------------------------------------- L3: internal history
    def check_duplicate_payment(self, case_id):
        r = self.cases.loc[case_id]
        n = int(r["pre_n_ir"])
        return {
            "case_id": case_id,
            "invoice_receipt_events": n,
            "repeated_receipt_pattern": n > 1,
            "goods_receipt_count": int(r["pre_n_gr"]),
            "note": ("Detects repeated invoice-receipt and cancellation patterns. "
                     "The log carries no invoice document identifier, so this "
                     "cannot confirm a duplicate document — only a repeated "
                     "pattern warranting review."),
        }

    def lookup_vendor_history(self, case_id):
        r = self.cases.loc[case_id]
        v = r.get("vendor")
        if self._vendor_stats is None or v is None or v not in self._vendor_stats.index:
            return {"case_id": case_id, "vendor": v,
                    "available": False,
                    "note": "No vendor aggregate available for this case."}
        s = self._vendor_stats.loc[v]
        pop = self._vendor_stats["block_rate"].mean()
        return {
            "case_id": case_id,
            "vendor": v,
            "vendor_case_count": int(s["n_cases"]),
            "vendor_block_rate": round(float(s["block_rate"]), 4),
            "population_block_rate": round(float(pop), 4),
            "vendor_correction_rate": round(float(s["correction_rate"]), 4),
            "elevated_vs_population": bool(s["block_rate"] > 1.5 * pop),
            "note": "Vendor identifiers are anonymised. Pattern evidence only; "
                    "no external verification is possible.",
        }

    # ------------------------------------------------------------- L2: policy
    def lookup_policy(self, case_id=None):
        return {
            "price_tolerance_pct": C.PRICE_TOLERANCE_PCT,
            "quantity_tolerance_pct": C.QTY_TOLERANCE_PCT,
            "autonomous_action_cap_eur": C.AUTO_RESOLVE_VALUE_CAP,
            "escalation_cap_eur": C.APPROVAL_VALUE_CAP,
            "near_miss_band_pct": C.NEAR_MISS_BAND_PCT,
            "policy_version": C.POLICY_VERSION,
            "note": "Thresholds are policy, configured outside the model. The agent "
                    "may read them; it may not set them.",
        }

    def call(self, name, case_id):
        fn = getattr(self, name, None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(case_id)
        except KeyError:
            return {"error": f"case {case_id} not found"}


def _f(x):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) else round(x, 2)


# ------------------------------------------------- Anthropic tool-use schemas
def tool_schemas():
    cid = {"case_id": {"type": "string", "description": "The PO line item case ID."}}
    def t(name, desc):
        return {"name": name, "description": desc,
                "input_schema": {"type": "object", "properties": dict(cid),
                                 "required": ["case_id"]}}
    return [
        t("get_invoice", "Invoice event details for the case: value, receipt count, "
                         "whether it arrived before the goods receipt, block status."),
        t("lookup_po", "Purchase order terms: original value, whether price or quantity "
                       "were amended after creation, and the invoice-vs-PO variance."),
        t("lookup_goods_receipt", "Goods receipt: whether one exists, its value, and "
                                  "whether GR/IR sequencing is intact."),
        t("check_duplicate_payment", "Repeated invoice-receipt and cancellation patterns "
                                     "on this case. Cannot confirm duplicate documents."),
        t("lookup_vendor_history", "This vendor's historical block rate, mean variance and "
                                   "PO-correction rate versus the population."),
        {"name": "lookup_policy",
         "description": "Company tolerance thresholds and approval value bands.",
         "input_schema": {"type": "object",
                          "properties": {"case_id": {"type": "string"}},
                          "required": []}},
    ]
