import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from hampel.detectors import ContextAwareHampel


profile = {
    "seasons": {
        "winter": [12, 1, 2],
        "pre_monsoon": [3, 4, 5],
        "monsoon": [6, 7, 8, 9],
        "post_monsoon": [10, 11]
    },
    "pollutants": {
        "pm25": {
            season: {
                "p5": 10,
                "p95": 200,
                "mad": 5
            }
            for season in [
                "winter",
                "pre_monsoon",
                "monsoon",
                "post_monsoon"
            ]
        }
    }
}

rng = np.random.default_rng(42)

idx = pd.date_range(
    "2025-11-01",
    periods=400,
    freq="15min"
)

series = pd.Series(
    60 + rng.normal(0, 4, 400),
    index=idx
)

series.iloc[200] = 300
series.iloc[100] = np.nan

input_flags = pd.Series(0, index=idx)
input_flags.iloc[101] = 4

with tempfile.TemporaryDirectory() as temp:
    profile_path = Path(temp) / "knowledge_base.json"

    profile_path.write_text(json.dumps(profile))

    for mode in ["raw", "cleaned"]:

        print(f"\nTesting ContextAwareHampel ({mode})")

        detector = ContextAwareHampel(
            "pm25",
            profile_path=profile_path,
            buffer_mode=mode
        )

        batch_cleaned, batch_flags = detector.detect(
            series,
            input_flags
        )

        assert batch_flags.iloc[200] == 1
        assert batch_flags.iloc[100] == 2
        assert batch_flags.iloc[101] == 4

        print("Spike detection: PASS")
        print("Missing flag: PASS")
        print("Warm-up flag: PASS")

        stream_detector = ContextAwareHampel(
            "pm25",
            profile_path=profile_path,
            buffer_mode=mode
        )

        stream_results = [
            stream_detector.step(
                value,
                ts,
                int(input_flags.iloc[i])
            )
            for i, (ts, value) in enumerate(series.items())
        ]

        stream_cleaned = [x[0] for x in stream_results]
        stream_flags = [x[1] for x in stream_results]

        assert np.allclose(
            batch_cleaned.values,
            stream_cleaned,
            equal_nan=True
        )

        assert list(batch_flags) == stream_flags

        print("Batch vs streaming: PASS")

print("\nAll ContextAwareHampel smoke tests passed!")
print("Note: Temporary synthetic profile only; not research validation.")
