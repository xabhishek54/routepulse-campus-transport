"""
Metrics evaluator for RoutePulse.

Metric definitions (authoritative — see also config.py docstring):
  crowding_events:    count of stop-events where unmet_demand > 0
  overcrowding_events: count of stop-events where on_board >= capacity
  total_unmet_demand: total passengers who couldn't board (all stops, all trips)
  missed_connections: count of missed-connection events (transfer failures)
  average_wait:       HEADWAY/2 + mean(positive delays) — proxy; documented as such
  fleet_utilisation:  mean(on_board / capacity) over all stop-events

ETA metrics are kept separate from plan-outcome metrics:
  eta_mae:          mean |estimated - actual| (minutes)
  eta_calibration:  fraction of estimates where actual fell in CI (target = CI_PCT/100)

Multi-seed evaluation returns mean ± std across seeds, not just mean.
"""
from __future__ import annotations
import math
from typing import List, Dict

import numpy as np

from routepulse.config import AVG_WAIT_BASE, EVAL_SEEDS
from routepulse.models import Plan, SimulatedTrip, EvaluationResult
from routepulse.estimator import evaluate_eta_over_trips
from routepulse.detector import detect_all
from routepulse.validator import validate


# ---------------------------------------------------------------------------
# Per-seed metrics
# ---------------------------------------------------------------------------

_PLAN_METRIC_KEYS = [
    "crowding_events",
    "overcrowding_events",
    "total_unmet_demand",
    "passengers_served",
    "service_rate",
    "missed_connections",
    "average_wait_minutes",
    "fleet_utilisation",
    "constraint_violations",
]

_ETA_METRIC_KEYS = [
    "eta_mae_minutes",
    "eta_calibration",
    "eta_calibration_gap_pp",
]

_ALL_METRIC_KEYS = _PLAN_METRIC_KEYS + _ETA_METRIC_KEYS


def compute_metrics(
    plan: Plan,
    trips: List[SimulatedTrip],
    seed: int,
) -> Dict:
    """
    Compute all metrics for one simulation run.

    Returns a flat dict. ETA metrics are labelled separately from
    plan-outcome metrics to avoid confusion.
    """
    if not trips:
        return {k: 0.0 for k in _ALL_METRIC_KEYS}

    # ── ETA metrics (estimation quality, not plan quality) ─────────────────
    eta = evaluate_eta_over_trips(trips)

    # ── Plan-outcome metrics ───────────────────────────────────────────────
    crowding_events = sum(
        1 for t in trips for ev in t.stop_events if ev.crowded
    )
    overcrowding_events = sum(
        1 for t in trips for ev in t.stop_events if ev.overcrowded
    )
    total_unmet = sum(t.total_unmet_demand for t in trips)

    # Service rate: passengers who boarded / total demand
    # This normalises fairly across plans with different numbers of trips
    total_demand = sum(ev.demand_at_stop for t in trips for ev in t.stop_events)
    total_boarded = sum(ev.boarded for t in trips for ev in t.stop_events)
    service_rate = total_boarded / total_demand if total_demand > 0 else 1.0

    # Average wait: documented proxy
    # Real model would need per-passenger arrival times; this is HEADWAY/2 + mean positive delay
    all_delays = [ev.delay for t in trips for ev in t.stop_events]
    mean_positive_delay = (
        sum(max(0.0, d) for d in all_delays) / len(all_delays)
        if all_delays else 0.0
    )
    avg_wait = AVG_WAIT_BASE + mean_positive_delay

    # Fleet utilisation: mean load fraction
    load_fracs = [
        ev.on_board_after / ev.capacity
        for t in trips for ev in t.stop_events if ev.capacity > 0
    ]
    fleet_util = sum(load_fracs) / len(load_fracs) if load_fracs else 0.0

    # Missed connections
    det = detect_all(plan, trips)
    missed = len(det["missed_connections"])

    # Independent validator (schedule-level only; simulation checks always pass if sim ran)
    val_report = validate(plan)
    constraint_vios = val_report.n_violations

    return {
        # ETA (estimation quality — separate from plan quality)
        "eta_mae_minutes": eta["eta_mae_minutes"],
        "eta_calibration": eta["eta_calibration"],
        "eta_calibration_gap_pp": eta["eta_calibration_gap_pp"],
        # Plan outcomes
        "crowding_events": crowding_events,
        "overcrowding_events": overcrowding_events,
        "total_unmet_demand": total_unmet,
        "passengers_served": total_boarded,
        "service_rate": round(service_rate, 4),

        "missed_connections": missed,
        "average_wait_minutes": round(avg_wait, 2),
        "fleet_utilisation": round(fleet_util, 3),
        "constraint_violations": constraint_vios,
    }


