# RoutePulse — Review & Redesign Plan

**Status**: In progress  
**Started**: 2026-10-15  
**Commit target**: Small, frequent commits; every step leaves the app runnable.

---

## Audit Findings

### Critical bugs (incorrect results)

| # | Location | Issue | Root cause |
|---|----------|--------|------------|
| B1 | `simulator.py` / `models.py` | **Loop-return stop gets wrong scheduled time.** R1 ends at "Main Gate" again. `scheduled_arrival_at("S1")` returns the *departure* time (0 cumulative), not the return time (7.33 min cumulative). Every loop-close trip shows ~+10 min fake delay at the last stop. | `Route.stop_index` returns the *first* index for a stop that appears twice; scheduled arrival uses that index's cumulative time (0) instead of the return index. |
| B2 | `models.py:StopEvent.overcrowded` | **Overcrowded is `on_board > capacity` (strict).** So "at capacity" is never flagged. Result: 0 overcrowding events reported while 1,456 passengers can't board and numerous stops show `on_board == capacity`. The contradiction (zero overcrowding + thousands unmet) is the metric definition bug. | Change definition to `>=`, or (better) track `unmet_demand > 0` as the crowding signal and rename the overcrowding counter clearly. |
| B3 | `estimator.py` | **ETA calibration is 44.5% for a 90% CI (should be ~90%).** The Kalman filter is massively overconfident — process noise too small, initial uncertainty too small relative to actual travel-time variance (0.8 min/segment noise). The CI half-width is too narrow. | Tune Q and R relative to actual delay variance, or (honest fix) report the actual calibration and document the gap. Also: the eval only uses the first half of a trip as "observed" which compounds the problem. |
| B4 | `data_gen.py` + schedule | **Campus is too easy.** Demand per trip at peak: R1 carries ~40 pax/trip across 6 stops with a 40-seat bus, so it fills up but barely. Small buses on R2/R3 (25 seats) are genuinely stressed at peak (unmet demand 7–22/stop) but the naive baseline already uses the large bus on R1. There is nothing RoutePulse can do that a static smarter baseline can't also do, because the smarter baseline gets the same vehicle upgrade logic. | Redesign campus: larger demand numbers, more routes, realistic congestion. Or keep campus but make the baseline provably worse (static small buses everywhere) and the smarter baseline only slightly better. |
| B5 | `optimizer.py:recommend_vehicle_swaps` | **Benefit label is arithmetically wrong.** Claims "Eliminate X unmet passengers" where X > (large_cap − small_cap) = 15. One extra seat can carry at most 15 more passengers, but trips with 22 unmet claim full elimination. | Compute correct benefit: `min(trip.total_unmet_demand, LARGE_BUS_CAPACITY - dep.vehicle.capacity)`. |
| B6 | `optimizer.py:tradeoff_summary` | **"~+N% marginal fuel cost" is fabricated.** Formula `n_swaps * 15 + n_extra * 10` has no basis. With 10 swaps this claims +150% fuel cost which is absurd. | Remove fabricated cost estimates. Show counts only, or use realistic fuel cost model. |
| B7 | `validator.py` | **Validator is far too shallow.** Checks: operating window, minimum headway, no duplicates, no empty routes. Does NOT check: vehicle inventory (one vehicle can't run 48 simultaneous trips), turnaround feasibility, whether extra trips added by optimizer have real vehicles assigned, capacity at each stop. | Expand validator with: fleet inventory check (a vehicle ID cannot be used on overlapping trips), turnaround time check (gap between trips for same vehicle >= minimum turnaround), travel-time feasibility. |
| B8 | `evaluator.py` | **Smarter baseline beats RoutePulse on unmet demand** because the smarter baseline swaps to large buses on routes that need it, while RoutePulse only triggers swaps when `mean_load > 0.92` — a threshold so high it rarely fires on the current low-demand campus. | Fix: either make the campus genuinely stressed (B4), or make the optimizer trigger earlier and more aggressively in a clearly documented way. |
| B9 | `data_gen.py:build_smarter_baseline_plan` | **Smarter baseline is compared unfairly.** It uses the same vehicle on all departures all day (peak assignment), not just at peak. This gives it an advantage RoutePulse can't match without adding cost. The comparison should be fair. | Smarter baseline should only upgrade vehicles for peak-hour departures, not all-day. |
| B10 | `app/pages/04_forecasting.py` | **Page crashes** on `forecaster.predict_demand` because `_prepare` uses `df[["stop_id"]]` to transform, but the comparison chart builds a new df without the right columns. Also `get_forecaster()` may fail silently. | Fix the forecasting page with proper error handling and correct column handling. |
| B11 | `app/pages/01_overview.py` | **Map uses CartoDB dark_matter tiles** which require internet and an API key in some configs. Stops are at real London coordinates (51.5, -0.14) but visually appear bunched because campus spread is only ~0.01 degrees. | Switch to offline-capable tiles (OpenStreetMap or None), and spread the campus coordinates so the map is readable. |
| B12 | `disruptions/scenarios.py` | **Disruptions barely change metrics.** Morning traffic adds 4 min/segment to 8 affected trips; with 144 total trips the aggregate impact is tiny. Sports event spike at S6 (low-demand stop) with 3x multiplier adds ~15 pax to an already lightly loaded stop. | Make disruptions realistic: cancel 2-3 vehicles for breakdown, add 10-15 min delay to all peak departures for traffic, model a 500-student lecture ending for demand spike. |
| B13 | `app/pages/02_arrivals.py` | **100% calibration on tiny sample.** The page evaluates only the single selected trip's second half (2-3 stops). Calibration of 100% on 2 checks is statistically meaningless. | Show calibration computed over all trips and all seeds with proper CI. |

### UI/UX issues

| # | Issue |
|---|-------|
| U1 | Pages named by code structure (01_overview, 02_arrivals) not by user question |
| U2 | "Seed" exposed to operator — meaningless to non-developers |
| U3 | Every page repeats CSS injection — should be in one place |
| U4 | No empty/loading/error state handling — pages crash instead of failing gracefully |
| U5 | Raw IDs (D0000, V05, S1) shown in user-facing tables |
| U6 | No units on numbers (waiting time in what?), no context (is 8.35 min wait good or bad?) |
| U7 | Emojis used as decoration inconsistently |
| U8 | Recommendations page shows deltas only vs naive — must also show vs smarter baseline |
| U9 | No passenger-facing view |
| U10 | First screen says product does things — doesn't give honest measured summary |
| U11 | Charts are plotly dark but some have no axis labels or misleading y-axis |
| U12 | No font bundling — fonts loaded from Google Fonts (breaks offline) |
| U13 | Icon style is inconsistent (emoji vs SVG vs none) |
| U14 | "Developer chrome" visible: seed number inputs, plan IDs, internal metric names |
| U15 | No demo path / guided flow for judges |

---

## Approach

### Principles
1. **Fix root causes, not symptoms.** Don't hide bad results with display tricks.
2. **Freeze baselines before evaluating.** No tuning after seeing results.
3. **Every number shown must be computed from simulation data.**
4. **Honest reporting:** If RoutePulse loses on a metric vs smarter baseline, say so and explain why.
5. **Small commits after every meaningful fix.**

### Frozen baselines (defined before any metric tuning)
- **Naive baseline**: Every route uses the cheapest vehicle (small bus, 25 seats) all day.
- **Smarter baseline**: Peak-hour trips (08:45–10:00, 11:45–14:00, 16:30–18:00) use large bus on routes where estimated peak demand exceeds 80% of small-bus capacity. Off-peak keeps small bus.
- **RoutePulse**: Detects violations in simulation, applies swaps + extra trips + nudges.

RoutePulse target wins:
- Missed connections (nudges)
- Overflow events at peak (targeted swaps more surgical than static day-long upgrade)
- ETA accuracy (Kalman filter)

RoutePulse honest losses:
- Aggregate unmet demand vs smarter baseline (static all-day upgrade is hard to beat on this one metric alone — we say so)
- Fleet cost (more operational changes = more cost — we show the trade-off)

---

## Prioritised Task Order

### Phase 1 — Fix data layer (campus, demand, schedule)
- [x] B1: Fix loop-return stop scheduled arrival (use last index, not first)
- [ ] B4: Redesign campus demand so naive baseline genuinely fails (larger rates, 5 routes)
- [ ] B9: Fix smarter baseline (peak-hour upgrade only, not all-day)

### Phase 2 — Fix metrics and evaluator
- [ ] B2: Fix overcrowding definition / rename; document each metric clearly
- [ ] B3: Fix ETA calibration — tune Kalman or report honestly with context
- [ ] Add `crowding_events` = stops where unmet_demand > 0 (more honest than overcrowded)
- [ ] Multi-seed spread: show mean ± 1 std across seeds, not just mean

### Phase 3 — Fix optimizer and validator
- [ ] B5: Fix arithmetically wrong benefit labels
- [ ] B6: Remove fabricated cost percentages
- [ ] B7: Expand validator (fleet inventory, turnaround, travel feasibility)
- [ ] B8: Make optimizer triggers fire on the redesigned campus

### Phase 4 — Fix disruptions
- [ ] B12: Make disruptions realistic (larger delays, more affected trips)
- [ ] Add recovery churn metric (how many departures changed)
- [ ] Show "disrupted but no replan" vs "disrupted + replan" clearly

### Phase 5 — Fix ETA and forecasting
- [ ] B3: Fix Kalman CI width (recalibrate Q/R or widen uncertainty)
- [ ] B10: Fix forecasting page crash
- [ ] Add naive forecast baseline (previous-slot demand) to compare against

### Phase 6 — UI redesign
- [ ] B11: Fix map tiles (offline OSM)
- [ ] Rename pages to human questions
- [ ] Remove seed/ID exposure from operator view
- [ ] Add units, context, and benchmarks to every metric
- [ ] Add passenger arrival window view
- [ ] Add guided demo path / landing page
- [ ] Bundle fonts locally
- [ ] Add consistent icon style (lucide SVG or text)
- [ ] Fix error/loading/empty states

### Phase 7 — Tests
- [ ] Tests for metric calculations (overcrowding, unmet, calibration)
- [ ] Tests for validator with deliberately bad plans
- [ ] Tests for consistency between pages (same data, same result)

---

## Git rules for this pass
- Commit after every completed task from the list above
- Message format: lowercase, casual, specific (e.g. "fix loop stop scheduled time bug")
- Never commit .venv/, __pycache__, .pytest_cache, *.pyc, eval/results.json
- Check `git status` before every commit

---

*Last updated: starting Phase 1*
