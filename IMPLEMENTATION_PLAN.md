# RoutePulse — Implementation Plan

## Problem Understanding

Large campuses run multiple fixed routes with departure windows, capacity-limited vehicles, and stops with uneven passenger demand. The core problems are:

1. **Arrival uncertainty** — passengers don't know when the bus will actually arrive
2. **Overcrowding** — popular stops/times exceed vehicle capacity
3. **Missed connections** — passengers miss onward routes due to delays
4. **Scheduling rigidity** — fixed schedules don't adapt to demand spikes (class changeovers, events)

We need to go beyond "show vehicle locations" to: estimate arrival windows, forecast demand, detect violations, recommend feasible adjustments, and prove measurable improvement over a baseline.

---

## Architecture

```
RoutePulse/
├── data/
│   ├── seed/               # Small static reference data (stops, routes, base schedule)
│   └── generated/          # Synthetic GPS traces, demand logs (gitignored - big files)
│       └── .gitkeep
├── routepulse/             # Core Python package
│   ├── __init__.py
│   ├── models.py           # Stop, Route, Schedule, Vehicle, Trip dataclasses
│   ├── data_gen.py         # Synthetic data generator (fixed seed)
│   ├── simulator.py        # Discrete-event bus simulator (GPS trace producer)
│   ├── estimator.py        # Arrival-window estimation (Kalman-inspired, with uncertainty)
│   ├── detector.py         # Overcrowding, capacity violation, missed-connection detection
│   ├── optimizer.py        # Feasible schedule/vehicle-allocation recommendations
│   ├── evaluator.py        # Metric calculation & baseline comparison
│   ├── validator.py        # Independent hard-constraint checker (separate from optimizer)
│   └── scenarios.py        # Named disruption scenarios for reproducible demos
├── app/                    # Streamlit web dashboard
│   ├── main.py
│   └── pages/
│       ├── 01_overview.py
│       ├── 02_arrivals.py
│       ├── 03_violations.py
│       ├── 04_recommendations.py
│       └── 05_disruptions.py
├── tests/
│   ├── test_models.py
│   ├── test_estimator.py
│   ├── test_detector.py
│   ├── test_optimizer.py
│   └── test_validator.py
├── eval/
│   └── run_evaluation.py   # One-command evaluation script
├── requirements.txt
└── README.md
```

---

## Tech Choices & Rationale

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.11+ | Rapid prototyping, rich data/stats libs |
| Data modelling | dataclasses + pandas | Simple, inspectable, no ORM overhead |
| Simulation | Custom discrete-event | Full control over timing, reproducible seeds |
| Arrival estimation | Kalman filter (simple 1D) | Principled uncertainty; honest confidence |
| Optimisation | greedy search | Feasible for demo scope; explainable |
| Constraint validation | Independent rule-checker module | Satisfies "trustworthy correctness" bar |
| Dashboard | Streamlit | Zero JS, fast to build, demo-friendly |
| Maps | folium embedded in Streamlit | Good enough for campus maps |
| Charts | plotly | Interactive, looks premium |
| Testing | pytest | Standard |

---

## Data Approach

**Campus model** — A fictional "Westbrook University" campus with:
- ~8 stops (gates, academic blocks, student hub, residences, sports centre)
- 3 routes, each serving a subset of stops
- 4 departure slots per hour per route (every 15 min)
- 2 vehicle types: small bus (25 pax) and large bus (40 pax)

**Demand model** — Demand is Poisson-sampled with rates driven by:
- Class changeover peaks at :00 and :30 each hour
- Lunch peak 12:00–13:30
- Evening exodus 17:00–19:00
- Low-demand off-peak periods
- Random events (e.g., sports match adds spike at sports centre)

**GPS traces** — Simulated with:
- Nominal speed with Gaussian noise
- Occasional delays (traffic, dwell time overruns)
- Disruptions: vehicle breakdown, unexpected demand surge

**Fixed seeds** — SEED = 42 throughout. All generation and simulation are reproducible.

