#!/usr/bin/env python3
"""
A4I 2026 — Challenge 3
Generates data/bea_direct_requirements.csv, the pinned BEA coefficient table.

ROI MAINTAINERS ONLY. Students never run this — the output file ships in the repo.

WHY THIS EXISTS
---------------
The notebook needs to know, for each pair of industries, how much industry A buys
from industry B per dollar of A's output. That is BEA's "Direct Requirements"
table, and it is the thing that makes our supply edges a modelling choice built on
a published statistic rather than an invention.

BEA's API requires a free registration key. One key for us is fine; 150 attendees
each signing up on event morning is a help-desk queue we do not want, on top of the
two Colab API-enablement prompts they already have to click through. So we fetch it
once and pin the result, exactly as Challenge 2 pins data/foodkeeper.json.

USAGE
-----
    1. Get a free key (instant, email confirmation): https://apps.bea.gov/api/signup/
    2. export BEA_API_KEY=your-36-character-key
    3. python3 scripts/fetch_bea.py
    4. Commit the generated data/bea_direct_requirements.csv

OUTPUT SCHEMA — the notebook depends on exactly these three columns
-------------------------------------------------------------------
    buyer_naics4      STRING   the purchasing industry, as a 4-digit NAICS prefix
    supplier_naics4   STRING   the supplying industry, same
    coefficient       FLOAT    cents of input per dollar of buyer output

NOTE ON THE TableID
-------------------
BEA does not publish a list of TableID values, and their API guide says so
explicitly. So this script DISCOVERS the id rather than hardcoding one — see
`find_direct_requirements_table`. If that discovery fails, it prints every table
BEA offers and stops, rather than guessing. Do not replace this with a literal id
you found in a blog post.

NOTE ON THE NAICS MAPPING
-------------------------
BEA uses its own industry codes, not NAICS. BEA states its summary level
"generally corresponds to" 4-digit NAICS — note "generally". This script writes
the concordance it actually used to data/bea_naics_concordance.csv alongside the
coefficients, so the mapping is auditable rather than implied.
"""

import io
import os
import sys
import json
import csv

try:
    import requests
    import pandas as pd
except ImportError:
    sys.exit("Needs requests and pandas:  pip install requests pandas")

API = "https://apps.bea.gov/api/data/"
CONCORDANCE_URL = ("https://www.bea.gov/sites/default/files/2023-10/"
                   "BEA-Industry-and-Commodity-Codes-and-NAICS-Concordance.xlsx")

KEY = os.environ.get("BEA_API_KEY", "").strip()
if not KEY:
    sys.exit("Set BEA_API_KEY first. Free key: https://apps.bea.gov/api/signup/")
if len(KEY) != 36:
    print(f"WARNING: BEA keys are normally 36 characters; yours is {len(KEY)}.")


def bea(**params):
    params.update(UserID=KEY, ResultFormat="JSON")
    r = requests.get(API, params=params, timeout=120)
    r.raise_for_status()
    payload = r.json().get("BEAAPI", {})
    if "Error" in payload:
        sys.exit(f"BEA API error: {payload['Error']}")
    results = payload.get("Results", {})
    if isinstance(results, dict) and "Error" in results:
        sys.exit(f"BEA API error: {results['Error']}")
    return results


def find_direct_requirements_table():
    """Discover the Direct Requirements TableID rather than hardcoding it."""
    res = bea(method="GetParameterValues", DataSetName="InputOutput",
              ParameterName="TableID")
    rows = res.get("ParamValue", [])
    hits = [r for r in rows
            if "direct" in str(r.get("Description", "")).lower()
            and "requirement" in str(r.get("Description", "")).lower()]
    if not hits:
        print("Could not find a 'Direct Requirements' table. BEA offers:")
        for r in rows:
            print(f"  {r.get('Key')}: {r.get('Description')}")
        sys.exit("Pick the right one, then pass it as TABLE_ID below.")
    # Prefer the summary-level, after-redefinitions variant if several match.
    for r in hits:
        d = str(r.get("Description", "")).lower()
        if "summary" in d and "redefinition" in d:
            return r["Key"], r["Description"]
    return hits[0]["Key"], hits[0]["Description"]