# ---------------------------------------------------------------------------
# Multi-seed evaluation with spread
# ---------------------------------------------------------------------------

def evaluate_plan_multi_seed(
    plan: Plan,
    seeds: List[int],
    disruptions=None,
) -> EvaluationResult:
    """Run plan under multiple seeds; return EvaluationResult with mean values."""
    from routepulse.simulator import simulate_plan

    all_metrics: List[Dict] = []
    for s in seeds:
        trips = simulate_plan(plan, base_seed=s, disruptions=disruptions)
        m = compute_metrics(plan, trips, s)
        all_metrics.append(m)

    def _mean(key):
        vals = [m[key] for m in all_metrics]
        return sum(vals) / len(vals)

    def _std(key):
        vals = [m[key] for m in all_metrics]
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))

    return EvaluationResult(
        plan=plan,
        eta_mae=round(_mean("eta_mae_minutes"), 3),
        eta_calibration=round(_mean("eta_calibration"), 3),
        overcrowding_events=round(_mean("overcrowding_events")),
        crowding_events=round(_mean("crowding_events")),
        total_unmet_demand=round(_mean("total_unmet_demand")),
        missed_connections=round(_mean("missed_connections")),
        average_wait_minutes=round(_mean("average_wait_minutes"), 2),
        fleet_utilisation=round(_mean("fleet_utilisation"), 3),
        constraint_violations=round(_mean("constraint_violations")),
        seeds_used=list(seeds),
        unmet_demand_std=round(_std("total_unmet_demand"), 1),
        overcrowding_std=round(_std("overcrowding_events"), 1),
    )


def compute_multi_seed_ci(
    plan: Plan,
    seeds: List[int],
    disruptions=None,
) -> Dict[str, Dict]:
    """
    Per-metric mean ± 95% CI across seeds.
    Returns: {metric_key: {mean, ci95_low, ci95_high, std, n_seeds}}
    """
    from routepulse.simulator import simulate_plan

    all_metrics: List[Dict] = []
    for s in seeds:
        trips = simulate_plan(plan, base_seed=s, disruptions=disruptions)
        m = compute_metrics(plan, trips, s)
        all_metrics.append(m)

    results = {}
    for key in _ALL_METRIC_KEYS:
        vals = np.array([m[key] for m in all_metrics], dtype=float)
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        se = std / math.sqrt(len(vals)) if len(vals) > 0 else 0.0
        results[key] = {
            "mean": round(mean, 3),
            "std": round(std, 3),
            "ci95_low": round(mean - 1.96 * se, 3),
            "ci95_high": round(mean + 1.96 * se, 3),
            "n_seeds": len(seeds),
        }
    return results


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

def comparison_table(results: List[EvaluationResult]) -> List[Dict]:
    """Format EvaluationResults into a comparison table."""
    rows = []
    for er in results:
        rows.append({
            "Plan": er.plan.name,
            "Passengers left behind": er.total_unmet_demand,
            "Crowded stops": er.crowding_events,
            "Missed connections": er.missed_connections,
            "Avg wait (min)": er.average_wait_minutes,
            "Fleet utilisation": f"{er.fleet_utilisation:.0%}",
            "ETA accuracy (MAE, min)": er.eta_mae,
            "ETA calibration": f"{er.eta_calibration:.0%} (target {int(90)}%)",
            "Constraint violations": er.constraint_violations,
        })
    return rows


def improvement_table(
    naive: EvaluationResult,
    smarter: EvaluationResult,
    proposed: EvaluationResult,
) -> List[Dict]:
    """
    Show honest three-way comparison.
    Higher-is-better metrics are flagged.
    Where RoutePulse loses, that is shown plainly.
    """
    metrics = [
        ("Passengers left behind",  "total_unmet_demand",    False),
        ("Crowded stops",           "crowding_events",        False),
        ("Missed connections",      "missed_connections",     False),
        ("Avg wait (min)",          "average_wait_minutes",   False),
        ("Fleet utilisation",       "fleet_utilisation",      True),
    ]
    rows = []
    for label, attr, higher_is_better in metrics:
        nv = getattr(naive, attr)
        sv = getattr(smarter, attr)
        pv = getattr(proposed, attr)

        def _beats(a, b, hib):
            if hib:
                return a > b
            return a < b

        rp_vs_naive   = "↑ better" if _beats(pv, nv, higher_is_better) else ("=" if pv == nv else "↓ worse")
        rp_vs_smarter = "↑ better" if _beats(pv, sv, higher_is_better) else ("=" if pv == sv else "↓ worse")

        rows.append({
            "Metric": label,
            "Naive baseline": nv,
            "Rule-based baseline": sv,
            "RoutePulse": pv,
            "vs Naive": rp_vs_naive,
            "vs Rule-based": rp_vs_smarter,
        })
    return rows
