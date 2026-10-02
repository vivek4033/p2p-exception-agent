"""
warm_cache.py - run Arm B live in priority order with a hard budget stop.

    venv\\Scripts\\python.exe scripts\\warm_cache.py --budget 4.00

Exception cases first (that is where the research question lives), clean cases after.
Already-cached cases cost nothing. Stops before the call that would exceed the budget.
Then run:  venv\\Scripts\\python.exe run_all.py --live
(with AGENT_CACHE_ONLY=1 set if you want a guaranteed zero-spend pass)
"""
import argparse
import os
import sys
import time

sys.path.insert(0, "src")

import config as C          # noqa: E402
import data                 # noqa: E402
import labels as L          # noqa: E402
import evaluate as E        # noqa: E402
import agent as A           # noqa: E402
from tools import ToolBox   # noqa: E402

PRICE_IN = float(os.environ.get("PRICE_IN_PER_MTOK", 3.0))
PRICE_OUT = float(os.environ.get("PRICE_OUT_PER_MTOK", 15.0))
NO_EXC = "NO_EXCEPTION"


class CountingClient:
    def __init__(self):
        from anthropic import Anthropic
        self._inner = Anthropic()
        self.in_tok = self.out_tok = self.calls = 0

    @property
    def messages(self):
        return self

    def create(self, **kw):
        r = self._inner.messages.create(**kw)
        self.calls += 1
        self.in_tok += r.usage.input_tokens
        self.out_tok += r.usage.output_tokens
        return r

    def spend(self):
        return self.in_tok / 1e6 * PRICE_IN + self.out_tok / 1e6 * PRICE_OUT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=1.50, help="USD hard stop")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set. Stopping before any API call.")
        return

    print(f"DATA SOURCE: {C.stamp()} | budget ${args.budget:.2f}", flush=True)
    f = data.case_features(None, with_variants=False)
    f = L.build(f, None)
    f, _ = L.analysis_population(f)
    ev = E.build_eval_set(f)

    col = "exception_class" if "exception_class" in ev.columns else "exception_class_derived"
    ordered = ev.assign(_clean=(ev[col] == NO_EXC)).sort_values("_clean")  # exceptions first
    print(f"Eval set {len(ev)}: {(ordered['_clean'] == False).sum()} exceptions first, "
          f"then {(ordered['_clean']).sum()} clean", flush=True)

    events = data.load_log()
    box = ToolBox(ordered, events=events)
    client = CountingClient()

    done = skipped = 0
    per_case = None
    t0 = time.time()
    for i, (_, r) in enumerate(ordered.iterrows(), 1):
        cid = r["case_id"]
        cached = os.path.exists(A._cache_key(cid, "live"))
        if not cached and per_case and client.spend() + per_case > args.budget:
            skipped = len(ordered) - i + 1
            print(f"\nBUDGET STOP before case {i}: spent ${client.spend():.3f}, "
                  f"next case ~${per_case:.3f}", flush=True)
            break
        before = client.spend()
        try:
            out, traj = A.investigate(cid, box, mock=False, client=client)
        except Exception as exc:
            print(f"\nAPI ERROR at case {i} ({cid}): {type(exc).__name__}: {exc}", flush=True)
            skipped = len(ordered) - i + 1
            break
        done += 1
        cost = client.spend() - before
        if cost > 0:
            per_case = cost if per_case is None else 0.7 * per_case + 0.3 * cost
        if i % 10 == 0 or not cached:
            print(f"  {i}/{len(ordered)} {cid} {r[col]} -> {out.get('exception_type')} "
                  f"conf={out.get('confidence')} tools={len(traj)} "
                  f"spend=${client.spend():.3f}", flush=True)

    print("\n--- SUMMARY ---")
    print(f"Processed {done}, not reached {skipped}")
    print(f"API calls {client.calls} | in {client.in_tok:,} | out {client.out_tok:,}")
    print(f"Spend this session: ${client.spend():.3f} (verify against the console)")
    print(f"Elapsed {time.time() - t0:.0f}s | cache files: {len(os.listdir(A.CACHE_DIR))}")
    if skipped:
        print("\nSome cases are NOT cached. Run run_all.py --live with AGENT_CACHE_ONLY=1 "
              "to avoid unplanned spend; uncached cases are flagged, not billed.")


if __name__ == "__main__":
    main()
