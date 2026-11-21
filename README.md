# PolluSense Edge: outlier detection → imputation → AQI

The edge pipeline runs from **`run.py`** in the repo root. It replaces `pipeline/core.py` and `pipeline/run_edge.py`.

## Run

```
cd ~/pollusense
.venv/bin/python run.py edge/records_15min.csv output/edge_output.csv
```

Stop with **Ctrl+C**. Ctrl+Z only pauses it.

## Flow

```
edge/records_15min.csv (from edge/aggregate.py)
  → run.py
      → pipeline/live_detectors.py → hampel/detectors.py   outlier detection
      → impute/impute.py + impute/models/*.joblib           imputation
      → impute/aqi.py                                       AQI
  → output/edge_output.csv + terminal
```

`run.py` checks the input every 10 s and processes only new rows.

## Files used

| File | Role |
|---|---|
| `run.py` | Reads the input, runs every step, writes the output and prints it |
| `pipeline/live_detectors.py` | Builds the rule-check and Hampel detectors |
| `hampel/detectors.py` | Outlier detection code (rule check + Hampel) |
| `config/settings.py`, `config/settings_live.py` | Detector settings |
| `data/seasonal_bands/knowledge_base_2023_2024.json` | Seasonal bands for Hampel |
| `data/timestamps.py` | Window-end ↔ window-start conversion |
| `impute/impute.py` | Loads the models and fills gaps |
| `impute/models/*.joblib` | The 7 trained imputation models |
| `impute/aqi.py` | CPCB AQI |

## Not used by the edge pipeline

| File | Why |
|---|---|
| `pipeline/core.py` | Loads models with `impute.models.Base.load`, which can't read the trained joblib models |
| `pipeline/run_edge.py` | Built on `core.py`; replaced by `run.py` |
| `pipeline/run_cloud.py`, `pipeline/forward_raw.py`, `pipeline/uplink.py` | Cloud / MQTT only |

## Output

`output/edge_output.csv` has the input's columns with cleaned and filled values, plus:

- `AQI`: whole number, blank for about the first 16 h, until there is enough data.
- `flag_<column>`: 0 ok, 1 outlier (removed and filled), 2 missing (filled).

## Change the imputation model

In `run.py`, set `MODEL` to `'m0'`, `'dynamic'`, `'mice'`, `'stacking'`, `'mice_light'`, `'stacking_light'` or `'hgb_native'`, then restart. Only rows added after the restart use the new model.