def load_concordance():
    """BEA industry code -> 4-digit NAICS. Written out so it can be audited."""
    print(f"Fetching BEA/NAICS concordance...")
    r = requests.get(CONCORDANCE_URL, timeout=120)
    r.raise_for_status()
    # The workbook layout is not documented; read every sheet and find the one
    # carrying both a BEA code column and a NAICS column.
    sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, dtype=str, header=None)
    for name, raw in sheets.items():
        flat = raw.astype(str).apply(lambda c: c.str.lower())
        for hdr in range(min(12, len(raw))):
            row = list(flat.iloc[hdr].values)
            bea_col = next((i for i, v in enumerate(row) if "summary" in v or "bea" in v), None)
            nai_col = next((i for i, v in enumerate(row) if "naics" in v), None)
            if bea_col is not None and nai_col is not None:
                df = raw.iloc[hdr + 1:, [bea_col, nai_col]]
                df.columns = ["bea_code", "naics"]
                df = df.dropna()
                df["bea_code"] = df.bea_code.astype(str).str.strip()
                df["naics4"] = (df.naics.astype(str)
                                .str.extract(r"(\d+)")[0].str[:4])
                df = df[df.naics4.notna() & (df.bea_code.str.len() > 0)]
                if len(df) > 20:
                    print(f"  using sheet {name!r}, header row {hdr}: {len(df)} mappings")
                    return df[["bea_code", "naics4"]].drop_duplicates()
    sys.exit("Could not locate a BEA-code/NAICS mapping in that workbook. "
             "Open it by hand and adjust load_concordance().")


def main():
    table_id, desc = find_direct_requirements_table()
    print(f"Using TableID {table_id}: {desc}")

    res = bea(method="GetData", DataSetName="InputOutput",
              TableID=table_id, Year="ALL")
    rows = res.get("Data", [])
    if not rows:
        sys.exit("BEA returned no data rows for that table.")
    io_df = pd.DataFrame(rows)
    print(f"  {len(io_df):,} raw cells")

    year = io_df["Year"].max()
    io_df = io_df[io_df.Year == year]
    print(f"  newest year: {year}  ({len(io_df):,} cells)")

    io_df["coefficient"] = pd.to_numeric(io_df["DataValue"].astype(str)
                                         .str.replace(",", ""), errors="coerce")
    io_df = io_df[io_df.coefficient.notna() & (io_df.coefficient > 0)]

    conc = load_concordance()
    m = dict(zip(conc.bea_code, conc.naics4))

    out = pd.DataFrame({
        "supplier_naics4": io_df["RowCode"].astype(str).str.strip().map(m),
        "buyer_naics4":    io_df["ColCode"].astype(str).str.strip().map(m),
        "coefficient":     io_df["coefficient"].values,
    }).dropna()
    out = out[out.supplier_naics4 != out.buyer_naics4]
    out = (out.groupby(["buyer_naics4", "supplier_naics4"], as_index=False)
              .coefficient.max()
              .sort_values("coefficient", ascending=False))

    os.makedirs("data", exist_ok=True)
    out.to_csv("data/bea_direct_requirements.csv", index=False)
    conc.to_csv("data/bea_naics_concordance.csv", index=False)

    print()
    print(f"WROTE data/bea_direct_requirements.csv  ({len(out):,} industry pairs)")
    print(f"WROTE data/bea_naics_concordance.csv    ({len(conc):,} code mappings)")
    print(f"  buying industries  : {out.buyer_naics4.nunique()}")
    print(f"  supplying industries: {out.supplier_naics4.nunique()}")
    print()
    print("Strongest relationships, as a sanity check - these should look")
    print("economically sensible. If they do not, the concordance mapped wrong.")
    print(out.head(10).to_string(index=False))
    print()
    print(f"Source: BEA Input-Output Accounts, table {table_id}, year {year}.")
    print("Licence: public domain (https://bea.gov/help/faq/145). Commit both files.")


if __name__ == "__main__":
    main()
