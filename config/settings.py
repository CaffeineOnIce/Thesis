# Hampel settings — FROZEN on 2026-11-20 before the 2025 test (Phase 4).
# Source: docs/selection.md (pre-registered selection rule), tuned on 2024 with bands built from 2023 only
# (results/hampel_tuning_v2.csv, results/hampel_selection_rescore.csv). Original placeholders:
# config/settings_placeholder.py. Frozen record + hashes: results/frozen_settings.json.
# All windows are in 15-min steps (24 steps = 6 h).
#
# The scalar names below are the constructor defaults of hampel/detectors.py. H1 and H2 were tuned separately
# and use different windows, so the complete frozen configurations are H1_TUNED and H2_TUNED (pass them as
# keyword arguments); the optional switches stay OFF by default in the constructors.
WINDOW_SIZE = 12             # H2 tuned window (H1_TUNED uses 24)
EPSILON = 1e-6
K_STATIC = 4.0               # traditional Hampel (tuned; rule (e) of the selection, see docs/selection.md)
K_LOOSE = 8.0                # context-aware: median low in the seasonal band (tuned)
K_STRICT = 7.0               # context-aware: median high in the seasonal band (tuned)
K_VERY = 6.0                 # context-aware: value outside the seasonal p5-p95 band (tuned)
BETA = 0.5
SEASONAL_FLOOR_FACTOR = 0.5
TREND_THRESHOLD = 0.3
TREND_RELAXATION = 1.5
MAX_K = 9.0                  # = K_LOOSE + 1 (tuned with the triplet)
MAX_CONSEC = 4               # lock-in guard: accept a new level after this many consecutive flags
MIN_VALID_FRAC = 0.5         # need at least half the window observed to test a value

H2_PROFILE_PATH = "data/seasonal_bands/knowledge_base_2023_2024.json"   # final bands (2023 + 2024)

H1_TUNED = dict(window_size=24, k_static=4.0, window_by_observed=True)
H2_TUNED = dict(profile_path=H2_PROFILE_PATH, window_size=12, k_loose=8.0, k_strict=7.0, k_very=6.0, max_k=9.0,
                buffer_mode="cleaned", trend_outside_band=True)
# Reference only, NOT pre-registered (docs/phase3_checks.md §2): H1 with a looser K that passes rule (a).
H1_LOOSE_REFERENCE = dict(window_size=24, k_static=10.0, window_by_observed=True)
