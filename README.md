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

## Models

| Method | `MODEL` in `run.py` | File in `models/` | What it is | Paper role |
|---|---|---|---|---|
| M0 | `'m0'` | `m0_locf_median.joblib` | Last observation carried forward for up to 6 h, then the training set's month × hour median | The causal floor every method must beat |
| M1 | `'dynamic'` | `dynamic_imputation.joblib` | Dynamic imputation in two passes. Pass 1 uses time and history only. Pass 2 adds the other variables' current values, replacing a missing one with its pass-1 estimate | Our earlier method, made causal |
| M2 | `'mice'` | `mice_extratrees.joblib` | Iterative imputation with ExtraTrees (MICE-style, single draw) | The MICE baseline |
| M3 | `'stacking'` | `stacking_ensemble.joblib` | Stacking: HGB + ExtraTrees + RF, with a ridge meta-learner trained on out-of-fold predictions | The ensemble baseline |
| M2-L | `'mice_light'` | `mice_extratrees_light.joblib` | M2 with 10 trees, depth 10, 2 iterations | Light variant for the constrained Pi |
| M3-L | `'stacking_light'` | `stacking_ensemble_light.joblib` | M3 with 20 trees, depth 12 | Light variant for the constrained Pi |
| HGB-native | `'hgb_native'` | `hgb_native.joblib` | One gradient-boosted model per target, trained directly on features containing NaN | Cheapest learned model |

All models are trained on 2023–2024 and tested on 2025. The tree sizes are capped (depth and leaf size): uncapped forests on about 70 000 training rows would need several GB, which no Pi can load.

In the PDF, M1 chooses the model per target on 2024. Here it uses fixed models: MLP for PM2.5 and PM10, tuned KNN for CO, Random Forest for NO2, temperature and humidity.

## How to run

1. Install Python 3.10–3.13.
2. Install the packages:
   ```
   pip install -r requirements.txt
   ```
3. Check that `models/` contains the `.joblib` file of the model you set in `run.py` (all 7 are saved by `imputation.ipynb`).
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

Settings at the top of `run.py`: `MODEL` (`'mice'`, `'dynamic'`, `'stacking'`, `'m0'`, `'mice_light'`, `'stacking_light'` or `'hgb_native'`), `CHECK_EVERY` (seconds between checks), `COLUMNS` (input column names).

## Notes

- `outlier_detection.py` is a placeholder. Replace it, but keep the function name `detect_outliers`.
- AQI is blank for the first ~16 hours of an input file. `aqi.py` follows two CPCB rules:
  - an average counts only with enough data: 16 h for the 24 h averages (PM2.5, PM10, NO2), 6 h for the 8 h average (CO)
  - AQI needs at least 3 pollutants, one of them PM2.5 or PM10

  After the first 16 h every row gets an AQI, because `run.py` always passes the previous 3 days of data.
- AQI is not rounded (e.g. `61.59`).
- Keep `scikit-learn==1.6.1`. The models may not load with another version.
