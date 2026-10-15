"""
Demand forecaster for RoutePulse.

Uses a scikit-learn GradientBoostingRegressor trained on simulated historical
demand observations to predict passenger counts at each stop for the next
FORECAST_HORIZON_STEPS time slots.

Features:
  - Time-of-day (hour, minute, sin/cos encoding for periodicity)
  - Day-of-week (encoded as integer; synthetic data uses Tuesday=1)
  - Stop identity (one-hot via DictVectorizer)
  - Lag demand values (past N boarding counts at this stop)
  - Demand multiplier (physics-based signal used as a feature, not the label)

This forecaster supplements — but does not replace — the physics-based
demand_multiplier in data_gen.py. It learns the residual pattern from
historical simulation runs.
"""
from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import OrdinalEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error

from routepulse.config import (
    SEED, HEADWAY, FORECAST_HORIZON_STEPS, FORECAST_N_LAGS,
    FORECAST_MIN_TRAIN_SAMPLES,
)
from routepulse.data_gen import demand_multiplier


# ---------------------------------------------------------------------------
# Feature engineering helpers
# ---------------------------------------------------------------------------

def _time_features(time_min: float) -> dict:
    """Return cyclic time-of-day features from time in minutes since midnight."""
    angle_day = 2 * math.pi * time_min / (24 * 60)
    angle_headway = 2 * math.pi * time_min / (HEADWAY * 60)
    return {
        "hour": time_min / 60.0,
        "sin_day": math.sin(angle_day),
        "cos_day": math.cos(angle_day),
        "sin_hw": math.sin(angle_headway),
        "cos_hw": math.cos(angle_headway),
        "demand_mult": demand_multiplier(time_min),
    }


def _build_feature_row(
    stop_id: str,
    time_min: float,
    lag_demands: List[float],
    day_of_week: int = 1,  # Tuesday
) -> dict:
    """Assemble one feature row as a flat dict."""
    row = {"stop_id": stop_id, "day_of_week": float(day_of_week)}
    row.update(_time_features(time_min))
    # Pad lags if insufficient history
    padded = ([0.0] * FORECAST_N_LAGS + list(lag_demands))[-FORECAST_N_LAGS:]
    for i, v in enumerate(padded):
        row[f"lag_{i}"] = float(v)
    return row


# ---------------------------------------------------------------------------
# Training data builder
# ---------------------------------------------------------------------------

def build_training_data(
    simulated_trips_by_seed: Dict[int, List],
) -> pd.DataFrame:
    """
    Convert multi-seed simulation results into a tabular training dataset.

    Each row = one (stop, slot) observation with features + label.
    Label = actual boarding count at that stop in that trip.
    """
    rows = []
    for seed, trips in simulated_trips_by_seed.items():
        # Build per-stop demand history as lags within this simulation day
        stop_history: Dict[str, List[Tuple[float, int]]] = {}  # stop_id -> [(time, demand)]

        for trip in sorted(trips, key=lambda t: t.departure.departure_time):
            for ev in trip.stop_events:
                sid = ev.stop.stop_id
                t = ev.actual_arrival
                hist = stop_history.get(sid, [])
                lag_demands = [d for _, d in hist[-FORECAST_N_LAGS:]]
                row = _build_feature_row(sid, t, lag_demands)
                row["label"] = float(ev.demand_at_stop)
                row["seed"] = seed
                rows.append(row)
                hist.append((t, ev.demand_at_stop))
                stop_history[sid] = hist

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

FEATURE_COLS = (
    ["day_of_week", "hour", "sin_day", "cos_day", "sin_hw", "cos_hw", "demand_mult"]
    + [f"lag_{i}" for i in range(FORECAST_N_LAGS)]
)
CAT_COLS = ["stop_id"]


