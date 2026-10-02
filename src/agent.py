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

This log carries no per-document price or quantity amounts, so exceptions are \
structural: missing goods receipts, receipt/invoice count mismatches, \
out-of-sequence invoices, repeated receipts, and purchase orders amended before \
invoicing. Do not reason about price variance percentages; they do not exist here.

Call only the tools you need. Do not call a tool whose output cannot change your \
recommendation.

Evidence authority, highest first:
  1. ERP transaction data (PO, goods receipt, invoice) — factual
  2. Company policy (tolerances, approval limits) — decision authority
  3. Internal history (vendor patterns) — supporting evidence only

When you have enough evidence, reply with ONLY a JSON object, no prose and no \
markdown fences:

{{"exception_type": one of {sorted([L.NO_EXCEPTION, L.PRIOR_AMENDMENT, L.GR_IR_MISMATCH, L.SEQUENCE_VIOLATION, L.DUPLICATE, L.MISSING_GR])},
 "recommendation": one of {sorted([L.OUT_AUTO_CLEARED, L.OUT_PRICE_CORRECTION, L.OUT_QTY_CORRECTION, L.OUT_NO_CORRECTION, L.OUT_CANCELLED, L.OUT_UNRESOLVED])},
 "confidence": one of {list(L.CONFIDENCE_LEVELS)},
 "evidence_complete": boolean,
 "exposure_eur": number,
 "evidence": [short strings, what you actually found],
 "reasoning": one or two sentences}}

The recommendation is the proposed resolution outcome, never a routing choice. \\
Do not choose AUTO_RESOLVE or HUMAN_APPROVAL; Arm C owns that decision using \\
policy, confidence, evidence, and exposure."""


def _cache_key(case_id, salt=""):
    h = hashlib.sha256(f"{case_id}|{MODEL}|{salt}|{SYSTEM_PROMPT}".encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{case_id}_{h}.json")


def _normalize_confidence(value):
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in L.CONFIDENCE_LEVELS:
            return normalized
    return L.CONFIDENCE_WEAK


def _extract_json(text):
    text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def investigate(case_id, box: ToolBox, mock=False, client=None, salt=""):
    """Returns (result_dict, trajectory_list). Cached on disk."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_key(case_id, salt + ("mock" if mock else "live"))
    if os.path.exists(path):
        with open(path) as fh:
            d = json.load(fh)
        d["result"]["confidence"] = _normalize_confidence(
            d["result"].get("confidence"))
        return d["result"], d["trajectory"]

    if mock:
        result, traj = _mock_investigate(case_id, box)
    else:
        if os.environ.get("AGENT_CACHE_ONLY") == "1":
            return ({"exception_type": None, "recommendation": L.OUT_UNRESOLVED,
                     "confidence": L.CONFIDENCE_WEAK, "evidence_complete": False,
                     "exposure_eur": None,
                     "evidence": [], "reasoning": "Not cached; cache-only mode.",
                     "mode": "cache_miss", "_tool_outputs": {}}, [])
        result, traj = _live_investigate(case_id, box, client)

    with open(path, "w") as fh:
        json.dump({"result": result, "trajectory": traj,
                   "cached_at": time.strftime("%Y-%m-%d %H:%M:%S")}, fh)
    return result, traj


