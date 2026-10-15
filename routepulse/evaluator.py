"""
Metrics evaluator for RoutePulse.

Computes all evaluation metrics for a simulated plan and supports
multi-seed evaluation for robustness reporting.
"""
from __future__ import annotations
import math
from typing import List, Dict

import numpy as np

from routepulse.config import AVG_WAIT_BASE
from routepulse.models import Plan, SimulatedTrip, EvaluationResult
from routepulse.estimator import evaluate_eta_over_trips
from routepulse.detector import detect_all
from routepulse.validator import validate


# ---------------------------------------------------------------------------
# Single-seed metrics
# ---------------------------------------------------------------------------
def compute_metrics(
    plan: Plan,
    trips: List[SimulatedTrip],
    seed: int,
) -> Dict:
    """Return a flat dict of all metrics for one simulation run."""
    if not trips:
        return {k: 0.0 for k in _METRIC_KEYS}

    # ETA metrics
    eta = evaluate_eta_over_trips(trips)

    # Overcrowding & demand
    total_overcrowding = sum(
        1 for t in trips for ev in t.stop_events if ev.overcrowded
    )
    total_unmet = sum(t.total_unmet_demand for t in trips)

    # Average wait: proxy = HEADWAY / 2 + mean delay at each stop
    # (proper passenger waiting model would require individual passenger records)
    all_delays = [ev.delay for t in trips for ev in t.stop_events]
    mean_delay = sum(max(0, d) for d in all_delays) / len(all_delays) if all_delays else 0.0
    avg_wait = AVG_WAIT_BASE + mean_delay   # half-headway base + propagated delay

    # Fleet utilisation
    load_fracs = [
        ev.on_board_after / ev.capacity
        for t in trips for ev in t.stop_events if ev.capacity > 0
    ]
    fleet_util = sum(load_fracs) / len(load_fracs) if load_fracs else 0.0

    # Violations (from detector)
    det = detect_all(plan, trips)
    missed_connections = len(det["missed_connections"])

    # Independent validator
    val_report = validate(plan, trips)
    constraint_violations = val_report.n_violations

    return {
        "eta_mae_minutes": eta["eta_mae_minutes"],
        "eta_calibration": eta["eta_calibration"],
        "overcrowding_events": total_overcrowding,
        "total_unmet_demand": total_unmet,
        "missed_connections": missed_connections,
        "average_wait_minutes": round(avg_wait, 2),
        "fleet_utilisation": round(fleet_util, 3),
        "constraint_violations": constraint_violations,
    }


_METRIC_KEYS = [
    "eta_mae_minutes", "eta_calibration",
    "overcrowding_events", "total_unmet_demand",
    "missed_connections", "average_wait_minutes",
    "fleet_utilisation", "constraint_violations",
]


# ---------------------------------------------------------------------------
# Multi-seed evaluation
# ---------------------------------------------------------------------------
def evaluate_plan_multi_seed(
    plan: Plan,
    seeds: List[int],
    disruptions=None,
) -> EvaluationResult:
    """
    Run the plan under multiple seeds, return aggregated EvaluationResult.

    Uses mean across seeds; CI is ~95% normal interval reported separately.
    """
    from routepulse.simulator import simulate_plan

    all_metrics: List[Dict] = []
    for s in seeds:
        trips = simulate_plan(plan, base_seed=s, disruptions=disruptions)
        m = compute_metrics(plan, trips, s)
        all_metrics.append(m)

    def _mean(key):
        vals = [m[key] for m in all_metrics]
        return sum(vals) / len(vals)

    return EvaluationResult(
        plan=plan,
        eta_mae=round(_mean("eta_mae_minutes"), 3),
        eta_calibration=round(_mean("eta_calibration"), 3),
        overcrowding_events=round(_mean("overcrowding_events")),
        total_unmet_demand=round(_mean("total_unmet_demand")),
        missed_connections=round(_mean("missed_connections")),
        average_wait_minutes=round(_mean("average_wait_minutes"), 2),
        fleet_utilisation=round(_mean("fleet_utilisation"), 3),
        constraint_violations=round(_mean("constraint_violations")),
        seeds_used=seeds,
    )


def compute_multi_seed_ci(
    plan: Plan,
    seeds: List[int],
    disruptions=None,
) -> Dict[str, Dict]:
    """
    Compute per-metric mean and 95% CI across seeds.
    Returns: {metric_key: {"mean": ..., "ci95_low": ..., "ci95_high": ...}}
    """
    from routepulse.simulator import simulate_plan

    all_metrics: List[Dict] = []
    for s in seeds:
        trips = simulate_plan(plan, base_seed=s, disruptions=disruptions)
        m = compute_metrics(plan, trips, s)
        all_metrics.append(m)

    results = {}
    for key in _METRIC_KEYS:
        vals = np.array([m[key] for m in all_metrics])
        mean = float(np.mean(vals))
        se = float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0
        results[key] = {
            "mean": round(mean, 3),
            "ci95_low": round(mean - 1.96 * se, 3),
            "ci95_high": round(mean + 1.96 * se, 3),
            "n_seeds": len(seeds),
        }
    return results


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------
def comparison_table(results: List[EvaluationResult]) -> List[Dict]:
    """Format a list of EvaluationResult into a comparison table (list of row dicts)."""
    rows = []
    for er in results:
        rows.append({
            "Plan": er.plan.name,
            "ETA MAE (min)": er.eta_mae,
            "ETA Calibration": f"{er.eta_calibration:.1%}",
            "Overcrowding Events": er.overcrowding_events,
            "Unmet Demand": er.total_unmet_demand,
            "Missed Connections": er.missed_connections,
            "Avg Wait (min)": er.average_wait_minutes,
            "Fleet Utilisation": f"{er.fleet_utilisation:.1%}",
            "Constraint Violations": er.constraint_violations,
        })
    return rows


def improvement_table(baseline: EvaluationResult, proposed: EvaluationResult) -> List[Dict]:
    """Show improvement of proposed vs baseline (lower is better for most metrics)."""
    rows = []
    metrics = [
        ("ETA MAE (min)", "eta_mae", False),
        ("Overcrowding Events", "overcrowding_events", False),
        ("Unmet Demand", "total_unmet_demand", False),
        ("Missed Connections", "missed_connections", False),
        ("Avg Wait (min)", "average_wait_minutes", False),
        ("Fleet Utilisation", "fleet_utilisation", True),   # higher is better
        ("ETA Calibration", "eta_calibration", True),       # higher is better
    ]
    for label, attr, higher_is_better in metrics:
        base_val = getattr(baseline, attr)
        prop_val = getattr(proposed, attr)
        if base_val != 0:
            delta_pct = (prop_val - base_val) / base_val * 100
        else:
            delta_pct = 0.0
        better = (delta_pct < 0) if not higher_is_better else (delta_pct > 0)
        rows.append({
            "Metric": label,
            "Baseline": base_val,
            "Proposed": prop_val,
            "Δ": round(prop_val - base_val, 3),
            "Δ%": f"{delta_pct:+.1f}%",
            "Better?": "✓" if better else ("=" if delta_pct == 0 else "✗"),
        })
    return rows