class DemandForecaster:
    """
    Gradient-boosting demand forecaster for stop-level passenger counts.

    Attributes:
        model: trained sklearn GradientBoostingRegressor pipeline
        is_fitted: True after .fit() has been called successfully
        train_mae: MAE on training data (for honest reporting)
        holdout_mae: MAE on held-out seeds (None until evaluated)
    """

    def __init__(self, n_estimators: int = 150, max_depth: int = 4, learning_rate: float = 0.08):
        self._n_estimators = n_estimators
        self._max_depth = max_depth
        self._lr = learning_rate
        self.is_fitted = False
        self.train_mae: Optional[float] = None
        self.holdout_mae: Optional[float] = None
        self._enc: Optional[OrdinalEncoder] = None
        self._model: Optional[GradientBoostingRegressor] = None

    # ── Training ─────────────────────────────────────────────────────────────

    def fit(self, df: pd.DataFrame) -> "DemandForecaster":
        """Train the forecaster on a DataFrame from build_training_data()."""
        if len(df) < FORECAST_MIN_TRAIN_SAMPLES:
            raise ValueError(
                f"Need at least {FORECAST_MIN_TRAIN_SAMPLES} samples, got {len(df)}"
            )
        X, y = self._prepare(df, fit_encoder=True)
        self._model = GradientBoostingRegressor(
            n_estimators=self._n_estimators,
            max_depth=self._max_depth,
            learning_rate=self._lr,
            random_state=SEED,
        )
        self._model.fit(X, y)
        preds = self._model.predict(X)
        self.train_mae = float(mean_absolute_error(y, preds))
        self.is_fitted = True
        return self

    def evaluate_holdout(self, df: pd.DataFrame) -> float:
        """Compute MAE on a held-out dataset and store it."""
        X, y = self._prepare(df, fit_encoder=False)
        preds = self.predict_raw(X)
        self.holdout_mae = float(mean_absolute_error(y, preds))
        return self.holdout_mae

    # ── Prediction ───────────────────────────────────────────────────────────

    def predict_raw(self, X: np.ndarray) -> np.ndarray:
        """Return raw float predictions (clip to ≥ 0)."""
        if not self.is_fitted:
            raise RuntimeError("Forecaster is not fitted. Call .fit() first.")
        return np.maximum(0.0, self._model.predict(X))

    def predict_demand(
        self,
        stop_id: str,
        time_min: float,
        lag_demands: List[float],
        day_of_week: int = 1,
    ) -> Tuple[float, float]:
        """
        Predict passenger demand at a stop.

        Returns:
            (point_estimate, uncertainty_std)
            Uncertainty is estimated as the spread of individual tree predictions.
        """
        row = _build_feature_row(stop_id, time_min, lag_demands, day_of_week)
        df_row = pd.DataFrame([row])
        X, _ = self._prepare(df_row, fit_encoder=False)
        point = float(np.maximum(0.0, self._model.predict(X)[0]))

        # Staged prediction variance as uncertainty proxy
        staged = list(self._model.staged_predict(X))
        if len(staged) > 1:
            stage_vals = np.array([s[0] for s in staged[-20:]])
            uncertainty = float(np.std(stage_vals))
        else:
            uncertainty = 1.0

        return point, uncertainty

    def predict_horizon(
        self,
        stop_id: str,
        current_time_min: float,
        lag_demands: List[float],
        day_of_week: int = 1,
    ) -> List[Tuple[float, float, float]]:
        """
        Forecast demand for the next FORECAST_HORIZON_STEPS slots.

        Returns:
            list of (slot_time_min, point_estimate, uncertainty_std)
        """
        results = []
        lags = list(lag_demands)
        t = current_time_min
        for _ in range(FORECAST_HORIZON_STEPS):
            t += HEADWAY
            pt, unc = self.predict_demand(stop_id, t, lags, day_of_week)
            results.append((t, pt, unc))
            lags.append(pt)
            lags = lags[-FORECAST_N_LAGS:]
        return results

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _prepare(
        self, df: pd.DataFrame, fit_encoder: bool
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Encode stop_id and return (X, y) arrays. y is None if label absent."""
        df = df.copy()
        if fit_encoder:
            self._enc = OrdinalEncoder(
                handle_unknown="use_encoded_value", unknown_value=-1
            )
            df["stop_id_enc"] = self._enc.fit_transform(df[["stop_id"]])
        else:
            if self._enc is None:
                raise RuntimeError("Encoder not fitted. Call fit() first.")
            df["stop_id_enc"] = self._enc.transform(df[["stop_id"]])

        num_cols = ["stop_id_enc"] + FEATURE_COLS
        # Fill any missing lag columns with 0
        for col in num_cols:
            if col not in df.columns:
                df[col] = 0.0

        X = df[num_cols].fillna(0.0).values
        y = df["label"].values if "label" in df.columns else None
        return X, y

    def feature_importances(self) -> pd.DataFrame:
        """Return a sorted DataFrame of feature importances."""
        if not self.is_fitted:
            return pd.DataFrame()
        num_cols = ["stop_id_enc"] + FEATURE_COLS
        imp = self._model.feature_importances_
        return (
            pd.DataFrame({"feature": num_cols, "importance": imp})
            .sort_values("importance", ascending=False)
            .reset_index(drop=True)
        )


# ---------------------------------------------------------------------------
# Convenience: train from scratch on multi-seed data
# ---------------------------------------------------------------------------

def train_forecaster(
    train_seeds: List[int],
    holdout_seeds: Optional[List[int]] = None,
) -> DemandForecaster:
    """
    Train the demand forecaster from scratch using multi-seed simulations.

    Args:
        train_seeds: seeds used for training
        holdout_seeds: seeds used for evaluation (optional)

    Returns:
        Fitted DemandForecaster with .train_mae and .holdout_mae populated.
    """
    from routepulse.data_gen import build_campus, build_baseline_plan
    from routepulse.simulator import simulate_plan

    stops, routes, vehicles, departures = build_campus()
    baseline = build_baseline_plan(departures=departures)

    train_trips = {s: simulate_plan(baseline, base_seed=s) for s in train_seeds}
    df_train = build_training_data(train_trips)

    forecaster = DemandForecaster()
    forecaster.fit(df_train)

    if holdout_seeds:
        holdout_trips = {s: simulate_plan(baseline, base_seed=s) for s in holdout_seeds}
        df_holdout = build_training_data(holdout_trips)
        forecaster.evaluate_holdout(df_holdout)

    return forecaster
