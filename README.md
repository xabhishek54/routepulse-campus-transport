# RoutePulse 🚌

**Campus Transport Optimiser** — Hackathon: Wild Bugs  
Problem statement: *Optimise Campus Transport Under Real Constraints*

RoutePulse estimates arrival windows, forecasts passenger demand, detects overcrowding and missed connections, and recommends feasible route/vehicle adjustments with measurable improvement over a documented baseline.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the dashboard

```bash
streamlit run app/main.py
```

Navigate to `http://localhost:8501` — use the sidebar to explore all 5 pages.

### 3. Reproduce the evaluation

```bash
python eval/run_evaluation.py
```

This produces a comparison table and saves `eval/results.json`. Fixed seed=42–52, fully reproducible.

### 4. Run the tests

```bash
pytest tests/ -v
```

---

## Architecture

```
routepulse/
├── models.py       Core domain objects (Stop, Route, Trip, ETAEstimate…)
├── data_gen.py     Synthetic campus data generator (fixed seed)
├── simulator.py    Discrete-event bus simulator with disruption support
├── estimator.py    Kalman-filter arrival estimation with uncertainty
├── detector.py     Overcrowding, conflict, and missed-connection detection
├── validator.py    Independent hard-constraint checker
├── optimizer.py    Greedy feasible recommendations (vehicle swap, nudge, extra trip)
├── evaluator.py    Metrics computation and multi-seed evaluation
└── scenarios.py    Named disruption scenarios for demo

app/
├── main.py             Landing page
└── pages/
    ├── 01_overview.py      Campus map, routes, schedule
    ├── 02_arrivals.py      ETA with confidence intervals
    ├── 03_violations.py    Overcrowding, conflicts, missed connections
    ├── 04_recommendations.py  Plan comparison and trade-off explorer
    └── 05_disruptions.py   Disruption replay and replanning

eval/
└── run_evaluation.py   One-command evaluation (seeds 42–52)
```

---

## Campus: Westbrook University (synthetic)

- **8 stops**: Main Gate, Science Block, Library Hub, Student Union, Residences North, Sports Centre, Engineering Block, Medical School
- **3 routes**: Campus Loop (R1), North Connector (R2), East Express (R3)
- **7 vehicles**: 4 × minibus (25 pax), 3 × bus (40 pax)
- **Departures**: Every 15 min, 08:00–20:00 → ~144 trips/day
- **Demand**: Poisson model, peaks at class changeovers (09:00, 10:00…), lunch (12:00–13:30), evening exodus (17:00–19:00)

All data is synthetic. No real passenger information. Fully reproducible from `SEED=42`.

---

## Evaluation Metrics

| Metric | Description |
|--------|-------------|
| ETA MAE | Mean absolute error of Kalman arrival estimates |
| ETA Calibration | Fraction of estimates where actual arrival fell inside 90% CI |
| Overcrowding Events | Stops where on-board > vehicle capacity |
| Unmet Demand | Passengers unable to board |
| Missed Connections | Transfer events where next bus is >15 min late |
| Average Wait | Mean passenger waiting time |
| Fleet Utilisation | Mean load/capacity ratio |
| Constraint Violations | Count from independent validator |

### Plans compared

1. **Naive Baseline** — fixed static schedule, no adaptation
2. **Smarter Baseline** — upgrades to large bus on routes predicted to exceed 80% peak load
3. **RoutePulse Recommendation** — vehicle swaps, extra trips, departure nudges; all validated before display

---

## Design Decisions

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full architecture rationale, ambiguity resolution, risk table, and what gets cut under time pressure.

Key choices:
- **Kalman filter** for ETA: honest uncertainty, grows with stops ahead, calibration is measured
- **Independent validator** (separate from optimizer): can't be gamed, same rules for all plans
- **Greedy heuristics** (not full solver): explainable, fast, always feasible
- **Fixed seeds 42–52**: single command reproduces all results, no lucky-run problem

---

## Demo Script (5-min demo)

1. **Overview** — show the campus map, routes, demand curve. Point out peak at 09:00 and 17:00.
2. **Arrivals** — pick R1, 09:00 departure. Show Kalman ETA with CI band. Note calibration %.
3. **Violations** — show overcrowding heatmap and missed connections at Library Hub.
4. **Recommendations** — show radar chart before/after. Expand 2 action items.
5. **Disruptions** — select "Sports Event Surge". Show recovery score. Explain 3-state comparison.

---

## Assumptions & Caveats

- All data is synthetic. Campus layout, demands, and travel times are fictional.
- Demand model is Poisson; real demand has more structure (e.g., exact class sizes).
- Travel times use Haversine distance at fixed 15 km/h; real roads vary.
- "Missed connection" definition: no onward bus for the same route within 15 minutes.
- Sensitivity to ±20% travel time and ±30% demand is shown in the evaluation output.
