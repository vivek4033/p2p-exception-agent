"""
xes_to_parquet.py — streaming XES converter.

pm4py loads the entire log into memory as Python objects. On BPI 2019 that is
roughly 8 GB and it will fail on most laptops. This reads the XML incrementally
and never holds more than one trace at a time, so peak memory is a few hundred
MB regardless of file size.

    python xes_to_parquet.py data/BPI_Challenge_2019.xes
    python xes_to_parquet.py data/BPI_Challenge_2019.xes.gz

Writes data/log.parquet, which is what config.PARQUET_PATH points at.
Run this once; everything afterwards loads in seconds.
"""

import gzip
import os
import sys

import pandas as pd
from lxml import etree

CHUNK_TRACES = 5000     # flush to disk every N traces
OUT = "data/log.parquet"

ATTR_TAGS = {"string", "date", "int", "float", "boolean", "id"}


def _open(path):
    return gzip.open(path, "rb") if path.endswith(".gz") else open(path, "rb")


def _strip(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def _read_attrs(elem):
    """Direct attribute children of a trace or event element."""
    out = {}
    for child in elem:
        t = _strip(child.tag)
        if t in ATTR_TAGS:
            k = child.get("key")
            v = child.get("value")
            if k is not None:
                out[k] = v
    return out


def convert(path, out=OUT, chunk=CHUNK_TRACES):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    parts, buf, n_traces, n_events = [], [], 0, 0

    with _open(path) as fh:
        ctx = etree.iterparse(fh, events=("end",), recover=True, huge_tree=True)
        for _, elem in ctx:
            if _strip(elem.tag) != "trace":
                continue

            trace_attrs = {f"case:{k}": v for k, v in _read_attrs(elem).items()}
            case_id = trace_attrs.get("case:concept:name")
            trace_attrs["case:concept:name"] = case_id

            for ev in elem:
                if _strip(ev.tag) != "event":
                    continue
                row = dict(trace_attrs)
                row.update(_read_attrs(ev))
                buf.append(row)
                n_events += 1

            n_traces += 1

            # free the parsed subtree and everything before it
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]

            if n_traces % chunk == 0:
                parts.append(pd.DataFrame(buf))
                buf = []
                print(f"  {n_traces:,} traces / {n_events:,} events", flush=True)

    if buf:
        parts.append(pd.DataFrame(buf))

    df = pd.concat(parts, ignore_index=True)
    del parts

    if "time:timestamp" in df.columns:
        df["time:timestamp"] = pd.to_datetime(df["time:timestamp"],
                                              errors="coerce", utc=True, format="mixed")

    # numeric-looking attribute columns come out of XES as strings
    for c in df.columns:
        if c in ("time:timestamp", "concept:name", "case:concept:name"):
            continue
        if df[c].dtype == object:
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().mean() > 0.95:
                df[c] = conv

    df.to_parquet(out, index=False)
    print(f"\nWROTE {out}")
    print(f"  events : {len(df):,}")
    print(f"  cases  : {df['case:concept:name'].nunique():,}")
    print(f"  columns: {df.columns.tolist()}")
    print(f"  size   : {os.path.getsize(out) / 1e6:.1f} MB")
    return df


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1])
