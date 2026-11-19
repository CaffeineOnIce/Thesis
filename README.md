# PolluSense: Context-Aware Outlier Detection for Air Quality Sensor Data

**Research Project | WoWMoM 2027**

PolluSense focuses on reliable air-quality sensor data processing through outlier detection, missing-data simulation, and imputation. The project investigates how traditional and context-aware Hampel filtering methods can identify abnormal sensor readings while avoiding unnecessary removal of genuine pollution events.

The research uses CPCB air-quality data and evaluates different detection and filtering–imputation strategies on time-series measurements.

---

## 1. Project Objectives

The main objectives of this work are:

- Detect abnormal air-quality sensor measurements.
- Compare Traditional Hampel and Context-Aware Hampel detection.
- Simulate artificial outliers and missing data for controlled experiments.
- Evaluate the effect of filtering and imputation order.
- Investigate false-positive behaviour during real high-pollution periods.
- Develop a common processing pipeline intended for edge and cloud execution.

## 2. Dataset Description

The experiments use CPCB air-quality measurements covering three years.

| Attribute | Description |
|---|---|
| Data source | CPCB air-quality CSV datasets |
| Period | January 2023 – December 2025 |
| Total records | 105,216 |
| Sampling interval | 15 minutes |
| Number of variables | 6 |
| Tuning year | 2024 |
| Evaluation year | 2025 |

### Variables

| Variable | Description |
|---|---|
| `pm25` | PM2.5 concentration |
| `pm10` | PM10 concentration |
| `no2` | Nitrogen dioxide |
| `co` | Carbon monoxide |
| `temp` | Temperature |
| `rh` | Relative humidity |

The dataset preparation script generates:

- `data/cpcb_15min_clean.parquet`
- `data/observed_mask.parquet`

The observed mask preserves the original missing-value locations for subsequent experiments.

**Note:** Raw CSV files and generated Parquet files are not included in this GitHub repository. They must be supplied locally before running the experiments.

## 3. Methodology and Implemented Modules

### 3.1 Outlier Detection

Two Hampel-based approaches are implemented:

**Traditional Hampel (H1)**
- Uses a rolling median and Median Absolute Deviation (MAD).
- Detects abnormal measurements using a statistical threshold.

**Context-Aware Hampel (H2)**
- Incorporates pollutant-specific seasonal context.
- Uses configurable detection thresholds.
- Supports raw and cleaned buffer modes.

Additional RuleCheck logic is evaluated alongside the detectors.

### 3.2 Missing-Data and Outlier Simulation

The simulation modules generate controlled experimental conditions.

- Artificial outlier injection.
- Configurable missing-data simulation.
- Reproducible experiments using random seeds.
- Observation masks to distinguish original missing values from simulated gaps.

### 3.3 Threshold Tuning

Hampel detector thresholds are tuned using the 2024 dataset.

The tuning process compares different window sizes and threshold configurations using injected spikes and bursts.

### 3.4 Imputation Integration

The project integrates the M3-L Stacking Ensemble imputation model for the E2 experiments.

The model is used to investigate how missing-value imputation interacts with outlier detection.

The trained model files are external dependencies and are not included in this repository.

## 4. Experimental Evaluation

### E2 – Outlier Detection Evaluation

The detection experiment uses the 2025 dataset and five random seeds.

It compares:

- H1 – Traditional Hampel.
- H2-raw – Context-Aware Hampel using raw measurements.
- H2-cleaned – Context-Aware Hampel using cleaned measurements.
- Each detector with and without RuleCheck.

Evaluation metrics:

- Precision
- Recall
- F1-score
- False-positive rate

### E2 – Real High-Pollution-Day Evaluation

This experiment evaluates detector behaviour on real high-pollution days without injecting artificial outliers.

It compares flag rates during the most polluted days against other days to investigate whether genuine pollution events are being incorrectly flagged.

### E2 – Filtering and Imputation Ablation

Three processing strategies are compared:

1. **Hampel → Imputation:** Detect outliers first, replace flagged measurements with missing values, then impute.
2. **Imputation → Hampel:** Impute missing values first, then apply Hampel detection.
3. **Hampel Median Fill:** Use Hampel's median-based cleaned output and impute only the remaining gaps.

The experiment introduces 10% random missing gaps on top of injected outliers and measures Mean Absolute Error (MAE) on corrupted points and gap points.

## 5. Experimental Results

### 5.1 Traditional vs Context-Aware Hampel

Mean results across five random seeds on the 2025 evaluation dataset:

| Detector | Precision | Recall | F1-score | FPR |
|---|---:|---:|---:|---:|
| H1 – Traditional | 0.0914 | 0.3425 | 0.1367 | 0.1379 |
| H1 + RuleCheck | 0.1610 | 0.6953 | 0.2506 | 0.1397 |
| H2 – Raw | 0.5397 | 0.3237 | 0.3894 | 0.0185 |
| H2 – Raw + RuleCheck | 0.6348 | 0.6756 | 0.6443 | 0.0203 |
| H2 – Cleaned | 0.4649 | 0.3282 | 0.3660 | 0.0276 |
| H2 – Cleaned + RuleCheck | 0.5744 | 0.6802 | 0.6080 | 0.0295 |

**Observation:** H2 Raw + RuleCheck achieved the highest F1-score (0.6443) and precision (0.6348). H2 Cleaned + RuleCheck achieved the highest recall (0.6802).

These results indicate improved detection performance for the context-aware approach in this evaluation.

### 5.2 Real High-Pollution-Day Evaluation

The high-pollution-day analysis identified 19 high-pollution days using the 95th percentile of daily PM2.5 measurements.

