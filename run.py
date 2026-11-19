# Usage: python run.py input.csv output.csv   (Ctrl+C to stop)
import io
import sys
import time
from pathlib import Path

import pandas as pd

from aqi import compute_aqi
from imputation import VARIABLES, impute
from outlier_detection import detect_outliers

MODEL = 'mice'
CHECK_EVERY = 10
COLUMNS = {'T': 'Temperature', 'H': 'Humidity', 'CO': 'CO', 'NO2': 'NO2', 'PM2.5': 'PM2.5', 'PM10': 'PM10'}


def read(path):
    text = Path(path).read_text() if Path(path).exists() else ''
    text = text[:text.rfind('\n') + 1]  # skip a half-written last line
    if not text.strip():
        return None
    df = pd.read_csv(io.StringIO(text))
    df.columns = df.columns.str.strip()
    df['_t'] = pd.to_datetime(df['Timestamp'])
    return df


def process(raw, new):
    df = raw[raw['_t'] >= new['_t'].min() - pd.Timedelta(days=3)]  # the models need 3 days of history
    df = df.rename(columns=COLUMNS).assign(_t=df['_t'].dt.floor('15min'))
    df = df.drop_duplicates('_t', keep='last').set_index('_t').sort_index()
    data = df[VARIABLES].apply(pd.to_numeric, errors='coerce').asfreq('15min')

    filled = impute(detect_outliers(data), MODEL)
    aqi = compute_aqi(filled)

    t = new['_t'].dt.floor('15min')
    out = new.drop(columns='_t')
    for col, var in COLUMNS.items():
        out[col] = filled.loc[t, var].round(3).values
    out['AQI'] = aqi.loc[t, 'AQI'].values
    return out


def main(in_path, out_path):
    out_path = Path(out_path)
    done = None
    if out_path.exists() and out_path.stat().st_size:
        done = pd.to_datetime(pd.read_csv(out_path)['Timestamp']).max()
    print(f'Watching {in_path} (Ctrl+C to stop)')
    try:
        while True:
            raw = read(in_path)
            if raw is not None:
                new = raw if done is None else raw[raw['_t'] > done]
                if len(new):
                    out = process(raw, new)
                    out.to_csv(out_path, mode='a', header=not out_path.exists(), index=False)
                    print(out.tail(10).to_string(index=False))
                    done = new['_t'].max()
            time.sleep(CHECK_EVERY)
    except KeyboardInterrupt:
        print('Stopped.')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
