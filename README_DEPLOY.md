# PolluSense Edge — deployment package (Raspberry Pi + VM)

Built 20 Nov 2026 from the starter pipeline plus the frozen Hampel module (v1.0-hampel).

## 1. The final pipeline

```
ESP32 (firmware/pollusense_v1)  — PMS7003, MQ135, MQ7, DHT11; 1-min JSON, raw mV for the MQ sensors
   │  MQTT (local Wi-Fi)  topic pollusense/<id>/raw
   ▼
Raspberry Pi
   edge/ingest.py      store every 1-min message in data.db                       (always running)
   edge/aggregate.py   calibrate MQ (R0, T/RH), 15-min median per variable,        (systemd timer :01 :16 :31 :46)
                       flag 2 = missing, 4 = MQ warm-up; publish pollusense/<id>/rec15
   ├─ EDGE mode   pipeline/run_edge.py     rec15 → core.process → clean record → VM (queued in SQLite if offline)
   └─ CLOUD mode  pipeline/forward_raw.py  rec15 unchanged → VM (queued in SQLite if offline)
VM
   pipeline/run_cloud.py   raw rec15 → core.process → log           (cloud mode)
                           receives the clean records from the Pi   (edge mode)

core.process (identical code on Pi and VM), per 15-min record:
   1 rule check   range; stuck = same value 4 times (CO: 8)                       → flag 1
   2 Hampel H2    frozen: W 12, k 8/7/6, MAX_K 9, cleaned buffer, trend protection
                  also outside the band, bands 2023+2024 (or knowledge_base_live.json) → flag 1
   3 impute       every missing / flagged value with the trained model (M3-L)      → flag 3
   4 AQI          CPCB-style, 24-h running averages on observed + imputed values
```

Run edge and cloud mode at the same time: both subscribe to the same rec15 stream, so the edge-vs-cloud comparison
uses exactly the same records.

## 2. Files on each machine

| Machine | Files |
|---|---|
| ESP32 | `firmware/pollusense_v1/pollusense_v1.ino` (flash from the laptop with Arduino IDE) |
| Raspberry Pi | this whole folder at `/home/pi/pollusense` (paths in `edge/*.py` assume it) + `models/M3-L.joblib` + `pipeline_config.json` + `calibration.json` (R0 values from `edge/r0.py`) |
| VM | the same folder (only `pipeline/`, `hampel/`, `config/`, `impute/`, `data/seasonal_bands/`, `models/` are used) + `pipeline_config.json` |

What is in the folder and why:

| Path | Used for |
|---|---|
| `edge/` | ingest, calibration, R0, 15-min aggregation (Pi only) |
| `pipeline/core.py` | the 4-step processing above (Pi and VM) — **patched**: builds the detectors through `live_detectors.py` |
| `pipeline/live_detectors.py`, `config/settings.py`, `config/settings_live.py` | frozen H2 values + live rule settings |
| `hampel/detectors.py` | H1 / H2 / rule check, v1.0 (identical to the paper's code) |
| `data/seasonal_bands/knowledge_base_2023_2024.json` | frozen bands |
| `impute/` | imputation models + AQI |
| `pipeline/uplink.py`, `run_edge.py`, `forward_raw.py`, `run_cloud.py` | MQTT services with offline queue |
| `tools/verify_hampel_identical.py`, `results/frozen_settings.json`, `results/hampel_identity_laptop.csv`, `tests/fixtures/` | Pi identity check |
| `bench/bench_detectors.py` | Pi cost per detector step (paper Table T6) |
| `tools/pipeline_replay_check.py` | whole pipeline replayed on 2 months of 2024 data; flags must equal the frozen H2 |
| `tools/site_adapt_bands.py` | writes `knowledge_base_live.json` after the first days of live data |

Not on the Pi: CPCB raw data, masks, tuning/experiment scripts, reports.

## 3. Install (Pi and VM)

1. Use the **same Python minor version and the same package versions** as the laptop that trains the models
   (`requirements.txt`; TODO A1: Python 3.15 on the laptop may have no scikit-learn wheels — use 3.11/3.12/3.13 on all
   three machines).
2. ```
   cd /home/pi/pollusense
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp pipeline_config.example.json pipeline_config.json      # fill in passwords, VM host, CA path
   ```
3. Copy `models/M3-L.joblib` from Samanway (trained with the same scikit-learn version).

## 4. Checks before the live run (in this order, from the folder root)

| Check | Command | Pass |
|---|---|---|
| Hampel identical to laptop | `python -m tools.verify_hampel_identical --label pi` then `python -m tools.verify_hampel_identical --compare results/hampel_identity_laptop.csv results/hampel_identity_pi.csv` | `PASS: flag mismatches 0` |
| Whole pipeline = frozen H2 | `python -m tools.pipeline_replay_check --model M3-L --n 960` | `PASS`; note per-record ms |
| Detector cost (paper) | `python -m bench.bench_detectors --label pi` | writes `results/E3_detector_cost_pi.csv` — copy it to the laptop repo |
| Model loads + identical predictions | Samanway's `verify_identical.py` on laptop, Pi, VM | identical |

## 5. Start the services (Pi)

Order: Mosquitto broker → `edge/ingest.py` → timer for `edge/aggregate.py` → `python -m pipeline.run_edge` and
`python -m pipeline.forward_raw` (from the folder root). VM: `python -m pipeline.run_cloud`.
`edge/*.py` import `calibrate` directly, so run them with working directory `/home/pi/pollusense/edge`.

## 6. After the first days of live data

Compare live medians with the CPCB bands and, if a pollutant is off by more than 2×, write live bands:
`python -m tools.site_adapt_bands --live-median no2=<x> pm25=<y> ... --season post_monsoon`.
The pipeline picks up `data/seasonal_bands/knowledge_base_live.json` on restart. Record the date and ratios in the
paper (the NO2 analysis shows why this is needed).

## 7. Tested here (20 Nov 2026, Linux x86, Python 3.13)

- Hampel identity vs laptop file: PASS (0 mismatches, max diff 0).
- Replay of 5,856 records through `core.process` with an M0 imputer: pipeline flags = frozen H2 for all four
  pollutants (0 mismatches); ~36 ms per record (mostly imputation/pandas), Hampel ~0.2 ms.
- Not tested: MQTT services, firmware, aggregation on real sensor data, the M3-L model (not available).
