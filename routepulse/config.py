"""
Central configuration for RoutePulse.

All constants that appear in more than one place live here.
Any change to physical parameters only needs to happen in this file.
"""

# ── Simulation ─────────────────────────────────────────────────────────────────
SEED: int = 42
"""Default random seed. Evaluation uses seeds SEED..SEED+N_EVAL_SEEDS-1."""

N_EVAL_SEEDS: int = 11
"""Number of seeds used in multi-seed evaluation (42–52)."""

EVAL_SEEDS: list[int] = list(range(SEED, SEED + N_EVAL_SEEDS))

# ── Operating window ───────────────────────────────────────────────────────────
OP_START_HOUR: float = 8.0          # 08:00
OP_END_HOUR: float   = 20.0         # 20:00
OP_START: int  = int(OP_START_HOUR * 60)   # minutes since midnight
OP_END:   int  = int(OP_END_HOUR   * 60)
HEADWAY:  int  = 15                  # minutes between departures per route

# ── Vehicle types ──────────────────────────────────────────────────────────────
SMALL_BUS_CAPACITY: int = 25
LARGE_BUS_CAPACITY: int = 40
CAMPUS_BUS_SPEED_KMH: float = 15.0  # nominal campus bus speed

# ── Simulator parameters ───────────────────────────────────────────────────────
TRAVEL_NOISE_SIGMA: float  = 0.8    # Gaussian std dev added per segment (minutes)
ALIGHTING_FRACTION: float  = 0.35   # fraction of on-board who alight at each non-first stop
DWELL_TIME_MINUTES: float  = 0.5    # per-stop dwell added to travel time

# ── Demand model ───────────────────────────────────────────────────────────────
BASE_OFF_PEAK_MULT: float  = 0.3    # demand multiplier outside peak windows
PEAK_SIGMA_HOURS: float    = 0.25   # width (std dev in hours) of class-changeover peaks
SMARTER_BASELINE_THRESHOLD: float = 0.80  # load fraction above which smarter baseline swaps up

# ── Kalman filter (estimator) ─────────────────────────────────────────────────
KALMAN_INITIAL_UNCERTAINTY: float  = 2.0   # initial delay uncertainty (minutes)
KALMAN_PROCESS_NOISE: float        = 0.25  # delay grows by this std per stop (minutes)
KALMAN_OBS_NOISE: float            = 0.30  # GPS/timing measurement noise (minutes)
ETA_CI_PCT: float                  = 90.0  # default confidence interval coverage (%)

# ── Detector thresholds ────────────────────────────────────────────────────────
MIN_HEADWAY: float            = 5.0   # minimum acceptable gap between same-route departures (min)
MAX_WAIT_FOR_CONNECTION: float = 15.0 # passengers waiting > this at a transfer = missed connection

# ── Optimizer thresholds ───────────────────────────────────────────────────────
OVERCROWD_THRESHOLD: float    = 0.92  # mean load/capacity trigger for vehicle swap
UNMET_DEMAND_THRESHOLD: int   = 8     # unmet passengers/trip trigger for action
NUDGE_MINUTES: float          = 5.0   # departure shift applied to fix missed connections
MAX_SWAPS: int                = 10    # maximum vehicle swaps per recommendation
MAX_EXTRA_TRIPS: int          = 5     # maximum extra departures inserted

# ── Evaluator ─────────────────────────────────────────────────────────────────
AVG_WAIT_BASE: float = HEADWAY / 2.0  # half-headway baseline wait (minutes)

# ── Demand forecasting (ML) ───────────────────────────────────────────────────
FORECAST_HORIZON_STEPS: int   = 4     # how many 15-min slots ahead to forecast
FORECAST_N_LAGS: int          = 8     # number of lag features for the forecaster
FORECAST_MIN_TRAIN_SAMPLES: int = 20  # minimum samples before forecaster is used

# ── Disruption scenarios ───────────────────────────────────────────────────────
SPORTS_DEMAND_SPIKE: float = 3.0      # demand multiplier at Sports Centre during event
SPORTS_START_HOUR: float   = 14.0
SPORTS_END_HOUR: float     = 15.0
TRAFFIC_EXTRA_DELAY: float = 4.0      # extra minutes per segment during traffic disruption
TRAFFIC_WINDOW_HOURS: tuple = (8.0, 10.0)  # hours affected by morning traffic
