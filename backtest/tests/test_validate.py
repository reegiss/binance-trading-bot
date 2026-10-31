import pandas as pd
import pytest

from backtest import metrics
from backtest.trend import TrendParams
from backtest.validate import (C1_MAX_DD_RATIO, C2_MIN_CAGR_RATIO, C4_MIN_PASS_SHARE,
                               OOS_ALERT_MIN_ASSETS, check_c1, check_c2, check_c3,
                               check_c4, decide, grid_configs)

H = {"cagr": 0.40, "max_drawdown": -0.80, "calmar": 0.50}
NAN = float("nan")


def test_preregistered_constants():
    assert (C1_MAX_DD_RATIO, C2_MIN_CAGR_RATIO, C4_MIN_PASS_SHARE, OOS_ALERT_MIN_ASSETS) == \
        (0.60, 0.75, 0.70, 3)


def test_c1_boundary():
    assert check_c1({"max_drawdown": -0.479}, H) is True    # limit 0.60 * 0.80 = 0.48
    assert check_c1({"max_drawdown": -0.481}, H) is False


def test_c2_boundary_and_negative_hodl():
    assert check_c2({"cagr": 0.301}, H) is True              # limit 0.75 * 0.40 = 0.30
    assert check_c2({"cagr": 0.299}, H) is False
    assert check_c2({"cagr": -0.05}, {"cagr": -0.10}) is True
    assert check_c2({"cagr": -0.11}, {"cagr": -0.10}) is False


def test_c3_requires_beating_both():
    assert check_c3({"calmar": 0.6}, H, {"calmar": 0.55}) is True
    assert check_c3({"calmar": 0.6}, H, {"calmar": 0.70}) is False
    assert check_c3({"calmar": 0.4}, H, {"calmar": 0.10}) is False
    assert check_c3({"calmar": 0.6}, H, None) is True


def test_c4_threshold():
    assert check_c4([True] * 51 + [False] * 21) is True
    assert check_c4([True] * 50 + [False] * 22) is False


def test_nan_metrics_fail():                             # Review Focus 5
    nan = {"cagr": NAN, "max_drawdown": NAN, "calmar": NAN}
    assert check_c1(nan, H) is False
    assert check_c2(nan, H) is False
    assert check_c3(nan, H, None) is False
    assert check_c2({"cagr": 0.1}, {"cagr": NAN}) is False


def test_decide():
    assert decide(True, True) == "integrate-A"
    assert decide(True, False) == "integrate-A"
    assert decide(False, True) == "use-B"
    assert decide(False, False) == "dca-hodl"


def test_grid_has_72_unique_configs():
    grid = grid_configs()
    assert len(grid) == 72 and len(set(grid)) == 72
    assert all(isinstance(p, TrendParams) for p in grid)
    assert {p.lookbacks for p in grid} == {(10, 20, 50, 100), (20, 50, 100, 200), (50, 100, 200, 300)}
    assert {p.vol_target for p in grid} == {0.30, 0.40, 0.50, 0.60, 0.80, None}
    assert {p.band for p in grid} == {0.0, 0.05, 0.10, 0.20}
    assert TrendParams() in grid


def test_combine_sums_and_rejects_misaligned():
    idx = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
    a, b = pd.Series([1.0, 2.0, 3.0], index=idx), pd.Series([10.0, 20.0, 30.0], index=idx)
    assert metrics.combine([a, b]).tolist() == [11.0, 22.0, 33.0]
    with pytest.raises(ValueError):
        metrics.combine([a, b.iloc[1:]])
