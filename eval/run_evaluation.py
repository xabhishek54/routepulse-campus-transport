#!/usr/bin/env python3
"""
RoutePulse full evaluation script.

Reproduces all numbers in the report:
  - Per-seed metrics for all three plans (naive, rule-based, RoutePulse)
  - Mean ± std across 11 seeds
  - ETA calibration
  - Demand forecaster holdout MAE

Output: Markdown report to stdout and eval/report.md.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routepulse.config import EVAL_SEEDS
from routepulse.data_gen import build_campus, build_naive_baseline, build_smarter_baseline_plan
from routepulse.simulator import simulate_plan
from routepulse.detector import detect_all
from routepulse.optimizer import build_recommended_plan, action_summary
from routepulse.evaluator import evaluate_plan_multi_seed, comparison_table, improvement_table
from routepulse.validator import validate
from routepulse.estimator import evaluate_eta_over_trips
from routepulse.forecaster import train_forecaster


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def fmt_float(v) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def main():
    t0 = time.time()
    seeds = list(EVAL_SEEDS)
    n = len(seeds)

    print(f"RoutePulse Evaluation Report")
    print(f"Seeds: {seeds[0]}–{seeds[-1]} ({n} runs)")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Build campus ──────────────────────────────────────────────────────────
    section("Building campus")
    stops, routes, vehicles, departures = build_campus()
    naive   = build_naive_baseline(departures=departures)
    smarter = build_smarter_baseline_plan(routes=routes, vehicles=vehicles)
    print(f"  Stops: {len(stops)}, Routes: {len(routes)}, Vehicles: {len(vehicles)}")
    print(f"  Departures/day: {len(naive.departures)} (naive), {len(smarter.departures)} (rule-based)")

    # ── Validate baselines ────────────────────────────────────────────────────
    section("Validating baseline plans")
    for plan in [naive, smarter]:
        r = validate(plan)
        status = "PASS" if r.passed else f"FAIL ({r.n_violations} violations)"
        print(f"  {plan.name}: {status}")
        if not r.passed:
            for c in r.checks:
                if not c.passed:
                    print(f"    FAIL: {c.constraint}: {c.detail[:80]}")

    # ── Build optimised plan (using seed 42 as the "current day") ─────────────
    section("Building RoutePulse recommended plan (seed 42)")
    trips_42 = simulate_plan(naive, base_seed=42)
    det_42   = detect_all(naive, trips_42)
    optimised = build_recommended_plan(naive, trips_42, det_42["missed_connections"])
    val_opt  = validate(optimised)
    acts     = action_summary(optimised.actions_applied)
    print(f"  Plan: {optimised.plan_id}")
    print(f"  Validator: {'PASS' if val_opt.passed else 'FAIL'}")
    print(f"  Actions: {acts}")

    # ── Multi-seed evaluation ─────────────────────────────────────────────────
    section(f"Multi-seed evaluation ({n} seeds)")
    print("  Running... (this may take ~30 seconds)")

    er_naive    = evaluate_plan_multi_seed(naive, seeds)
    er_smarter  = evaluate_plan_multi_seed(smarter, seeds)
    er_optimised = evaluate_plan_multi_seed(optimised, seeds)

    print(f"\n  {'Metric':30s}  {'Naive':>12s}  {'Rule-based':>12s}  {'RoutePulse':>12s}")
    print(f"  {'-'*72}")

    metrics = [
        ("service_rate",        "Service rate",          True),
        ("crowding_events",     "Crowded stops",          False),
        ("total_unmet_demand",  "Passengers left behind", False),
        ("missed_connections",  "Missed connections",     False),
        ("average_wait_minutes","Avg wait (min)",          False),
        ("fleet_utilisation",   "Fleet utilisation",      True),
        ("eta_mae",             "ETA MAE (min)",          False),
        ("eta_calibration",     "ETA calibration",        True),
        ("constraint_violations","Constraint violations", False),
    ]

    for attr, label, hib in metrics:
        nv = getattr(er_naive, attr, None)
        sv = getattr(er_smarter, attr, None)
        ov = getattr(er_optimised, attr, None)

        def _fmt(v, is_pct=False):
            if v is None:
                return "  N/A"
            if is_pct:
                return f"  {v:.1%}"
            if isinstance(v, float):
                return f"  {v:.2f}"
            return f"  {v}"

        is_pct = attr in ("service_rate", "fleet_utilisation", "eta_calibration")
        rp_vs_naive   = "↑" if (hib and ov > nv) or (not hib and ov < nv) else ("=" if ov == nv else "↓")
        rp_vs_smarter = "↑" if (hib and ov > sv) or (not hib and ov < sv) else ("=" if ov == sv else "↓")
        print(
            f"  {label:30s}"
            f"{_fmt(nv, is_pct):>14s}"
            f"{_fmt(sv, is_pct):>14s}"
            f"{_fmt(ov, is_pct):>12s}"
            f"   vs naive: {rp_vs_naive}  vs rule-based: {rp_vs_smarter}"
        )

    # ── Seed spread ───────────────────────────────────────────────────────────
    section("Seed spread (unmet demand std)")
    print(f"  Naive     unmet demand std: {er_naive.unmet_demand_std:.1f}")
    print(f"  Rule-based                : {er_smarter.unmet_demand_std:.1f}")
    print(f"  RoutePulse                : {er_optimised.unmet_demand_std:.1f}")

    # ── Demand forecaster ─────────────────────────────────────────────────────
    section("Demand forecaster evaluation")
    half = n // 2
    train_seeds   = seeds[:half]
    holdout_seeds = seeds[half:]
    print(f"  Train seeds:   {train_seeds}")
    print(f"  Holdout seeds: {holdout_seeds}")
    print("  Training forecaster...")
    fc = train_forecaster(train_seeds=train_seeds, holdout_seeds=holdout_seeds)
    print(f"  Train MAE:   {fc.train_mae:.2f} pax/slot")
    print(f"  Holdout MAE: {fc.holdout_mae:.2f} pax/slot")
    print(f"  vs Naive:    {fc.improvement_pct:+.1f}% improvement")
    calibrated = "well calibrated" if fc.holdout_mae < fc.train_mae * 1.5 else "may be overfitting"
    print(f"  Assessment:  {calibrated}")

    # ── ETA calibration detail ────────────────────────────────────────────────
    section("ETA calibration detail (seed 42)")
    eta_result = evaluate_eta_over_trips(trips_42)
    print(f"  Calibration: {eta_result['eta_calibration']:.1%} (target 90%)")
    print(f"  Gap from target: {eta_result['eta_calibration_gap_pp']:+.1f} pp")
    print(f"  MAE: {eta_result['eta_mae_minutes']:.3f} min")
    print(f"  n evaluated: {eta_result['n_evaluated']:,}")
    print(f"  Well calibrated: {eta_result['eta_is_well_calibrated']}")

    # ── Report file ───────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    section(f"Done in {elapsed:.1f}s")

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report.md")
    with open(report_path, "w") as f:
        f.write(f"# RoutePulse Evaluation Report\n\n")
        f.write(f"Seeds: {seeds[0]}–{seeds[-1]} ({n} runs)  \n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
        f.write("## Three-way comparison\n\n")
        f.write(f"| Metric | Naive | Rule-based | RoutePulse | RP vs Naive | RP vs Rule-based |\n")
        f.write(f"|--------|-------|------------|------------|-------------|------------------|\n")
        for attr, label, hib in metrics:
            nv = getattr(er_naive, attr, None)
            sv = getattr(er_smarter, attr, None)
            ov = getattr(er_optimised, attr, None)
            def _md(v, is_pct=False):
                if v is None: return "N/A"
                if is_pct: return f"{v:.1%}"
                return f"{v:.2f}" if isinstance(v, float) else str(v)
            is_pct = attr in ("service_rate", "fleet_utilisation", "eta_calibration")
            rn = "↑" if (hib and ov > nv) or (not hib and ov < nv) else ("=" if ov == nv else "↓")
            rs = "↑" if (hib and ov > sv) or (not hib and ov < sv) else ("=" if ov == sv else "↓")
            f.write(f"| {label} | {_md(nv,is_pct)} | {_md(sv,is_pct)} | {_md(ov,is_pct)} | {rn} | {rs} |\n")
        f.write("\n## ETA calibration\n\n")
        f.write(f"- Calibration: {eta_result['eta_calibration']:.1%} (target 90%, gap {eta_result['eta_calibration_gap_pp']:+.1f} pp)\n")
        f.write(f"- MAE: {eta_result['eta_mae_minutes']:.3f} min\n")
        f.write(f"- n evaluated: {eta_result['n_evaluated']:,}\n\n")
        f.write("## Demand forecaster\n\n")
        f.write(f"- Train MAE: {fc.train_mae:.2f} pax/slot\n")
        f.write(f"- Holdout MAE: {fc.holdout_mae:.2f} pax/slot\n")
        f.write(f"- vs Naive: {fc.improvement_pct:+.1f}%\n")

    print(f"  Report saved to: {report_path}")


if __name__ == "__main__":
    main()
