# RoutePulse

A campus transport intelligence system built for Westbrook University (fictional).
Given a fixed route network and a stochastic demand model, RoutePulse simulates
daily operations, estimates vehicle arrival times, detects schedule problems, and
produces validated schedule recommendations.

---

## Problem statement

Campus bus networks run fixed schedules set weeks in advance. Demand varies sharply
by time of day (class changeovers, lunch, evening exodus), and a single vehicle
breakdown or traffic jam cascades into missed connections and stranded passengers.
Operators have no real-time view of which trips are overcrowded, no arrival window
for passengers, and no systematic way to decide when an extra bus is worth deploying.

RoutePulse addresses each of these gaps with a software stack that runs entirely
offline on synthetic data, producing reproducible, verifiable results.

---

## Architecture

```
routepulse/
├── config.py        Central constants: capacities, thresholds, window, seeds
├── models.py        Core dataclasses: Stop, Route, Vehicle, Plan, StopEvent, ...
├── data_gen.py      Synthetic campus + demand model + baseline plans
├── simulator.py     Discrete-event bus simulator (Poisson demand, Gaussian travel noise)
├── estimator.py     Kalman-filter ETA estimator with CI calibration
├── detector.py      Crowding, schedule-conflict and missed-connection detectors
├── validator.py     Independent hard-constraint checker (7 schedule checks, 3 sim checks)
├── optimizer.py     Greedy schedule optimiser (upgrade → extra trip → time shift)
├── evaluator.py     Multi-seed metrics with mean ± std, honest comparison table
├── forecaster.py    Gradient Boosting demand forecaster with holdout evaluation
└── scenarios.py     Named disruption scenarios: traffic, breakdown, sports event
app/
├── main.py          Landing dashboard (network snapshot, guided navigation)
└── pages/
    ├── 01_Where_Is_the_Network_Under_Stress.py
    ├── 02_When_Will_My_Bus_Arrive.py
    ├── 03_Whats_Going_Wrong.py
    ├── 04_Demand_Forecast.py
    ├── 05_How_Should_We_Fix_It.py
    └── 06_Disruption_Planner.py
eval/
└── run_evaluation.py   Reproduces all report numbers from scratch
tests/                  35 unit tests covering all core modules
```

### Data flow

```
data_gen.py
  └─ Stops, Routes, Vehicles, Departures, Plans
        │
        ▼
simulator.py  ←─ Disruption (optional)
  └─ List[SimulatedTrip]
        │
        ├─▶ estimator.py   → ETAEstimate (Kalman filter per trip)
        ├─▶ detector.py    → Violations, MissedConnections
        ├─▶ validator.py   → ValidationReport (independent of optimizer)
        └─▶ optimizer.py   → Plan (modified departures, validated before return)
                │
                ▼
         evaluator.py  → EvaluationResult (mean ± std over N seeds)
```

---

## Components

### Demand model

Demand at each stop follows a Poisson process with a time-varying rate:

```
rate(t) = base_demand_rate × multiplier(t)
passengers ~ Poisson(rate × headway_fraction)
```

`multiplier(t)` is a sum of Gaussian kernels centred on class-changeover times
(08:30, 09:00, 10:00, 12:00, 13:00, 14:00, 15:00, 16:00, 17:00, 18:00), with
σ = 0.20 hours (12-minute FWHM — sharp peaks matching how class changeovers work).
Peak multipliers range from 2.0× to 4.5×. Off-peak multiplier is 0.15×.

The `naive` baseline (all 30-seat minibuses) produces genuine crowding at peak:
~670 crowded stop-events and ~18,000 unmet passengers per simulation day (seed 42).

### ETA estimator

A 1D Kalman filter tracking delay (minutes) as it propagates along a route.

```
State:   x_k = delay at stop k
Model:   x_k = x_{k-1} + w_k,   w_k ~ N(0, Q)   Q = 1.44 min²/stop
Obs:     z_k = x_k + v_k,       v_k ~ N(0, R)   R = 1.00 min²
```

The 90% CI half-width at n stops ahead = z_{0.05} × √(P_filtered + n×Q).
Measured calibration across 11 seeds: ~94% (gap from 90% target: +4 pp — well calibrated).

Loop routes are handled via position-based lookup (`scheduled_arrival_at_position(i)`)
rather than stop-ID lookup, which would return the first occurrence's scheduled time
and produce a spurious ~+10 min phantom delay on the return leg.

### Validator

Checks are run by `validator.py`, which has no visibility of optimizer internals.
An optimiser-produced plan that fails any check reverts to the safe fallback.

| Check | Description |
|-------|-------------|
| C1 | All departures within 08:00–20:00 operating window |
| C2 | Minimum 5-min headway between same-route departures |
| C3 | No duplicate departure times on the same route |
| C4 | All routes have at least one departure |
| C5 | No vehicle assigned to two overlapping trips simultaneously |
| C6 | Minimum 5-min turnaround between consecutive trips for the same vehicle |
| C7 | All trips nominally complete within the operating window |
| C9–C11 | Simulation-level: non-negative on-board, non-decreasing arrivals, boarded ≤ demand |

### Optimizer

Three greedy passes applied in sequence, worst-first:

1. **Vehicle upgrade** — replace 30-seat minibus with 60-seat bus on trips where
   `mean_load > 0.85` or `unmet_demand > 5`. Benefit = `min(unmet_demand, 30)`.
   No fabricated percentages; cost expressed as extra vehicle-minutes.

