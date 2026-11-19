"""CSV -> outlier detection -> imputation -> AQI for every row -> output CSV.
Usage:  python run.py input.csv output.csv"""
import sys

import pandas as pd

from aqi import compute_aqi
from imputation import VARIABLES, impute
from outlier_detection import detect_outliers

MODEL = 'mice'

COLUMNS = {'Timestamp': 'Timestamp', 'T': 'Temperature', 'H': 'Humidity',
           'CO': 'CO', 'NO2': 'NO2', 'PM2.5': 'PM2.5', 'PM10': 'PM10'}


def load(path):
    df = pd.read_csv(path)
    df.columns = df.columns.str.strip()
    df = df.rename(columns=COLUMNS)
    df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.floor('15min')
    df = df.set_index('Timestamp').sort_index()
    df = df[~df.index.duplicated(keep='last')]
    return df[VARIABLES].apply(pd.to_numeric, errors='coerce').asfreq('15min')


def main(in_path, out_path):
    data = load(in_path)
    clean = detect_outliers(data)
    filled = impute(clean, MODEL)

    out = filled.round(3)
    out['Imputed'] = clean.isna().apply(lambda r: ','.join(r.index[r]), axis=1)
    out = out.join(compute_aqi(filled))
    out.to_csv(out_path, index_label='Timestamp')

    print(out.tail(10).to_string())
    print(f'\n{len(out)} rows saved to {out_path}, {int(clean.isna().sum().sum())} values imputed')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
