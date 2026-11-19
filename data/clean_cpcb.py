"""Clean CPCB Jadavpur 15-min data -> data/cpcb_15min_clean.parquet + data/observed_mask.parquet.
Usage: python data/clean_cpcb.py raw1.xlsx raw2.xlsx ...   (one file per CPCB download)"""
import sys
import numpy as np
import pandas as pd

# Edit to match the exact column headers of your CPCB download.
RAW_COLS = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "CO": "co", "AT": "temp", "RH": "rh"}
TIME_COL = "To Date"                     # window end, matches the pipeline's ts
VARS = ["pm25", "pm10", "no2", "co", "temp", "rh"]
LIMITS = {"pm25": (0, 1000), "pm10": (0, 1000), "no2": (0, 1000), "co": (0, 50), "temp": (5, 45), "rh": (0, 100)}

def runs(cond: pd.Series) -> pd.Series:
    """Length of the run of identical consecutive values each row belongs to."""
    grp = (cond != cond.shift()).cumsum()
    return cond.groupby(grp).transform("size")

def load(paths):
    frames = []
    for p in paths:
        df = pd.read_excel(p) if p.endswith(("xls", "xlsx")) else pd.read_csv(p)
        df.columns = [str(c).split(" (")[0].strip() for c in df.columns]   # "PM2.5 (ug/m3)" -> "PM2.5"
        df = df.rename(columns=RAW_COLS)
        df["ts"] = pd.to_datetime(df[TIME_COL], dayfirst=True)
        frames.append(df.set_index("ts")[VARS])
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated()].apply(pd.to_numeric, errors="coerce")
    return df.asfreq("15min")

def clean(df: pd.DataFrame):
    report = {}
    out = df.copy()
    for v in VARS:
        lo, hi = LIMITS[v]
        bad = (out[v] < lo) | (out[v] > hi)
        report[f"{v}_out_of_range"] = int(bad.sum()); out.loc[bad, v] = np.nan
        s = out[v]
        stuck = s.notna() & (runs(s.fillna(-9999)) >= 16)            # unchanged for >= 4 h
        report[f"{v}_stuck"] = int(stuck.sum()); out.loc[stuck, v] = np.nan
    sat = out["rh"] >= 99.5
    sat_long = sat & (runs(sat) > 24)                                  # saturated > 6 h
    report["rh_saturated"] = int(sat_long.sum()); out.loc[sat_long, "rh"] = np.nan
    bad_ratio = out["pm25"] > 1.1 * out["pm10"]
    report["pm25_gt_pm10_rows"] = int(bad_ratio.sum())
    observed = out.notna()
    observed.loc[bad_ratio, ["pm25", "pm10"]] = False                 # kept, but never scored
    return out, observed, report

if __name__ == "__main__":
    raw = load(sys.argv[1:])
    df, observed, report = clean(raw)
    df.to_parquet("data/cpcb_15min_clean.parquet")
    observed.to_parquet("data/observed_mask.parquet")
    with open("data/data_report.md", "w") as f:
        f.write("# CPCB cleaning report\n\n")
        for k, v in report.items():
            f.write(f"- {k}: {v}\n")
        season = df.index.month.map({12: "winter", 1: "winter", 2: "winter", 3: "summer", 4: "summer", 5: "summer",
                                     6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "post_monsoon", 11: "post_monsoon"})
        f.write("\n## Missing % after cleaning, by year and season\n\n")
        f.write((df.isna().groupby([df.index.year, season]).mean() * 100).round(1).to_markdown())
    print(report)
