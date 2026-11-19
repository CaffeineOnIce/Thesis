import numpy as np
import pandas as pd

from hampel.detectors import TraditionalHampel, RuleCheck
from config import settings as S


idx = pd.date_range(
    "2025-11-01",
    periods=400,
    freq="15min"
)

rng = np.random.default_rng(0)

base = pd.Series(
    60 + rng.normal(0, 4, 400),
    index=idx
)

print("Test 1: Spike detection")

s = base.copy()
s.iloc[200] = 300

cleaned, flags = TraditionalHampel().detect(s)

assert flags.iloc[200] == 1
assert cleaned.iloc[200] != 300

print("PASS: Artificial spike detected and replaced")


print("\nTest 2: Sustained level change")

s = base.copy()
s.iloc[250:274] = 150 + rng.normal(0, 4, 24)

_, step_flags = TraditionalHampel().detect(s)

step_count = int((step_flags.iloc[250:274] == 1).sum())

print("Consecutive outlier flags:", step_count)

assert step_count == S.MAX_CONSEC

print("PASS: Lock-in guard accepts sustained level change")


print("\nTest 3: Missing and warm-up observations")

s = base.copy()
s.iloc[100] = np.nan

input_flags = pd.Series(0, index=idx)
input_flags.iloc[101] = 4

_, output_flags = TraditionalHampel().detect(s, input_flags)

assert output_flags.iloc[100] == 2
assert output_flags.iloc[101] == 4

print("Missing flag:", output_flags.iloc[100])
print("Warm-up flag:", output_flags.iloc[101])

print("PASS: Missing and warm-up observations handled correctly")


print("\nTest 4: Batch versus streaming consistency")

s = base.copy()
s[rng.random(400) < 0.15] = np.nan
s.iloc[150] = 250

batch_cleaned, batch_flags = TraditionalHampel().detect(s)

detector = TraditionalHampel()

stream_results = [
    detector.step(x, ts)
    for ts, x in s.items()
]

stream_cleaned = [x[0] for x in stream_results]
stream_flags = [x[1] for x in stream_results]

same_cleaned = np.allclose(
    batch_cleaned.values,
    stream_cleaned,
    equal_nan=True
)

same_flags = list(batch_flags) == stream_flags

assert same_cleaned
assert same_flags

print("Batch and streaming cleaned values:", same_cleaned)
print("Batch and streaming flags:", same_flags)

print("PASS: Batch and streaming outputs are identical")


print("\nAll Traditional Hampel tests passed!")


print("\nTest 5: RuleCheck")

rule = RuleCheck("pm25")

results = [rule.step(50) for _ in range(5)]

assert results == [False, False, False, False, True]

range_rule = RuleCheck("pm25")

assert range_rule.step(1001) is True

print("Stuck sensor detection:", results)
print("Physical range detection: PASS")

print("\nAll tests completed successfully!")
