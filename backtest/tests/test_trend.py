import numpy as np
import pandas as pd
import pytest

from backtest.trend import TrendParams, sma_regime, trend_exposure, warmup_days


def daily(prices, start="2020-01-01"):
    prices = np.asarray(prices, dtype=float)
    idx = pd.date_range(start, periods=len(prices), freq="D", tz="UTC")
    return pd.Series(prices, index=idx)


# ---- signals ---------------------------------------------------------------

def test_rising_series_full_exposure_without_vol_control():
    e = trend_exposure(daily([1, 2, 3, 4, 5]), TrendParams(lookbacks=(2, 3), vol_target=None))
    assert e.isna().tolist() == [True, True, True, False, False]
    assert e.dropna().tolist() == [1.0, 1.0]


def test_falling_series_zero_exposure():
    e = trend_exposure(daily([5, 4, 3, 2, 1]), TrendParams(lookbacks=(2, 3), vol_target=None))
    assert e.isna().tolist() == [True, True, True, False, False]
    assert e.dropna().tolist() == [0.0, 0.0]


def test_half_of_signals_positive():
    # close[t]=4 > close[t-2]=2 but < close[t-4]=10
    e = trend_exposure(daily([10, 1, 2, 3, 4]), TrendParams(lookbacks=(2, 4), vol_target=None))
    assert e.iloc[-1] == 0.5


def test_vol_scaling_matches_formula():
    r = 0.05
    log_rets = [-r, r] * 4                       # last move is up -> raw = 1 with lookback 1
    close = daily(np.exp(np.concatenate([[0.0], np.cumsum(log_rets)])))
    e = trend_exposure(close, TrendParams(lookbacks=(1,), vol_window=4, vol_target=0.5))
    expected_vol = np.std([-r, r, -r, r], ddof=1) * np.sqrt(365)
    assert e.iloc[-1] == pytest.approx(1.0 * min(1.0, 0.5 / expected_vol))
    assert e.iloc[-1] < 1.0                      # scaling actually applied


def test_low_vol_is_capped_at_full_exposure():
    close = daily(np.exp(np.cumsum([0.0] + [0.001] * 10)))
    e = trend_exposure(close, TrendParams(lookbacks=(1,), vol_window=4, vol_target=0.5))
    assert e.dropna().eq(1.0).all()


def test_constant_price_has_scale_one():         # Review Focus 1: vol == 0
    e = trend_exposure(daily([5.0] * 10), TrendParams(lookbacks=(2,), vol_window=3, vol_target=0.5))
    assert e.iloc[:3].isna().all()
    assert e.iloc[3:].notna().all() and (e.iloc[3:] == 0.0).all()


def test_no_lookahead():
    rng = np.random.default_rng(0)
    close = daily(np.exp(np.cumsum(rng.normal(0, 0.03, 300))))
    full = trend_exposure(close, TrendParams())
    cut = trend_exposure(close.iloc[:250], TrendParams())
    pd.testing.assert_series_equal(full.iloc[:250], cut)


def test_warmup_days_counts_leading_nans():
    p = TrendParams()
    close = daily(np.linspace(1, 50, 300))
    e = trend_exposure(close, p)
    assert warmup_days(p) == 200
    assert e.iloc[:200].isna().all() and e.iloc[200:].notna().all()
    assert warmup_days(TrendParams(lookbacks=(5,), vol_window=30)) == 30
    assert warmup_days(TrendParams(lookbacks=(5,), vol_window=30, vol_target=None)) == 5


def test_sma_regime_values():
    s = sma_regime(daily([1, 2, 3, 1, 5]), window=3)
    assert s.iloc[:2].isna().all()
    assert s.iloc[2:].tolist() == [1.0, 0.0, 1.0]