# ------------------------------------------------------------------ mock mode
def _mock_investigate(case_id, box):
    """
    Deterministic stand-in over the same evidence a model would see. Exists ONLY
    to prove the harness runs without spending money — its scores are not an AI
    result and must never be reported as one.
    """
    traj = []
    outputs = {}
    as_of = box.decision_time(case_id)
    outputs["get_invoice"] = box.call("get_invoice", case_id, as_of=as_of); traj.append("get_invoice")
    inv = outputs["get_invoice"]
    outputs["lookup_po"] = box.call("lookup_po", case_id, as_of=as_of); traj.append("lookup_po")
    po = outputs["lookup_po"]
    outputs["lookup_goods_receipt"] = box.call("lookup_goods_receipt", case_id, as_of=as_of); traj.append("lookup_goods_receipt")
    outputs["lookup_policy"] = box.call("lookup_policy", case_id, as_of=as_of); traj.append("lookup_policy")

    dup = inv.get("repeated_receipt_pattern") or inv.get("n_invoice_receipts", 0) > 1
    seq = inv.get("invoice_received_before_goods_receipt")
    no_gr = not inv.get("goods_receipt_present", True)
    mism = po.get("gr_ir_count_mismatch")
    prior = po.get("po_amended_before_invoice")

    if dup:
        outputs["check_duplicate_payment"] = box.call("check_duplicate_payment", case_id, as_of=as_of); traj.append("check_duplicate_payment")
        etype, rec, conf = L.DUPLICATE, L.OUT_CANCELLED, L.CONFIDENCE_INTERMEDIATE
    elif seq:
        outputs["lookup_goods_receipt"] = box.call("lookup_goods_receipt", case_id, as_of=as_of); traj.append("lookup_goods_receipt")
        etype, rec, conf = (L.SEQUENCE_VIOLATION, L.OUT_NO_CORRECTION,
                    L.CONFIDENCE_INTERMEDIATE)
    elif no_gr:
        outputs["lookup_goods_receipt"] = box.call("lookup_goods_receipt", case_id, as_of=as_of); traj.append("lookup_goods_receipt")
        etype, rec, conf = L.MISSING_GR, L.OUT_UNRESOLVED, L.CONFIDENCE_WEAK
    elif mism:
        vh = box.call("lookup_vendor_history", case_id, as_of=as_of); outputs["lookup_vendor_history"] = vh; traj.append("lookup_vendor_history")
        etype = L.GR_IR_MISMATCH
        rec, conf = ((L.OUT_QTY_CORRECTION, L.CONFIDENCE_INTERMEDIATE)
                 if vh.get("vendor_correction_rate", 0) > 0.4
                 else (L.OUT_NO_CORRECTION, L.CONFIDENCE_INTERMEDIATE))
    elif prior:
        outputs["lookup_vendor_history"] = box.call("lookup_vendor_history", case_id, as_of=as_of); traj.append("lookup_vendor_history")
        etype, rec, conf = (L.PRIOR_AMENDMENT, L.OUT_PRICE_CORRECTION,
                    L.CONFIDENCE_INTERMEDIATE)
    else:
        etype, rec, conf = L.NO_EXCEPTION, L.OUT_AUTO_CLEARED, L.CONFIDENCE_STRONG

    return {
        "exception_type": etype,
        "recommendation": rec,
        "confidence": conf,
        "evidence_complete": not no_gr,
        "exposure_eur": inv.get("exposure_eur") or po.get("net_worth_eur"),
        "evidence": [f"gr={po.get('goods_receipt_count')}",
                     f"ir={po.get('invoice_receipt_count')}",
                     f"prior_amendment={prior}"],
        "reasoning": "MOCK MODE — deterministic stand-in, not a model output.",
        "mode": "mock",
        "_tool_outputs": outputs,
    }, traj


# ------------------------------------------------------------------ live mode
def _live_investigate(case_id, box, client):
    from anthropic import Anthropic
    client = client or Anthropic()

    messages = [{"role": "user",
                 "content": f"Investigate case {case_id}. Begin by gathering evidence."}]
    traj = []
    tool_outputs = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    as_of = box.decision_time(case_id)
    parse_retries = 0

    for _ in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT,
            tools=tool_schemas(), messages=messages)
        if getattr(resp, "usage", None):
            usage["input_tokens"] += getattr(resp.usage, "input_tokens", 0) or 0
            usage["output_tokens"] += getattr(resp.usage, "output_tokens", 0) or 0

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    traj.append(block.name)
                    out = box.call(block.name, block.input.get("case_id", case_id), as_of=as_of)
                    tool_outputs[block.name] = out
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(out, default=str)})
            if results:
                messages.append({"role": "user", "content": results})
            else:
                messages.append({"role": "user",
                                 "content": "Continue the investigation or reply with ONLY the JSON object."})
            continue

        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        result = _extract_json(text)
        if result is not None:
            result["confidence"] = _normalize_confidence(result.get("confidence"))
            result["mode"] = "live"
            result["_tool_outputs"] = tool_outputs
            result["_usage"] = usage
            return result, traj

        if parse_retries == 0:
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": "Reply with ONLY the JSON object, no prose."})
            parse_retries += 1
            continue

        return {"exception_type": None, "recommendation": L.OUT_UNRESOLVED,
            "confidence": L.CONFIDENCE_WEAK, "evidence_complete": False,
                "exposure_eur": None, "evidence": [],
                "reasoning": "Unparseable model output.",
                "raw": text[:400], "mode": "live", "_tool_outputs": tool_outputs,
                "_usage": usage}, traj

    return {"exception_type": None, "recommendation": L.OUT_UNRESOLVED,
            "confidence": L.CONFIDENCE_WEAK, "evidence_complete": False,
            "exposure_eur": None,
            "evidence": [], "reasoning": f"Exceeded {MAX_TURNS} turns.",
            "mode": "live", "_tool_outputs": tool_outputs, "_usage": usage}, traj
