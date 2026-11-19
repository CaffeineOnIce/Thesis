# PolluSense CPCB data import bundle

This bundle contains the three CSV files uploaded for PolluSense:

- `data/raw/2023.csv`
- `data/raw/2024.csv`
- `data/raw/2025.csv`

`prepare_cpcb_data.py` converts them into the two file names expected by the research guide:

- `data/cpcb_15min_clean.parquet`
- `data/observed_mask.parquet`

## Run on the Mac in the PolluSense project

1. Extract this bundle into the root of `~/pollusense-project`, merging its `data/raw/` folder with the project.
2. Activate the existing environment:

   ```bash
   source ~/venv-ps/bin/activate
   cd ~/pollusense-project
   ```

3. Install a Parquet engine into this environment:

   ```bash
   python -m pip install pyarrow
   ```

4. Run:

   ```bash
   python prepare_cpcb_data.py
   ```

## Data handling

The script selects the six variables expected by the guide and renames them to `pm25`, `pm10`, `no2`, `co`, `temp`, and `rh`. It parses `Timestamp` as a timezone-naive DatetimeIndex, checks each year against a complete 15-minute grid, checks duplicates and ordering, and concatenates 2023-2025.

It does **not** fill, interpolate, resample, clip, or remove measurements. The observed mask is `True` exactly where the corresponding source measurement is non-null. This preserves original missingness for later gap simulation.

The guide's core experiments use 2024 for tuning and 2025 for evaluation. 2023 is retained in the combined file as an additional historical year; the existing scripts select 2024 or 2025 by year.

## Confirm before research reporting

The CSV contents contain no station identifier or station metadata column. Confirm and record the CPCB station/location and data provenance separately. Also confirm that the timezone-naive timestamps are IST and represent the 15-minute window-end convention required by the research guide. The script does not infer either fact from the timestamp strings.
