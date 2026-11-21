# Usage: python run.py ~/pollusense/edge/records_15min.csv output/edge_output.csv   (Ctrl+C to stop)
import io
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from data.timestamps import to_window_end, to_window_start
from impute.aqi import compute_aqi
from impute.impute import VARIABLES, impute
from pipeline.live_detectors import make_live_detectors

MODEL = 'mice'
CHECK_EVERY = 10
TIME_COL = 'datetime_ist'
COLUMNS = {'pm25': 'PM2.5', 'pm10': 'PM10', 'co_mgm3': 'CO', 'no2_ugm3': 'NO2', 'temp': 'Temperature', 'rh': 'Humidity'}
DETECTOR_NAMES = {'PM2.5': 'pm25', 'PM10': 'pm10', 'CO': 'co', 'NO2': 'no2', 'Temperature': 'temp', 'Humidity': 'rh'}
HISTORY = pd.Timedelta(days=3)


def read(path):
    text = path.read_text() if path.exists() else ''
    text = text.replace('\x00', '')  # NUL bytes left by a power cut during a write
    text = text[:text.rfind('\n') + 1]  # skip a half-written last line
    if not text.strip():
        return None
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = df.columns.str.strip()
    missing = [c for c in [TIME_COL, *COLUMNS] if c not in df.columns]
    if missing:
        sys.exit(f'columns {missing} not found in {path}; found {list(df.columns)}')
    df['_t'] = pd.to_datetime(df[TIME_COL].astype(str).str.strip(), errors='coerce')
    return df.dropna(subset=['_t'])


def to_grid(raw):
    df = raw.assign(_t=raw['_t'].dt.floor('15min')).drop_duplicates('_t', keep='last').set_index('_t').sort_index()
    return df.rename(columns=COLUMNS)[VARIABLES].apply(pd.to_numeric, errors='coerce').asfreq('15min')


class Detectors:
    """Live rule check + frozen H2 Hampel (hampel/detectors.py), stepped once per 15-min row, in time order.
    Flags: 0 ok, 1 outlier (removed, then imputed), 2 missing (imputed)."""

    def __init__(self):
        self.rules, self.hampel = make_live_detectors()
        self.last, self.clean, self.flags = None, None, None

    def update(self, grid):
        new = grid if self.last is None else grid[grid.index > self.last]
        if new.empty:
            return
        rows, flags = [], []
        for ts, r in new.iterrows():
            x = {DETECTOR_NAMES[v]: float(r[v]) for v in VARIABLES}
            f = {d: 2 if np.isnan(x[d]) else 0 for d in x}
            for d in x:
                if self.rules[d].step(x[d]):
                    f[d], x[d] = 1, np.nan
            for d, h in self.hampel.items():
                if h.step(x[d], ts)[1] == 1:
                    f[d], x[d] = 1, np.nan
            rows.append([x[DETECTOR_NAMES[v]] for v in VARIABLES])
            flags.append([f[DETECTOR_NAMES[v]] for v in VARIABLES])
        clean = pd.DataFrame(rows, index=new.index, columns=VARIABLES)
        flags = pd.DataFrame(flags, index=new.index, columns=VARIABLES)
        self.clean = clean if self.clean is None else pd.concat([self.clean, clean])
        self.flags = flags if self.flags is None else pd.concat([self.flags, flags])
        self.last = new.index[-1]


def process(det, new):
    t = new['_t'].dt.floor('15min')
    window = det.clean.loc[t.min() - HISTORY:t.max()]
    filled = to_window_end(impute(to_window_start(window), MODEL))  # models were trained on CPCB window-start labels
    aqi = compute_aqi(filled)

    out = new.drop(columns='_t')
    for col, var in COLUMNS.items():
        out[col] = filled.loc[t, var].round(3).values
    out['AQI'] = aqi.loc[t, 'AQI'].round().astype('Int64').values
    for col, var in COLUMNS.items():
        out[f'flag_{col}'] = det.flags.loc[t, var].values
    return out


def widths(columns):
    return {c: max(len(c), 19 if c.startswith('datetime') else 10) for c in columns}

def show(out, header=False):
    if header:
        print(' '.join(c.rjust(w) for c, w in widths(out).items()))
        return
    for _, r in out.iterrows():
        print(' '.join(str(r[c]).rjust(w) for c, w in widths(out.columns).items()))

def main(in_path, out_path):
    in_path, out_path = Path(in_path).resolve(), Path(out_path).resolve()
    os.chdir(Path(__file__).resolve().parent)  # band files are relative to the repo root
    out_path.parent.mkdir(parents=True, exist_ok=True)
    det = Detectors()
    done = None
    if out_path.exists() and out_path.stat().st_size:
        done = pd.to_datetime(pd.read_csv(out_path)[TIME_COL].astype(str).str.strip()).max()
    print(f'Watching {in_path} (model: {MODEL}, Ctrl+C to stop)')
    header = True
    try:
        while True:
            raw = read(in_path)
            if raw is not None:
                if header:
                    show([c for c in raw.columns if c != '_t'] + ['AQI'] + [f'flag_{c}' for c in COLUMNS], header=True)
                    header = False
                det.update(to_grid(raw))
                new = raw if done is None else raw[raw['_t'] > done]
                if len(new):
                    out = process(det, new)
                    out.to_csv(out_path, mode='a', header=not out_path.exists() or not out_path.stat().st_size,
                               index=False)
                    show(out.tail(10))
                    done = new['_t'].max()
            time.sleep(CHECK_EVERY)
    except KeyboardInterrupt:
        print('Stopped.')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
