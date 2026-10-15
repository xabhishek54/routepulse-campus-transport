# RoutePulse Evaluation Report

Seeds: 42–52 (11 runs)  
Generated: 2026-10-15 17:46:49  

## Three-way comparison

| Metric | Naive | Rule-based | RoutePulse | RP vs Naive | RP vs Rule-based |
|--------|-------|------------|------------|-------------|------------------|
| Service rate | 44.6% | 70.5% | 46.3% | ↑ | ↓ |
| Crowded stops | 682 | 406 | 725 | ↓ | ↓ |
| Passengers left behind | 18187 | 9663 | 19161 | ↓ | ↓ |
| Missed connections | 136 | 136 | 142 | ↓ | ↓ |
| Avg wait (min) | 8.54 | 8.54 | 8.53 | ↑ | ↑ |
| Fleet utilisation | 78.4% | 61.7% | 79.1% | ↑ | ↑ |
| ETA MAE (min) | 1.50 | 1.50 | 1.51 | ↓ | ↓ |
| ETA calibration | 93.3% | 93.3% | 93.3% | = | = |
| Constraint violations | 0 | 0 | 0 | = | = |

## ETA calibration

- Calibration: 89.7% (target 90%, gap -0.3 pp)
- MAE: 1.757 min
- n evaluated: 624

## Demand forecaster

- Train MAE: 3.41 pax/slot
- Holdout MAE: 3.90 pax/slot
- vs Naive: +59.7%