**Baseline** — A "static schedule" that never adapts. Metrics computed over a fixed 08:00–20:00 operating window on a typical Tuesday.

**Smarter baseline** — A "round-robin reallocation" that swaps large/small vehicles when predicted load exceeds 80% but makes no other changes.

---

## Evaluation Approach

### Metrics (computed by evaluator.py, checked by validator.py)

| Metric | Definition |
|--------|------------|
| ETA MAE | Mean absolute error of arrival estimates vs. actual simulated arrival (minutes) |
| ETA calibration | % of trips where actual arrival fell within the stated confidence interval |
| Overcrowding events | Trips where boarded passengers > vehicle capacity |
| Missed connections | Passenger journeys where the intended onward bus had departed before they arrived |
| Unmet demand | Total passengers who couldn't board (all trips full at their stop) |
| Average wait | Mean waiting time across all passengers |
| Fleet utilisation | Average load / capacity across all trips |

### Comparison table

Each plan is evaluated: Naive baseline -> Smarter baseline -> RoutePulse recommendation.
Improvement reported as absolute delta and % change, with 95% CI over multiple seeds (42-52).

---

## Phased Task Breakdown

### Phase 1 — Foundation (MVP core)
- [x] Repo init, .gitignore, this plan
- [ ] models.py — Stop, Route, Schedule, Vehicle, Trip
- [ ] data_gen.py — synthetic stops, routes, schedules
- [ ] simulator.py — discrete-event trip simulation
- [ ] evaluator.py — baseline metric computation
- [ ] Commit: working data pipeline

### Phase 2 — Intelligence
- [ ] estimator.py — Kalman-filter ETA with uncertainty
- [ ] detector.py — overcrowding, missed connections, conflicts
- [ ] validator.py — independent hard-constraint checker
- [ ] Tests for all the above

### Phase 3 — Optimisation
- [ ] optimizer.py — feasible recommendations (vehicle swap, departure nudge, extra trip)
- [ ] scenarios.py — named disruption scenarios + replan
- [ ] eval/run_evaluation.py — one-command reproducible evaluation

### Phase 4 — Dashboard
- [ ] Streamlit app skeleton
- [ ] Overview page: map, route list, schedule table
- [ ] Arrivals page: ETA with confidence bands
- [ ] Violations page: overcrowding, missed connections
- [ ] Recommendations page: before/after comparison, trade-off sliders
- [ ] Disruptions page: replay and replan

### Phase 5 — Polish
- [ ] README with install + run instructions
- [ ] Sensitivity analysis (vary travel times +/-20%, demand +/-30%)
- [ ] Final evaluation table
- [ ] Demo script (repeatable 5-min demo flow)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Optimiser produces infeasible plans | Validator runs as a separate pass and blocks any infeasible plan from being shown |
| Kalman filter diverges on noisy traces | Clamp covariance; fall back to rolling average if residuals too large |
| Streamlit too slow for large datasets | Keep generated data small (1 operating day, ~500 trips); cache with @st.cache_data |
| Demo breaks mid-presentation | Everything runs off fixed seed from local files; no network dependency |

---

## What Gets Cut If Time Is Short

1. Live/real-time feed (stick to simulation replay)
2. Fancy ML demand forecasting (Poisson model is good enough)
3. Passenger-facing mobile UI (operator dashboard is primary)
4. Full multi-day evaluation (one representative day is sufficient)
5. Constrained optimisation solver (greedy heuristic is fine and explainable)

---

## Ambiguous Requirements — Decisions Made

- "Campus" interpreted as a fictional mid-size university with ~8000 students
- "Arrival window" means a point estimate +/- a confidence half-width (e.g., "arrives in 4 +/- 1.2 min")
- "Feasible recommendation" means it doesn't violate capacity, timetable windows, or minimum headway
- "Missed connection" defined as: passenger arrives at transfer stop after their onward bus departed, with no bus for that route within 15 min
- Evaluation window: 08:00-20:00, typical Tuesday, seed 42; extensions use seeds 43-52

---

*Last updated: Phase 1 start*
