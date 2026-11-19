# Hampel settings
# Original configuration supplied by Asif

# Sliding window sizes for 15-minute CPCB data
# 8=2h, 16=4h, 24=6h, 31=7.75h, 48=12h, 96=24h
WINDOW_SIZE = 12
WINDOW_SIZE_CANDIDATES = [8, 16, 24, 31, 48, 96]

# Numerical stability
EPSILON = 1e-9

# Traditional Hampel threshold
# Provisional value from the research guide
K_STATIC = 3.5

# Context-aware Hampel hyperparameters
K_LOOSE = 4.0
K_STRICT =3.0
K_VERY = 2.5
BETA = 0.5
SEASONAL_FLOOR_FACTOR = 0.6
TREND_THRESHOLD = 0.08
TREND_RELAXATION = 1.15

# Additional parameters from the research guide
# Provisional until confirmed or tuned
MAX_K = 4.5
MAX_CONSEC = 4
MIN_VALID_FRAC = 0.5
