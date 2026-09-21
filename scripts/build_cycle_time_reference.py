"""Generate config/cycle_time_reference.csv from closed non-evaluation cases."""

from datetime import date
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config as C
import data
import labels
from priority import block_intervals, class_medians, START_ACTIVITY, END_ACTIVITIES

OUT = ROOT / "reference" / "cycle_time_reference.csv"


def main():
    events = data.load_log()
    log = events.rename(columns={C.CASE_COL: "case_id", C.ACT_COL: "activity",
                                 C.TS_COL: "timestamp"})
    features = labels.build(data.case_features(None, with_variants=False), None)
    label_frame = features[["case_id", "exception_class"]].rename(
        columns={"exception_class": "exception_type"})
    eval_path = ROOT / "outputs" / "eval_set.csv"
    eval_ids = pd.read_csv(eval_path)["case_id"].astype(str).tolist() if eval_path.exists() else []
    medians = class_medians(block_intervals(log[["case_id", "activity", "timestamp"]]),
                            label_frame.assign(case_id=label_frame.case_id.astype(str)),
                            eval_ids)
    output = medians.reset_index().rename(columns={"index": "exception_type"})
    output["median_days"] = output["median_days"].round(1)
    output["n"] = output["n"].astype(int)
    output["start_activity"] = START_ACTIVITY
    output["end_activities"] = "|".join(END_ACTIVITIES)
    output["source"] = "BPI Challenge 2019, closed non-eval cases"
    output["generated_on"] = date.today().isoformat()
    OUT.parent.mkdir(exist_ok=True)
    output.to_csv(OUT, index=False)
    print(output[["exception_type", "median_days", "n"]].to_string(index=False))


if __name__ == "__main__":
    main()