| Detector | Flag rate on high-pollution days | Flag rate on other days |
|---|---:|---:|
| H1 | 0.1930 | 0.1863 |
| H2 – Raw | 0.0209 | 0.0043 |
| H2 – Cleaned | 0.0344 | 0.0060 |

The results provide a comparison of detector flag rates during real high-pollution periods and other days.

### 5.3 Filtering and Imputation Ablation Results

Mean MAE across five random seeds:

| Strategy | Outlier-point MAE | Gap-point MAE |
|---|---:|---:|
| Hampel Median Fill | 11.0360 | 3.7339 |
| Hampel → Imputation | 9.9287 | 3.4470 |
| Imputation → Hampel | 9.6758 | 3.8465 |

**Observation:**
- Imputation → Hampel achieved the lowest average MAE on corrupted outlier points.
- Hampel → Imputation achieved the lowest average MAE on simulated gap points.

These are descriptive comparisons; statistical significance has not been established.

## 6. Repository Structure

```text
pollusense-project/
│
├── bench/
│   ├── __init__.py
│   ├── evaluate_2025.py
│   ├── evaluate_2025_highdays.py
│   └── evaluate_2025_ablation.py
│
├── config/
│   ├── __init__.py
│   └── settings.py
│
├── data/
│   └── seasonal_bands/
│       └── knowledge_base.json
│
├── external_imputation/
│   ├── imputation.py
│   └── imputation.ipynb
│
├── hampel/
│   ├── __init__.py
│   └── detectors.py
│
├── pipeline/
│   └── __init__.py
│
├── results/
│   ├── hampel_tuning.csv
│   ├── context_hampel_tuning.csv
│   ├── E2_detection.csv
│   ├── E2_highdays.csv
│   ├── E2_ablation.csv
│   ├── E2_ablation_overall_statistics.csv
│   └── E2_ablation_pollutant_statistics.csv
│
├── sim/
│   ├── __init__.py
│   ├── gaps.py
│   └── outliers.py
│
├── tests/
│   ├── __init__.py
│   ├── test_hampel.py
│   ├── test_context_hampel.py
│   └── test_gaps.py
│
├── prepare_cpcb_data.py
├── tune_hampel.py
├── tune_context_hampel.py
├── requirements.txt
├── DATASET_README.md
└── README.md
```

## 7. Installation and Setup

### Prerequisites

- Python 3.11
- Git
- pip
- CPCB source CSV files
- M3-L Stacking Ensemble model files for the imputation experiments

### Step 1: Clone the repository

```bash
git clone -b Subham https://github.com/CaffeineOnIce/Thesis.git
cd Thesis
```

### Step 2: Create a virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### Step 3: Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyarrow
```

### Step 4: Prepare the dataset

Place the source CSV files in:

```text
data/raw/
├── 2023.csv
├── 2024.csv
└── 2025.csv
```

Run:

```bash
python prepare_cpcb_data.py
```

This generates the cleaned Parquet dataset and observed-value mask.

For additional dataset preparation details, see `DATASET_README.md`.

### Step 5: Configure the imputation model

Obtain the M3-L Stacking Ensemble model files from the relevant research collaborator and place them in the location expected by `external_imputation/imputation.py`.

The model files are not distributed in this repository.

## 8. Running the Project

Run commands from the repository root.

### Run the tests

```bash
python -m tests.test_hampel
python -m tests.test_context_hampel
python -m tests.test_gaps
```

### Run Hampel threshold tuning

```bash
python -m tune_hampel
python -m tune_context_hampel
```

### Run E2 detection evaluation

```bash
python -m bench.evaluate_2025
```

### Run real high-pollution-day evaluation

```bash
python -m bench.evaluate_2025_highdays
```

### Run filtering and imputation ablation

```bash
python -m bench.evaluate_2025_ablation
```

The E2 scripts require the prepared Parquet files. The ablation experiment additionally requires the configured M3-L imputation model.

Generated experiment results are saved in the `results/` directory.

## 9. Technologies Used

| Technology | Purpose |
|---|---|
| Python | Main implementation |
| Pandas | Time-series data processing |
| NumPy | Numerical computation |
| Scikit-learn | Machine learning and evaluation utilities |
| PyArrow | Parquet data storage |
| Joblib | Loading serialized imputation models |
| Matplotlib | Data visualization |
| Git and GitHub | Version control and collaboration |

## 10. Current Development Status

### Completed

- Traditional Hampel detector implementation.
- Context-Aware Hampel detector implementation.
- Gap simulation and outlier injection.
- Detector unit and smoke tests.
- CPCB dataset preparation.
- Hampel threshold tuning.
- E2 detection evaluation.
- E2 real high-pollution-day evaluation.
- E2 filtering and imputation ablation.
- Statistical summaries across five random seeds.

### Remaining

- Complete the edge/cloud processing pipeline.
- Implement and validate the replay harness.
- Complete E3 replay experiments on the Raspberry Pi and cloud VM.
- Complete E4 experiments according to the research guide.
- Final result analysis, figures, and research documentation.

## 11. Research and Contributions

This repository contains the implementation and experimental work for the PolluSense outlier-detection contribution.

**Primary contribution areas:**
- Statistical and context-aware sensor outlier detection.
- Missing-data and outlier simulation.
- CPCB time-series dataset preparation.
- Comparative evaluation of detection strategies.
- Analysis of filtering and imputation order.



**Repository:** https://github.com/CaffeineOnIce/Thesis/tree/Subham

---

*This repository is under active research development. Experimental results and implementation details may be updated as the remaining experiments are completed.*
