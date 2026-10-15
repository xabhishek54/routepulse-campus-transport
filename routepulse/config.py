"""
Central configuration for RoutePulse.

All constants that appear in more than one place live here.
Any change to physical parameters only needs to happen in this file.

Metric definitions (single source of truth):
  - overcrowding_event: a stop where on_board_after >= capacity (at or over)
  - crowding_event:     a stop where unmet_demand > 0 (passengers couldn't board)
  - unmet_demand:       total passengers who arrived at a stop and could not board
  - eta_mae:            mean |estimated_arrival - actual_arrival| over future stops (min)
  - eta_calibration:    fraction of estimates where actual fell within stated CI (target = CI/100)
  - average_wait:       HEADWAY/2 + mean positive delay (proxy; exact needs per-passenger model)
  - fleet_utilisation:  mean(on_board / capacity) across all stop-events (0–1)
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
SMALL_BUS_CAPACITY: int = 30         # minibus seats (naive baseline)
LARGE_BUS_CAPACITY: int = 60         # full bus seats
CAMPUS_BUS_SPEED_KMH: float = 15.0  # nominal campus bus speed

# ── Simulator parameters ───────────────────────────────────────────────────────
TRAVEL_NOISE_SIGMA: float  = 1.5    # Gaussian std dev added per segment (minutes)
                                     # Calibrated to produce realistic ~2-4 min delays
ALIGHTING_FRACTION: float  = 0.40   # fraction of on-board who alight at each non-first stop
DWELL_TIME_MINUTES: float  = 0.75   # per-stop dwell added to travel time (45 seconds)
MIN_TURNAROUND_MINUTES: float = 5.0  # minimum time between end of one trip and start of next

# ── Demand model ───────────────────────────────────────────────────────────────
BASE_OFF_PEAK_MULT: float  = 0.15   # demand multiplier outside peak windows (low base)
PEAK_SIGMA_HOURS: float    = 0.20   # width (std dev in hours) of class-changeover peaks
                                     # 0.20h = 12 min FWHM — sharp class-change spikes
SMARTER_BASELINE_THRESHOLD: float = 0.80  # load fraction triggering route-level upgrade

# ── Kalman filter (estimator) ─────────────────────────────────────────────────
KALMAN_INITIAL_UNCERTAINTY: float  = 3.0   # initial delay uncertainty (minutes std dev)
KALMAN_PROCESS_NOISE: float        = 1.2   # delay uncertainty grows by this std per stop
                                            # Calibrated: TRAVEL_NOISE_SIGMA=1.5, so per-stop
                                            # accumulated uncertainty ~ 1.2 min std is reasonable
KALMAN_OBS_NOISE: float            = 1.0   # GPS/AVL timing measurement noise (minutes std dev)
ETA_CI_PCT: float                  = 90.0  # stated confidence interval coverage (%)
                                            # Calibration target: ~90% of actuals inside CI

# ── Detector thresholds ────────────────────────────────────────────────────────
MIN_HEADWAY: float            = 5.0   # minimum acceptable gap between same-route departures (min)
MAX_WAIT_FOR_CONNECTION: float = 10.0 # extra wait > this at a transfer = missed connection (min)

# ── Optimizer thresholds ───────────────────────────────────────────────────────
OVERCROWD_THRESHOLD: float    = 0.85  # mean load/capacity trigger for vehicle swap
                                       # (lower than before: fires more readily on stressed campus)
UNMET_DEMAND_THRESHOLD: int   = 5     # unmet passengers/trip trigger for action
NUDGE_MINUTES: float          = 5.0   # departure shift applied to fix missed connections
MAX_SWAPS: int                = 12    # maximum vehicle swaps per recommendation
MAX_EXTRA_TRIPS: int          = 6     # maximum extra departures inserted

# ── Evaluator ─────────────────────────────────────────────────────────────────
AVG_WAIT_BASE: float = HEADWAY / 2.0  # half-headway baseline wait (minutes)

# ETA calibration target: if CI is 90%, we expect 90% of actuals inside.
# We report actual calibration and flag it if it deviates by more than ±10pp.
ETA_CALIBRATION_TARGET: float = ETA_CI_PCT / 100.0
ETA_CALIBRATION_TOLERANCE: float = 0.10  # acceptable deviation from target

# ── Demand forecasting (ML) ───────────────────────────────────────────────────
FORECAST_HORIZON_STEPS: int   = 4     # how many 15-min slots ahead to forecast
FORECAST_N_LAGS: int          = 8     # number of lag features for the forecaster
FORECAST_MIN_TRAIN_SAMPLES: int = 20  # minimum samples before forecaster is used

# ── Disruption scenarios (config-driven, not hardcoded in scenarios.py) ───────
# Sports event at Sports Complex
SPORTS_DEMAND_SPIKE: float = 5.0      # 5x demand at Sports Complex
SPORTS_START_HOUR: float   = 15.0     # 15:00 starts
SPORTS_END_HOUR: float     = 16.5     # 16:30 ends (post-match rush)
SPORTS_AFFECTED_STOP: str  = "S08"    # Sports Complex stop ID

# Morning traffic disruption (delays all peak departures)
TRAFFIC_EXTRA_DELAY: float     = 8.0   # extra minutes per segment (significant)
TRAFFIC_WINDOW_HOURS: tuple    = (8.0, 10.5)  # morning congestion window
TRAFFIC_AFFECTED_ROUTES: tuple = ("R1", "R2", "R3", "R4")  # all routes affected

# Vehicle breakdown scenario
BREAKDOWN_ROUTE: str       = "R1"     # which route loses vehicles
BREAKDOWN_N_VEHICLES: int  = 3        # how many consecutive departures are cancelled
BREAKDOWN_START_HOUR: float = 9.0     # when breakdown starts
