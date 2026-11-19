# Air-quality imputation and AQI

Fills missing values in 15-minute air-quality data and calculates the AQI for every row.

```
input CSV → outlier detection → imputation → AQI → output CSV
```

## Files

| Path | Purpose |
|---|---|
| `run.py` | Runs the whole process |
| `outlier_detection.py` | Turns outliers into blanks (**template**) |
| `imputation.py` | Fills blanks using a model from `models/` |
| `aqi.py` | Calculates AQI for every row (**template**) |
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
6. Open `output.csv`. It has one row per 15 minutes:
   - `PM2.5`, `PM10`, `CO`, `NO2`, `Temperature`, `Humidity` (gaps filled)
   - `Imputed` (which values were filled)
   - `AQI`, `Category`, `Dominant`

To change the model, set `MODEL` in `run.py` to `'mice'` (default), `'dynamic'` or `'stacking'`.

## Notes

- `outlier_detection.py` and `aqi.py` are placeholders. Replace them, but keep the function names `detect_outliers` and `compute_aqi`.
- Keep `scikit-learn==1.6.1`. The models may not load with another version.
