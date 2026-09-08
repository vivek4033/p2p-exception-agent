"""
agent.py — the investigation agent (Arm B).

Claude API with tool calling. The agent chooses which tools to call and in what
order; that variable trajectory is what makes this an agent rather than a
pipeline. Every call is logged and the trajectories become a Stage 4 finding.

Two modes:
  mock=True   deterministic stand-in, no API calls, no cost. Use it to prove the
              harness runs end to end before spending anything.
  mock=False  real Claude API. Every response is cached to disk keyed on case ID
              and prompt hash, so re-runs are free.

The agent never decides its own authority. It emits a recommendation and a
stated confidence; policy_engine.py decides whether that may execute.
"""

import hashlib
import json
import os
import time

import config as C
import labels as L
from tools import ToolBox, tool_schemas

CACHE_DIR = "outputs/agent_cache"
MODEL = "claude-sonnet-4-6"
MAX_TURNS = 8

SYSTEM_PROMPT = f"""You are an accounts payable exception analyst at a large \
manufacturer. A purchase-order line item has been flagged. Investigate it using \
the tools available and recommend a resolution path.

You are predicting what the organisation would historically have done with this \
case. You are not asserting what is objectively correct.

Call only the tools you need. Do not call a tool whose output cannot change your \
recommendation.

Evidence authority, highest first:
  1. ERP transaction data (PO, goods receipt, invoice) — factual
  2. Company policy (tolerances, approval limits) — decision authority
  3. Internal history (vendor patterns) — supporting evidence only

When you have enough evidence, reply with ONLY a JSON object, no prose and no \
markdown fences:

{{"exception_type": one of {sorted([L.NO_EXCEPTION, L.PRICE_WITHIN_TOL, L.PRICE_OVER_TOL, L.QTY_VARIANCE, L.SEQUENCE_VIOLATION, L.DUPLICATE, L.MISSING_GR])},
 "recommendation": one of {sorted([L.OUT_AUTO_CLEARED, L.OUT_PO_CORRECTION, L.OUT_NO_PO_CORRECTION, L.OUT_CANCELLED, L.OUT_UNRESOLVED])},
 "confidence": float between 0 and 1,
 "evidence_complete": boolean,
 "exposure_eur": number,
 "evidence": [short strings, what you actually found],
 "reasoning": one or two sentences}}"""


def _cache_key(case_id, salt=""):
    h = hashlib.sha256(f"{case_id}|{MODEL}|{salt}|{SYSTEM_PROMPT}".encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{case_id}_{h}.json")


def investigate(case_id, box: ToolBox, mock=False, client=None, salt=""):
    """Returns (result_dict, trajectory_list). Cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_key(case_id, salt)
    if os.path.exists(path):
        with open(path) as fh:
            d = json.load(fh)
        return d["result"], d["trajectory"]

    if mock:
        result, traj = _mock_investigate(case_id, box)
    else:
        result, traj = _live_investigate(case_id, box, client)

    with open(path, "w") as fh:
        json.dump({"result": result, "trajectory": traj,
                   "cached_at": time.strftime("%Y-%m-%d %H:%M:%S")}, fh)
    return result, traj


# ------------------------------------------------------------------ mock mode
def _mock_investigate(case_id, box):
    """
    Deterministic stand-in. Calls tools in a plausible order and reasons over the
    same evidence a model would see. Exists ONLY to prove the harness works
    without spending money — its scores are not an AI result and must never be
    reported as one.
    """
    traj = []
    inv = box.call("get_invoice", case_id); traj.append("get_invoice")
    po = box.call("lookup_po", case_id); traj.append("lookup_po")
    pol = box.call("lookup_policy", case_id); traj.append("lookup_policy")

    var = po.get("price_variance_pct_invoice_vs_po")
    absvar = abs(var) if var is not None else None

    if inv.get("repeated_receipt_pattern") or inv.get("n_invoice_receipts", 0) > 1:
        box.call("check_duplicate_payment", case_id); traj.append("check_duplicate_payment")
        etype, rec, conf = L.DUPLICATE, L.OUT_CANCELLED, 0.62
    elif inv.get("invoice_received_before_goods_receipt"):
        box.call("lookup_goods_receipt", case_id); traj.append("lookup_goods_receipt")
        etype, rec, conf = L.SEQUENCE_VIOLATION, L.OUT_NO_PO_CORRECTION, 0.66
    elif absvar is None:
        etype, rec, conf = L.MISSING_GR, L.OUT_UNRESOLVED, 0.40
    elif absvar <= pol["price_tolerance_pct"]:
        etype, rec, conf = L.PRICE_WITHIN_TOL, L.OUT_AUTO_CLEARED, 0.95
    else:
        vh = box.call("lookup_vendor_history", case_id); traj.append("lookup_vendor_history")
        etype = L.PRICE_OVER_TOL
        if po.get("po_price_changed_after_creation"):
            rec, conf = L.OUT_PO_CORRECTION, 0.88
        elif vh.get("vendor_po_correction_rate", 0) and vh["vendor_po_correction_rate"] > 0.5:
            rec, conf = L.OUT_PO_CORRECTION, 0.71
        else:
            rec, conf = L.OUT_NO_PO_CORRECTION, 0.69

    return {
        "exception_type": etype,
        "recommendation": rec,
        "confidence": conf,
        "evidence_complete": absvar is not None,
        "exposure_eur": inv.get("invoice_value_eur") or po.get("po_value_eur"),
        "evidence": [f"variance {absvar}%" if absvar is not None else "variance not computable",
                     f"po_amended={po.get('po_price_changed_after_creation')}"],
        "reasoning": "MOCK MODE — deterministic stand-in, not a model output.",
        "mode": "mock",
    }, traj


# ------------------------------------------------------------------ live mode
def _live_investigate(case_id, box, client):
    from anthropic import Anthropic
    client = client or Anthropic()

    messages = [{"role": "user",
                 "content": f"Investigate case {case_id}. Begin by gathering evidence."}]
    traj = []

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT,
            tools=tool_schemas(), messages=messages)

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    traj.append(block.name)
                    out = box.call(block.name, block.input.get("case_id", case_id))
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(out, default=str)})
            messages.append({"role": "user", "content": results})
            continue

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(text)
            result["mode"] = "live"
        except json.JSONDecodeError:
            result = {"exception_type": None, "recommendation": L.OUT_UNRESOLVED,
                      "confidence": 0.0, "evidence_complete": False,
                      "exposure_eur": None, "evidence": [],
                      "reasoning": "Unparseable model output.",
                      "raw": text[:400], "mode": "live"}
        return result, traj

    return {"exception_type": None, "recommendation": L.OUT_UNRESOLVED,
            "confidence": 0.0, "evidence_complete": False, "exposure_eur": None,
            "evidence": [], "reasoning": f"Exceeded {MAX_TURNS} turns.",
            "mode": "live"}, traj
