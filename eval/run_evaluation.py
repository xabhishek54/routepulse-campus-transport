#!/usr/bin/env python3
"""
One-command reproducible evaluation for RoutePulse.

Usage:
    python eval/run_evaluation.py

This script:
  1. Generates campus data with SEED=42
  2. Simulates baseline, smarter baseline, and recommended plans
  3. Runs multi-seed evaluation (seeds 42-52)
  4. Prints the comparison table
  5. Saves results to eval/results.json

All randomness is seeded for full reproducibility.
"""
import sys
import os
import json

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routepulse.data_gen import build_campus, build_baseline_plan, build_smarter_baseline_plan
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_all
from routepulse.optimizer import build_recommended_plan, tradeoff_summary
from routepulse.evaluator import (
    evaluate_plan_multi_seed, comparison_table, improvement_table,
    compute_multi_seed_ci,
)
from routepulse.validator import validate

EVAL_SEEDS = list(range(42, 53))  # seeds 42–52 for robustness


def main():
    print("=" * 60)
    print("  RoutePulse — Evaluation Report")
    print("=" * 60)
    print(f"\nEvaluation seeds: {EVAL_SEEDS[0]}–{EVAL_SEEDS[-1]} ({len(EVAL_SEEDS)} seeds)")
    print("Campus: Westbrook University (synthetic)")
    print("Window: 08:00–20:00, typical Tuesday\n")

    # ----------------------------------------------------------------
    # Build campus
    # ----------------------------------------------------------------
    stops, routes, vehicles, departures = build_campus()
    print(f"Campus: {len(stops)} stops, {len(routes)} routes, {len(vehicles)} vehicles")
    print(f"Schedule: {len(departures)} departures\n")

    # ----------------------------------------------------------------
    # Plans
    # ----------------------------------------------------------------
    baseline = build_baseline_plan(departures=departures)
    smarter  = build_smarter_baseline_plan(stops=stops, routes=routes, vehicles=vehicles)

    # Generate recommended plan from seed-42 simulation
    print("Generating recommended plan (seed 42)...")
    trips_42 = simulate_plan(baseline, base_seed=42)
    det = detect_all(baseline, trips_42)
    recommended = build_recommended_plan(baseline, trips_42, det["missed_connections"])
    ts = tradeoff_summary(recommended.actions_applied)
    print(f"  Vehicle upgrades: {ts['vehicle_upgrades']}")
    print(f"  Extra trips:      {ts['extra_trips']}")
    print(f"  Departure nudges: {ts['departure_nudges']}\n")

    # ----------------------------------------------------------------
    # Validate all plans (independent checker)
    # ----------------------------------------------------------------
    print("Constraint validation (independent checker):")
    for plan in [baseline, smarter, recommended]:
        report = validate(plan)
        status = "PASS ✓" if report.passed else f"FAIL ✗ ({report.n_violations} violations)"
        print(f"  {plan.name:35s}: {status}")
    print()

    # ----------------------------------------------------------------
    # Multi-seed evaluation
    # ----------------------------------------------------------------
    print("Running multi-seed evaluation...")
    results = []
    for plan in [baseline, smarter, recommended]:
        print(f"  Evaluating '{plan.name}'...", end="", flush=True)
        er = evaluate_plan_multi_seed(plan, EVAL_SEEDS)
        results.append(er)
        print(" done")

    # ----------------------------------------------------------------
    # Comparison table
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  COMPARISON TABLE (mean over 11 seeds)")
    print("=" * 60)
    rows = comparison_table(results)
    # Print as simple aligned table
    headers = list(rows[0].keys())
    col_w = {h: max(len(h), max(len(str(r[h])) for r in rows)) + 2 for h in headers}
    header_line = "  ".join(h.ljust(col_w[h]) for h in headers)
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print("  ".join(str(row[h]).ljust(col_w[h]) for h in headers))

    # ----------------------------------------------------------------
    # Improvement table (baseline → recommended)
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  IMPROVEMENT: Naive Baseline → RoutePulse Recommendation")
    print("=" * 60)
    impr = improvement_table(results[0], results[2])
    imp_headers = list(impr[0].keys())
    imp_w = {h: max(len(h), max(len(str(r[h])) for r in impr)) + 2 for h in imp_headers}
    imp_header_line = "  ".join(h.ljust(imp_w[h]) for h in imp_headers)
    print(imp_header_line)
    print("-" * len(imp_header_line))
    for row in impr:
        print("  ".join(str(row[h]).ljust(imp_w[h]) for h in imp_headers))

    # ----------------------------------------------------------------
    # Sensitivity check
    # ----------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  SENSITIVITY ANALYSIS")
    print("=" * 60)

    from routepulse.simulator import simulate_plan as sim
    from routepulse.evaluator import compute_metrics

    for travel_sigma, label in [(0.4, "Low noise (σ=0.4 min)"), (1.5, "High noise (σ=1.5 min)")]:
        trips_sens = [
            __import__("routepulse.simulator", fromlist=["simulate_trip"]).simulate_trip(
                dep, base_seed=42, travel_time_noise_sigma=travel_sigma
            )
            for dep in baseline.departures
        ]
        trips_sens = [t for t in trips_sens if t is not None]
        m = compute_metrics(baseline, trips_sens, 42)
        print(f"\n  {label}:")
        print(f"    ETA MAE: {m['eta_mae_minutes']:.3f} min")
        print(f"    Overcrowding events: {m['overcrowding_events']}")
        print(f"    Unmet demand: {m['total_unmet_demand']}")

    # ----------------------------------------------------------------
    # Save results
    # ----------------------------------------------------------------
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    output = {
        "seeds": EVAL_SEEDS,
        "plans": [
            {
                "plan_id": er.plan.plan_id,
                "name": er.plan.name,
                "eta_mae": er.eta_mae,
                "eta_calibration": er.eta_calibration,
                "overcrowding_events": er.overcrowding_events,
                "total_unmet_demand": er.total_unmet_demand,
                "missed_connections": er.missed_connections,
                "average_wait_minutes": er.average_wait_minutes,
                "fleet_utilisation": er.fleet_utilisation,
                "constraint_violations": er.constraint_violations,
            }
            for er in results
        ],
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")
    print("\nEvaluation complete.")


if __name__ == "__main__":
    main()
