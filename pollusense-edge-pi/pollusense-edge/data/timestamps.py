"""Timestamp convention (A2).

CPCB exports and every file written by this repository (parquet, masks, results) use naive local time (IST) and
label each 15-min value by the START of its window: row 00:00 = 00:00-00:15. Evidence: each yearly raw file runs
00:00 -> 23:45 and its 23:45 row (the window ending at midnight) is empty in 2023, 2024 and 2025
(docs/handoff_samanway.md). Live PolluSense records are labelled by the window END. Nothing is shifted
silently: convert explicitly with these helpers when joining the two.
"""
import pandas as pd

WINDOW = pd.Timedelta("15min")


def to_window_end(obj):
    """Relabel a start-labelled (CPCB / this repo) Series or DataFrame to window-end labels (live convention)."""
    out = obj.copy(); out.index = out.index + WINDOW
    return out


def to_window_start(obj):
    """Relabel an end-labelled (live) Series or DataFrame to window-start labels (CPCB / this repo)."""
    out = obj.copy(); out.index = out.index - WINDOW
    return out
