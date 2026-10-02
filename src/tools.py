"""ERP evidence tools with a single decision-time filtering choke point."""

import numpy as np
import pandas as pd

import config as C
if not hasattr(C, "CASE_COL"):
    from src import config as C
try:
    from decision_time import decision_time
except ModuleNotFoundError:
    from .decision_time import decision_time


class ToolBox:
    """Serve case facts from events visible at or before ``as_of``."""

    def __init__(self, cases: pd.DataFrame, events: pd.DataFrame | None = None):
        self.cases = cases.set_index("case_id", drop=False)
        self.events = events.copy() if events is not None else None
        if self.events is not None:
            self.events = self.events.rename(columns={
                C.CASE_COL: "case_id", C.ACT_COL: "activity", C.TS_COL: "timestamp"})
            self.events["case_id"] = self.events["case_id"].astype(str)
            self.events["timestamp"] = pd.to_datetime(self.events["timestamp"], utc=True)

    def decision_time(self, case_id):
        if self.events is None:
            row = self.cases.loc[case_id]
            return row.get("anchor_ts")
        case = self.events[self.events.case_id == str(case_id)]
        return decision_time(case)

    def events_until(self, case_id, as_of):
        """Return only this case's events with timestamp <= the cutoff."""
        if self.events is None:
            return pd.DataFrame()
        case = self.events[self.events.case_id == str(case_id)]
        if as_of is None:
            return case.iloc[0:0].copy()
        cutoff = pd.Timestamp(as_of)
        return case[case.timestamp <= cutoff].sort_values("timestamp")

    @staticmethod
    def _ok(payload, records=None):
        out = dict(payload)
        out["status"] = "ok"
        out["records"] = list(records if records is not None else [dict(payload)])
        return out

    @staticmethod
    def _error(message):
        return {"status": "error", "records": [], "error": message}

    def _row(self, case_id):
        try:
            return self.cases.loc[case_id]
        except KeyError:
            raise KeyError(f"case {case_id} not found")

    # ------------------------------------------------------------- L1: ERP data
    def get_invoice(self, case_id, as_of=None):
        r = self._row(case_id)
        visible = self.events_until(case_id, as_of)
        if self.events is None:
            n_ir = int(r["pre_n_ir"]); has_gr = bool(r["pre_has_gr"])
            before = bool(r["invoice_before_gr"])
        else:
            ir = visible[visible.activity == C.A_INVOICE_RECEIPT]
            gr = visible[visible.activity.isin(C.GR_ACTS)]
            n_ir = len(ir); has_gr = not gr.empty
            before = bool(not ir.empty and not gr.empty and ir.timestamp.min() < gr.timestamp.min())
        payload = {"case_id": case_id, "exposure_eur": _f(r["exposure_eur"]),
                   "n_invoice_receipts": n_ir, "repeated_receipt_pattern": n_ir > 1,
                   "invoice_received_before_goods_receipt": before,
                   "goods_receipt_present": has_gr}
        return self._ok(payload, [payload] if n_ir else [])

    def lookup_po(self, case_id, as_of=None):
        r = self._row(case_id)
        visible = self.events_until(case_id, as_of)
        if self.events is None:
            n_gr, n_ir = int(r["pre_n_gr"]), int(r["pre_n_ir"])
            amended = bool(r["pre_price_change"] or r["pre_qty_change"])
            changed_after = bool(r.get("po_changed_after_invoice", False))
        else:
            n_gr = int(visible.activity.isin(C.GR_ACTS).sum())
            n_ir = int((visible.activity == C.A_INVOICE_RECEIPT).sum())
            invoice_ts = visible.loc[visible.activity == C.A_INVOICE_RECEIPT, "timestamp"]
            amended = bool(visible[visible.activity.isin(C.PRICE_CHANGE_ACTS + C.QTY_CHANGE_ACTS)]
                           .timestamp.le(invoice_ts.min()).any()) if not invoice_ts.empty else False
            changes = visible[visible.activity.isin(C.PRICE_CHANGE_ACTS + C.QTY_CHANGE_ACTS)]
            changed_after = bool(not invoice_ts.empty
                                 and changes.timestamp.gt(invoice_ts.min()).any())
        payload = {"case_id": case_id, "net_worth_eur": _f(r["exposure_eur"]),
                   "item_type": r.get("item_type"), "spend_area": r.get("spend_area"),
                   "goods_receipt_count": n_gr, "invoice_receipt_count": n_ir,
                   "gr_ir_count_mismatch": bool(n_gr != n_ir and (n_gr or n_ir)),
                   "po_amended_before_invoice": amended,
                   "goods_receipt_expected": bool(r["gr_expected"]),
                   "po_changed_after_invoice": changed_after}
        return self._ok(payload, [payload])

    def lookup_goods_receipt(self, case_id, as_of=None):
        r = self._row(case_id)
        visible = self.events_until(case_id, as_of)
        count = int(r["pre_n_gr"]) if self.events is None else int(visible.activity.isin(C.GR_ACTS).sum())
        payload = {"case_id": case_id, "goods_receipt_recorded": count > 0,
                   "goods_receipt_count": count, "goods_receipt_expected": bool(r["gr_expected"]),
                   "sequence_ok_gr_before_invoice": not bool(r["invoice_before_gr"])}
        return self._ok(payload, [{"case_id": case_id}] if count else [])

    # -------------------------------------------------------- L3: internal history
    def check_duplicate_payment(self, case_id, as_of=None):
        r = self._row(case_id)
        visible = self.events_until(case_id, as_of)
        n = int(r["pre_n_ir"]) if self.events is None else int((visible.activity == C.A_INVOICE_RECEIPT).sum())
        payload = {"case_id": case_id, "invoice_receipt_events": n,
                   "repeated_receipt_pattern": n > 1,
                   "goods_receipt_count": int(r["pre_n_gr"]) if self.events is None
                   else int(visible.activity.isin(C.GR_ACTS).sum())}
        return self._ok(payload, [payload] if n else [])

    def lookup_vendor_history(self, case_id, as_of=None):
        r = self._row(case_id)
        vendor = r.get("vendor")
        if self.events is None or as_of is None or vendor is None:
            return self._ok({"vendor": vendor, "available": False,
                             "reason": "dated prior-case history is unavailable"}, [])

        cutoff = pd.Timestamp(as_of)
        ended = self.events[
            self.events.activity.isin([C.A_REMOVE_BLOCK, C.A_CLEAR_INVOICE])
            & (self.events.timestamp < cutoff)
        ]
        prior_ids = set(ended.case_id.astype(str)) - {str(case_id)}
        prior = self.cases[self.cases.case_id.astype(str).isin(prior_ids)]
        if prior.empty or "vendor" not in prior:
            return self._ok({"vendor": vendor, "available": False}, [])

        population_rate = float(prior.was_blocked.mean())
        vendor_cases = prior[prior.vendor == vendor]
        if vendor_cases.empty:
            return self._ok({"vendor": vendor, "available": False}, [])
        block_rate = float(vendor_cases.was_blocked.mean())
        current_class = r.get("exception_class")
        same_class = (vendor_cases[vendor_cases.exception_class == current_class]
                      if current_class is not None and "exception_class" in vendor_cases
                      else vendor_cases.iloc[0:0])
        same_class_rate = (float(same_class.was_blocked.mean())
                           if not same_class.empty else None)
        payload = {
            "vendor": vendor,
            "vendor_case_count": int(len(vendor_cases)),
            "vendor_block_rate": round(block_rate, 4),
            "population_block_rate": round(population_rate, 4),
            "vendor_correction_rate": round(float(vendor_cases.post_price_change.mean()), 4),
            "elevated_vs_population": bool(block_rate > 1.5 * population_rate),
            "same_class_case_count": int(len(same_class)),
            "same_class_block_rate": (round(same_class_rate, 4)
                                      if same_class_rate is not None else None),
            "same_class_correction_rate": (
                round(float(same_class.post_price_change.mean()), 4)
                if not same_class.empty else None),
            "same_class_recurrence": bool(len(same_class) >= 2),
        }
        return self._ok(payload, [payload])

    # ------------------------------------------------------------- L2: policy
    def lookup_policy(self, case_id=None, as_of=None):
        payload = {"price_tolerance_pct": C.PRICE_TOLERANCE_PCT,
                   "quantity_tolerance_pct": C.QTY_TOLERANCE_PCT,
                   "escalation_cap_eur": C.APPROVAL_VALUE_CAP,
                   "human_disposition_required": True,
                   "near_miss_band_pct": C.NEAR_MISS_BAND_PCT,
                   "policy_version": C.POLICY_VERSION}
        return self._ok(payload, [payload])

    def call(self, name, case_id, as_of=None):
        fn = getattr(self, name, None)
        if fn is None:
            return self._error(f"unknown tool {name}")
        try:
            return fn(case_id, as_of=as_of)
        except KeyError as exc:
            return self._error(str(exc))


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
        t("get_invoice", "Invoice event details for the case."),
        t("lookup_po", "Purchase order terms and amendments."),
        t("lookup_goods_receipt", "Goods receipt and GR/IR sequencing."),
        t("check_duplicate_payment", "Repeated invoice-receipt patterns."),
        t("lookup_vendor_history", "Historical vendor patterns."),
        {"name": "lookup_policy", "description": "Company tolerance thresholds and approval bands.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
    ]
