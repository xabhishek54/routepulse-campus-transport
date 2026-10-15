"""
Tests for routepulse.forecaster (ML demand forecaster).
"""
import pytest


def test_forecaster_trains_and_predicts():
    from routepulse.forecaster import train_forecaster
    fc = train_forecaster(train_seeds=[42, 43], holdout_seeds=[44])
    assert fc.is_fitted
    assert fc.train_mae is not None
    assert fc.train_mae >= 0.0
    assert fc.holdout_mae is not None
    assert fc.holdout_mae >= 0.0


def test_predict_demand_returns_tuple():
    from routepulse.forecaster import train_forecaster
    fc = train_forecaster(train_seeds=[42, 43])
    point, unc = fc.predict_demand("S1", 9 * 60, [3.0, 4.0, 2.5, 3.5, 2.0, 3.0, 4.0, 2.5])
    assert point >= 0.0
    assert unc >= 0.0


def test_horizon_forecast_length():
    from routepulse.forecaster import train_forecaster
    from routepulse.config import FORECAST_HORIZON_STEPS
    fc = train_forecaster(train_seeds=[42, 43])
    results = fc.predict_horizon("S3", 10 * 60, [4.0] * 8)
    assert len(results) == FORECAST_HORIZON_STEPS


def test_feature_importances():
    from routepulse.forecaster import train_forecaster
    fc = train_forecaster(train_seeds=[42, 43])
    fi = fc.feature_importances()
    assert not fi.empty
    assert "feature" in fi.columns
    assert "importance" in fi.columns


def test_holdout_mae_not_insane():
    """Holdout MAE should be within a reasonable multiplier of train MAE (no extreme overfit)."""
    from routepulse.forecaster import train_forecaster
    fc = train_forecaster(train_seeds=[42, 43, 44, 45], holdout_seeds=[46, 47])
    assert fc.holdout_mae < fc.train_mae * 5.0, (
        f"Extreme overfit: holdout MAE {fc.holdout_mae:.2f} >> train MAE {fc.train_mae:.2f}"
    )
