# PolluSense CPCB data import bundle

This bundle contains the three CSV files uploaded for PolluSense:

- `data/raw/2023.csv`
- `data/raw/2024.csv`
- `data/raw/2025.csv`

`prepare_cpcb_data.py` converts them into the two file names expected by the research guide:

- `data/cpcb_15min_clean.parquet`
- `data/observed_mask.parquet`

## Run it on the PolluSense project

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


