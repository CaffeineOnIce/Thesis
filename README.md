# Air-quality imputation and AQI

Watches a CSV of 15-minute air-quality readings. Each new row is cleaned, its gaps are filled, and its AQI is calculated, saved and shown live.

```
input CSV → outlier detection → imputation → AQI → output CSV
```

## Files

| Path | Purpose |
|---|---|
| `run.py` | Watches the input CSV and processes each new row until stopped |
| `outlier_detection.py` | Turns outliers into blanks (**template**) |
| `imputation.py` | Fills blanks using a model from `models/` |
| `aqi.py` | Calculates AQI for every row (CPCB NAQI: 24 h mean for PM2.5, PM10, NO2; 8 h for CO) |
| `imputation.ipynb` | Kaggle notebook that trains and saves the models |
| `models/` | Trained models (`.joblib`) |
| `results/`, `figs/`, `__results___files/` | Notebook results and figures |

## How to run

1. Install Python 3.10–3.13.
2. Install the packages:
   ```
   pip install -r requirements.txt
   ```
3. Check that `models/` contains `dynamic_imputation.joblib`, `mice_extratrees.joblib` and `stacking_ensemble.joblib`.
4. Prepare the input CSV with these columns:

   | Column | Unit |
   |---|---|
   | `Timestamp` | — |
   | `PM2.5`, `PM10`, `NO2` | µg/m³ |
   | `CO` | mg/m³ |
   | `T` (temperature) | °C |
   | `H` (humidity) | % |

   If your column names differ, edit `COLUMNS` in `run.py`.
5. Run:
   ```
   python run.py input.csv output.csv
   ```
   It first processes the rows already in `input.csv`, then checks the file every 10 seconds.
   Each new row goes through outlier detection → imputation → AQI, is appended to `output.csv`
   and printed in the terminal.
6. Press **Ctrl+C** to stop. Running it again continues after the last row in `output.csv`.

`output.csv` has the same columns as `input.csv` (gaps filled) plus an `AQI` column.

Settings at the top of `run.py`: `MODEL` (`'mice'`, `'dynamic'` or `'stacking'`), `CHECK_EVERY` (seconds between checks), `COLUMNS` (input column names).

## Notes

- `outlier_detection.py` is a placeholder. Replace it, but keep the function name `detect_outliers`.
- AQI is blank for the first ~16 hours of an input file. `aqi.py` follows two CPCB rules:
  - an average counts only with enough data: 16 h for the 24 h averages (PM2.5, PM10, NO2), 6 h for the 8 h average (CO)
  - AQI needs at least 3 pollutants, one of them PM2.5 or PM10

  After the first 16 h every row gets an AQI, because `run.py` always passes the previous 3 days of data.
- AQI is not rounded (e.g. `61.59`).
- Keep `scikit-learn==1.6.1`. The models may not load with another version.
