"""Decision-time definition shared by leakage audits and tool dispatch."""

import pandas as pd

BLOCK_ACTIVITY = "Set Payment Block"
INVOICE_ACTIVITY = "Record Invoice Receipt"


def decision_time(case_events):
    """Return first block time, else first invoice-receipt time, else None."""
    blocked = case_events.loc[case_events.activity == BLOCK_ACTIVITY, "timestamp"]
    if not blocked.empty:
        return blocked.min()
    invoices = case_events.loc[case_events.activity == INVOICE_ACTIVITY, "timestamp"]
    return invoices.min() if not invoices.empty else None
