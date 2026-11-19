# Air-quality imputation and AQI

Watches a CSV of 15-minute air-quality readings. Each new row is cleaned, its gaps are filled by a trained model, and its AQI is calculated, saved and shown live.

```
input.csv → run.py → outlier_detection.py → imputation.py → aqi.py → output.csv + terminal
```

## Files

| File | Input | Output | What it does |
|---|---|---|---|
| `run.py` | `input.csv` (path given on the command line) | `output.csv` + terminal | Every 10 s, takes new rows plus 3 days of history, runs the three steps below, saves and prints the new rows. Runs until Ctrl+C |
| `outlier_detection.py` | Table, 15-min index, columns `PM2.5, PM10, CO, NO2, Temperature, Humidity` | Same table, outliers set to blank | `detect_outliers(frame)`. **Template**: range check only, to be replaced |
| `imputation.py` | Table from `detect_outliers` + model name | Same table, no blanks (real readings unchanged) | `impute(frame, model_name)`. Loads the model from `models/` and fills every blank |
| `aqi.py` | Filled table (uses `PM2.5, PM10, NO2, CO`) | Table with `si_pm25, si_pm10, si_no2, si_co, AQI, Category` | `compute_aqi(filled)`. CPCB NAQI: 24 h mean for PM2.5, PM10, NO2; 8 h mean for CO; AQI = highest sub-index |
| `imputation.ipynb` | CPCB CSVs `2022.csv`–`2025.csv` | `models/*.joblib`, `results/*.csv`, figures | Trains the 7 models on 2023–2024 and tests them on 2025 (16 gap patterns × 5 seeds). Not part of the live pipeline |
| `models/` | — | — | The 7 trained models |
| `results/`, `figs/`, `__results___files/` | — | — | Test results and figures from the notebook |
| `requirements.txt` | — | — | Package versions |

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

The tree sizes are capped (depth and leaf size): uncapped forests on about 70 000 training rows would need several GB, which no Pi can load.

In the PDF, M1 chooses the model per target on 2024. Here it uses fixed models: MLP for PM2.5 and PM10, tuned KNN for CO, Random Forest for NO2, temperature and humidity.

## How to run

1. Install Python 3.10–3.13.
2. Install the packages:
   ```
   pip install -r requirements.txt
   ```
3. Put the `.joblib` file of the model you want in `models/`, and set `MODEL` at the top of `run.py` (default `'mice'`).
4. Prepare `input.csv` with these columns:

   | Column | Unit |
   |---|---|
   | `Timestamp` | — |
   | `PM2.5`, `PM10`, `NO2` | µg/m³ |
   | `CO` | mg/m³ |
   | `T` (temperature) | °C |
   | `H` (humidity) | % |

   Blank cells are allowed. Other columns (e.g. `device_id`) are passed through. If your column names differ, edit `COLUMNS` in `run.py`.
5. Run:
   ```
   python run.py input.csv output.csv
   ```
   It first processes the rows already in `input.csv`, then checks for new rows every 10 seconds (`CHECK_EVERY`).
6. Press **Ctrl+C** to stop. Running it again continues after the last row in `output.csv`.

**`output.csv`:** the same columns and rows as `input.csv` (sensor gaps filled, outliers replaced) plus an `AQI` column. Each new row is also printed in the terminal.

## Notes

- `outlier_detection.py` is a placeholder. Replace it, but keep the function name `detect_outliers`.
- AQI is blank for the first ~16 hours of an input file. `aqi.py` follows two CPCB rules:
  - an average counts only with enough data: 16 h for the 24 h averages, 6 h for CO's 8 h average
  - AQI needs at least 3 pollutants, one of them PM2.5 or PM10

  After that every row gets an AQI, because `run.py` always passes the previous 3 days of data.
- AQI is not rounded (e.g. `61.59`).
- Keep `scikit-learn==1.6.1`. The models may not load with another version.
- If the features change in `imputation.ipynb`, update `make_features()` in `imputation.py` to match and retrain.
