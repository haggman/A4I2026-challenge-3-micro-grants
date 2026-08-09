#!/usr/bin/env python3
"""
A4I 2026 - Challenge 3
Generates data/bea_direct_requirements.csv, the pinned BEA coefficient table.

ROI MAINTAINERS ONLY. Students never run this - the output file ships in the repo.

WHY THIS EXISTS
---------------
The notebook needs to know, for each pair of industries, how much industry A buys
from industry B per dollar of A's output. That is BEA's "Direct Requirements"
table, and it is what makes our supply edges a modelling choice built on a
published statistic rather than an invention.

BEA's API requires a free registration key. One key for us is fine; 150 attendees
each signing up on event morning is a help-desk queue we do not want. So we fetch
it once and pin the result, exactly as Challenge 2 pins data/foodkeeper.json.

USAGE
-----
    pip3 install requests pandas openpyxl
    export BEA_API_KEY=your-36-character-key    # https://apps.bea.gov/api/signup/
    python3 scripts/fetch_bea.py

Runs from anywhere - it resolves data/ relative to this file, not your shell's
working directory.

If table discovery cannot identify the Direct Requirements table, the script
prints every table BEA offers WITH ITS FULL RAW RECORD and stops. Pick the right
id from that list and re-run with:

    export BEA_TABLE_ID=61
    python3 scripts/fetch_bea.py

OUTPUT SCHEMA - the notebook depends on exactly these three columns
-------------------------------------------------------------------
    buyer_naics4      STRING   purchasing industry, 4-digit NAICS prefix
    supplier_naics4   STRING   supplying industry, same
    coefficient       FLOAT    cents of input per dollar of buyer output
"""

import io
import os
import sys
import json
from pathlib import Path

try:
    import requests
    import pandas as pd
except ImportError:
    sys.exit("Needs requests and pandas:  pip3 install requests pandas openpyxl")

API = "https://apps.bea.gov/api/data/"
CONCORDANCE_URL = ("https://www.bea.gov/sites/default/files/2023-10/"
                   "BEA-Industry-and-Commodity-Codes-and-NAICS-Concordance.xlsx")

# Resolve data/ from THIS FILE's location, not the shell's cwd. Running
# `python3 fetch_bea.py` from inside scripts/ used to write scripts/data/.
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

KEY = os.environ.get("BEA_API_KEY", "").strip()
if not KEY:
    sys.exit("Set BEA_API_KEY first. Free key: https://apps.bea.gov/api/signup/")
if len(KEY) != 36:
    print(f"WARNING: BEA keys are normally 36 characters; yours is {len(KEY)}.")


def bea(**params):
    params.update(UserID=KEY, ResultFormat="JSON")
    r = requests.get(API, params=params, timeout=180)
    r.raise_for_status()
    payload = r.json().get("BEAAPI", {})
    if "Error" in payload:
        sys.exit(f"BEA API error: {json.dumps(payload['Error'], indent=2)}")
    results = payload.get("Results", {})
    if isinstance(results, dict) and "Error" in results:
        sys.exit(f"BEA API error: {json.dumps(results['Error'], indent=2)}")
    return results


def row_text(row):
    """Every string value in a record, lowercased and joined.

    BEA is not consistent about what it calls the human-readable field - it has
    used Description, Desc, and TableName across datasets, and for InputOutput it
    returned None for 'Description' entirely. So we stop guessing field names and
    search the whole record.
    """
    return " ".join(str(v).lower() for v in row.values() if v is not None)


def row_key(row):
    for k in ("Key", "key", "TableID", "TableId"):
        if row.get(k) is not None:
            return str(row[k])
    return None


def find_direct_requirements_table():
    """Discover the Direct Requirements TableID. Never hardcode it - BEA does not
    publish a list of table ids and says so in their own API guide."""
    override = os.environ.get("BEA_TABLE_ID", "").strip()
    if override:
        print(f"Using BEA_TABLE_ID override: {override}")
        return override, "(supplied via BEA_TABLE_ID)"

    res = bea(method="GetParameterValues", DataSetName="InputOutput",
              ParameterName="TableID")
    rows = res.get("ParamValue", [])
    if not rows:
        sys.exit(f"BEA returned no TableID values. Raw response:\n"
                 f"{json.dumps(res, indent=2)[:2000]}")

    scored = []
    for row in rows:
        text = row_text(row)
        if "direct" in text and "requirement" in text:
            # Prefer summary level, after redefinitions, industry-by-industry.
            score = sum([
                3 * ("summary" in text),
                2 * ("after redefinition" in text or "redefinitions" in text),
                1 * ("industry" in text),
            ])
            scored.append((score, row_key(row), row))

    if scored:
        scored.sort(key=lambda t: -t[0])
        best = scored[0]
        print("Candidate Direct Requirements tables:")
        for s, k, r in scored:
            print(f"  [{s}] {k}: {row_text(r)[:110]}")
        return best[1], row_text(best[2])[:160]

    # Discovery failed. Print the FULL raw record for every table so the next
    # run can be fixed from this output alone rather than another round trip.
    print("Could not identify a 'Direct Requirements' table by description.")
    print("BEA returned these tables. Full raw records follow - find the one whose")
    print("description mentions Direct Requirements and set BEA_TABLE_ID to its id.\n")
    for row in rows:
        print(f"  {json.dumps(row)}")
    print(f"\n({len(rows)} tables returned.)")
    print("\nThen:  export BEA_TABLE_ID=<id>  &&  python3 scripts/fetch_bea.py")
    sys.exit(1)


