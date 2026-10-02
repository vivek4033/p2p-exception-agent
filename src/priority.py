"""Human-queue prioritisation using a committed cycle-time reference table."""

import pandas as pd

START_ACTIVITY = "Record Invoice Receipt"
END_ACTIVITIES = ["Remove Payment Block", "Clear Invoice"]


def block_intervals(log):
    start = log[log.activity == START_ACTIVITY].groupby("case_id").timestamp.min().rename("start")
    end = log[log.activity.isin(END_ACTIVITIES)].groupby("case_id").timestamp.min().rename("end")
    intervals = pd.concat([start, end], axis=1).dropna(subset=["start"]).reset_index()
    intervals.loc[intervals.end < intervals.start, "end"] = pd.NaT
    return intervals


def class_medians(intervals, labels, eval_case_ids):
    closed = intervals.dropna(subset=["end"]).copy()
    closed["cycle_time_days"] = (closed.end - closed.start).dt.total_seconds() / 86400
    closed = closed.merge(labels, on="case_id")
    closed = closed[~closed.case_id.isin(set(eval_case_ids))]
    medians = closed.groupby("exception_type").cycle_time_days.agg(
        median_days="median", n="size")
    medians.loc["__ALL__"] = [closed.cycle_time_days.median(), len(closed)]
    return medians


def expected_days(exception_type, days_waited, medians):
    key = exception_type if exception_type in medians.index else "__ALL__"
    median = float(medians.loc[key, "median_days"])
    return max(median, float(days_waited or 0)), key, median


def build_queue(cases, intervals, medians, as_of):
    as_of = pd.Timestamp(as_of)
    queue = cases[cases.decision.isin(["HUMAN_APPROVAL", "ESCALATE"])].merge(
        intervals, on="case_id")
    queue = queue[(queue.start <= as_of) & (queue.end.isna() | (queue.end > as_of))].copy()
    queue["days_waited"] = (as_of - queue.start).dt.total_seconds() / 86400
    if queue.empty:
        return queue
    resolved = queue.apply(
        lambda row: expected_days(row.exception_type, row.days_waited, medians),
        axis=1, result_type="expand")
    queue[["expected_days_blocked", "median_source", "class_median_days"]] = resolved
    queue["queue_priority_eur_days"] = queue.exposure_eur * queue.expected_days_blocked
    queue["priority_driver"] = (queue.days_waited > queue.class_median_days).map(
        {True: "overdue", False: "class_median"})
    queue["as_of"] = as_of
    return queue.sort_values(["owner", "queue_priority_eur_days"], ascending=[True, False])


def load_reference(path="reference/cycle_time_reference.csv"):
    reference = pd.read_csv(path).set_index("exception_type")
    if "__ALL__" not in reference.index:
        raise ValueError("Reference table must include the __ALL__ fallback row.")
    return reference[["median_days", "n"]]