2. **Extra trip** — insert a new departure at the midpoint of a gap ≥ 2× MIN_HEADWAY
   where upgrade alone is insufficient. Checks headway on both sides before inserting.

3. **Departure shift** — move a departure earlier by 5 min to reduce missed connections,
   only if the shift maintains minimum headway and vehicle turnaround.

Every resulting plan passes all 7 schedule constraint checks before being returned.

### Demand forecaster

`GradientBoostingRegressor` (scikit-learn) trained on simulated boarding counts.

**Features**: cyclic time encoding (sin/cos at day and headway periods), demand
multiplier, 8 lag boarding counts, stop ordinal encoding.

**Training/holdout split**: seeds 42–46 (train), seeds 47–52 (holdout).
Holdout MAE is reported as the primary quality metric — the training MAE alone
is not meaningful for judging forecast quality.

### Evaluation

All evaluation uses 11 deterministic seeds (42–52). The same seeds are used for
all three plans so comparisons are like-for-like.

```
python eval/run_evaluation.py
```

Produces a Markdown report with mean ± std for each metric, plus a 3-way table.

---

## Metric definitions

All metric names and definitions are documented in `routepulse/config.py`.

| Metric | Definition |
|--------|-----------|
| `service_rate` | `boarded / total_demand` across all stop-events |
| `crowding_event` | Stop-event where `unmet_demand > 0` |
| `overcrowding_event` | Stop-event where `on_board >= capacity` |
| `total_unmet_demand` | Sum of `max(0, demand - boarded)` across all stops |
| `average_wait` | `HEADWAY/2 + mean(positive delays)` — documented as a proxy |
| `fleet_utilisation` | `mean(on_board / capacity)` across all stop-events |
| `eta_mae` | Mean \|estimated_arrival − actual_arrival\| in minutes |
| `eta_calibration` | Fraction of future-stop ETAs where actual fell inside the stated CI |
| `missed_connection` | Transfer failure with > 10 extra minutes of wait vs on-time scenario |

---

## Baselines

Two baselines are computed for comparison.

**Naive baseline** — every route uses a 30-seat minibus throughout the operating day.
No demand-aware adjustments. This creates genuine peak-hour crowding.

**Rule-based baseline** — routes where estimated peak demand exceeds 80% of minibus
capacity are upgraded to 60-seat buses for the entire day. This is a static rule
applied once at plan-build time. It cannot add extra trips or shift departure times,
and it pays the cost of large buses during off-peak periods.

RoutePulse makes surgical per-trip upgrades, adds targeted extra departures, and shifts
departure times. It outperforms the naive baseline on service rate. The rule-based
baseline scores higher on raw throughput metrics because blanket all-day large buses
carry more passengers — this trade-off is shown honestly in the recommendations page.

---

## Running

**Requirements**: Python 3.11+, packages listed in `requirements.txt`.

```bash
# Create environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the dashboard
streamlit run app/main.py --server.port 8501

# Run the full evaluation
python eval/run_evaluation.py

# Run the test suite
pytest tests/ -v
```

The app works fully offline. Map tiles use `carto-darkmatter` (served by Plotly's
embedded tile data; no external requests required for the map to render).
Google Fonts are not used; the UI uses the system sans-serif stack.

---

## Reproducibility

All randomness is seeded. Given the same seed, every simulation run produces
identical results. The `SEED` constant in `config.py` is the base seed; evaluation
uses `SEED` through `SEED + N_EVAL_SEEDS - 1` (42–52 by default).

To change the campus layout, demand model, or vehicle types, modify `config.py`
and re-run. No parameters are hardcoded in page code or optimizer logic.

---

## Tests

```
tests/
├── test_models.py       Stop geometry, route timing, StopEvent properties
├── test_detector.py     Crowding detection consistency, schedule conflict detection
├── test_estimator.py    Kalman update/predict, ETA calibration range, loop-route timing
├── test_validator.py    All 7 checks: individual and combined, optimised plan passes
├── test_optimizer.py    Honest benefit labels, service rate improves, action_summary
└── test_forecaster.py   Training, holdout evaluation, horizon prediction
```

Run: `pytest tests/ -v` — 35 tests, all pass.

---

## Campus: Westbrook University

10 stops, 4 routes, 12 vehicles (8 × 30-seat, 4 × 60-seat).
Operating hours 08:00–20:00, 15-minute headway.

| Route | Name | Stops |
|-------|------|-------|
| R1 | Main Shuttle | Halls North → Central Square → Science Faculty → Engineering → Medical → Central Square → Student Union → Main Entrance |
| R2 | North Loop | Main Entrance → Central Square → Halls North → Sports Complex → Science Faculty → Engineering |
| R3 | South Express | Main Entrance → Student Union → Library & IT → Business School → Engineering → Medical |
| R4 | Cross-Campus Link | Science Faculty → Medical → Business School → Library & IT → Student Union → Central Square |

Stop coordinates are fictional (centred on 51.50°N, 0.14°W, spread ~1.5 km).

---

## Disruption scenarios

| Scenario | Description |
|----------|-------------|
| Sports Event | 5× demand at Sports Complex, 15:00–16:30 |
| Morning Traffic | +8 min/segment delay on all routes, 08:00–10:30 |
| Fleet Breakdown | 3 consecutive Main Shuttle departures cancelled from 09:00 |
| Compound Crisis | All three simultaneously |

---

## Licence

Academic / hackathon submission. No real passenger data. All campus data is synthetic.