def load_concordance():
    """BEA industry code -> 4-digit NAICS. Written out so it can be audited."""
    print("Fetching BEA/NAICS concordance...")
    r = requests.get(CONCORDANCE_URL, timeout=180)
    r.raise_for_status()
    try:
        sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None,
                               dtype=str, header=None)
    except ImportError:
        sys.exit("Reading .xlsx needs openpyxl:  pip3 install openpyxl")

    best = None
    for name, raw in sheets.items():
        low = raw.astype(str).apply(lambda c: c.str.lower())
        for hdr in range(min(15, len(raw))):
            row = list(low.iloc[hdr].values)
            bea_col = next((i for i, v in enumerate(row)
                            if "summary" in v or v.strip() == "bea code"
                            or ("bea" in v and "code" in v)), None)
            nai_col = next((i for i, v in enumerate(row) if "naics" in v), None)
            if bea_col is None or nai_col is None:
                continue
            df = raw.iloc[hdr + 1:, [bea_col, nai_col]].copy()
            df.columns = ["bea_code", "naics"]
            df = df.dropna()
            df["bea_code"] = df.bea_code.astype(str).str.strip()
            df["naics4"] = df.naics.astype(str).str.extract(r"(\d+)")[0].str[:4]
            df = df[df.naics4.notna() & (df.bea_code.str.len() > 0)
                    & (df.bea_code.str.lower() != "nan")]
            df = df[["bea_code", "naics4"]].drop_duplicates()
            if best is None or len(df) > len(best[2]):
                best = (name, hdr, df)

    if best is None or len(best[2]) < 20:
        print("\nSheets found in the workbook:")
        for name, raw in sheets.items():
            print(f"  {name!r}: {raw.shape[0]} rows x {raw.shape[1]} cols")
            print(f"    first rows: {raw.head(3).values.tolist()}")
        sys.exit("Could not locate a BEA-code/NAICS mapping. Open the workbook and "
                 "adjust load_concordance() using the sheet dump above.")

    name, hdr, df = best
    print(f"  using sheet {name!r}, header row {hdr}: {len(df)} code mappings")
    return df


def main():
    table_id, desc = find_direct_requirements_table()
    print(f"\nUsing TableID {table_id}: {desc}\n")

    res = bea(method="GetData", DataSetName="InputOutput",
              TableID=table_id, Year="ALL")
    rows = res.get("Data", [])
    if not rows:
        sys.exit(f"BEA returned no data rows for table {table_id}.\n"
                 f"Raw response head:\n{json.dumps(res, indent=2)[:1500]}")

    io_df = pd.DataFrame(rows)
    print(f"{len(io_df):,} raw cells")
    print(f"Columns BEA returned: {list(io_df.columns)}")

    if "Year" in io_df.columns:
        year = io_df["Year"].max()
        io_df = io_df[io_df.Year == year]
        print(f"Newest year: {year}  ({len(io_df):,} cells)")
    else:
        year = "unknown"

    io_df["coefficient"] = pd.to_numeric(
        io_df["DataValue"].astype(str).str.replace(",", "").str.strip(),
        errors="coerce")
    io_df = io_df[io_df.coefficient.notna() & (io_df.coefficient > 0)]
    print(f"Non-zero coefficients: {len(io_df):,}")

    conc = load_concordance()
    m = dict(zip(conc.bea_code, conc.naics4))

    out = pd.DataFrame({
        "supplier_naics4": io_df["RowCode"].astype(str).str.strip().map(m),
        "buyer_naics4":    io_df["ColCode"].astype(str).str.strip().map(m),
        "coefficient":     io_df["coefficient"].values,
    })
    mapped = out.dropna()
    print(f"Cells whose BOTH industry codes mapped to NAICS: {len(mapped):,} "
          f"of {len(out):,} ({len(mapped) / max(len(out), 1):.0%})")
    if len(mapped) < 100:
        sys.exit("Almost nothing mapped. The concordance picked the wrong columns - "
                 "inspect data/bea_naics_concordance.csv before trusting anything.")

    out = mapped[mapped.supplier_naics4 != mapped.buyer_naics4]
    out = (out.groupby(["buyer_naics4", "supplier_naics4"], as_index=False)
              .coefficient.max()
              .sort_values("coefficient", ascending=False))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    coeff_path = DATA_DIR / "bea_direct_requirements.csv"
    conc_path = DATA_DIR / "bea_naics_concordance.csv"
    out.to_csv(coeff_path, index=False)
    conc.to_csv(conc_path, index=False)

    print()
    print(f"WROTE {coeff_path}  ({len(out):,} industry pairs)")
    print(f"WROTE {conc_path}  ({len(conc):,} code mappings)")
    print(f"  buying industries   : {out.buyer_naics4.nunique()}")
    print(f"  supplying industries: {out.supplier_naics4.nunique()}")
    print()
    print("SANITY CHECK - the strongest relationships. These should look")
    print("economically sensible. If they do not, the concordance mapped wrong")
    print("and you should NOT commit these files.")
    print(out.head(10).to_string(index=False))
    print()
    print(f"Source: BEA Input-Output Accounts, table {table_id}, year {year}.")
    print("Licence: public domain (https://bea.gov/help/faq/145). Commit both files.")


if __name__ == "__main__":
    main()
