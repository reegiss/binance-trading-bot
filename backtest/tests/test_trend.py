import numpy as np
import pandas as pd
import pytest

from backtest.trend import TrendParams, simulate, sma_regime, trend_exposure, warmup_days


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


# ---- simulation ------------------------------------------------------------

def ohlc(opens, closes=None):
    opens = np.asarray(opens, dtype=float)
    closes = opens if closes is None else np.asarray(closes, dtype=float)
    idx = pd.date_range("2020-01-01", periods=len(opens), freq="D", tz="UTC")
    return pd.DataFrame({"open": opens, "close": closes}, index=idx)


def series_like(df, values):
    return pd.Series(np.asarray(values, dtype=float), index=df.index)


def test_full_exposure_equals_buy_and_hold_minus_costs():
    df = ohlc([100, 110, 120, 130], [105, 115, 125, 135])
    r = simulate(df, series_like(df, [1, 1, 1, 1]), capital=1000, fee=0.001, slippage=0.0005)
    qty = 1000 / (1 + 0.001) / (110 * 1.0005)          # executed at the open of day 2
    assert r.equity.iloc[0] == 1000
    assert r.equity.iloc[-1] == pytest.approx(qty * 135)
    assert len(r.trades) == 1


def test_zero_exposure_keeps_capital_constant():
    df = ohlc([100, 50, 200, 10])
    r = simulate(df, series_like(df, [0, 0, 0, 0]), capital=1000)
    assert (r.equity == 1000).all() and r.trades.empty and (r.exposure == 0).all()


def test_executes_on_next_open_only():
    df = ohlc([100, 101, 102, 103, 104], [100.5, 101.5, 102.5, 103.5, 104.5])
    r = simulate(df, series_like(df, [0, 1, 1, 1, 1]), slippage=0.001)
    trade = r.trades.iloc[0]
    assert trade["date"] == df.index[2] and trade["side"] == "buy"
    assert trade["price"] == pytest.approx(102 * 1.001)
    assert r.exposure.iloc[1] == 0


def test_band_blocks_small_changes():
    df = ohlc([100] * 5)
    r = simulate(df, series_like(df, [0.50, 0.55, 0.58, 0.58, 0.58]), band=0.10, fee=0, slippage=0)
    assert len(r.trades) == 1
    assert r.exposure.iloc[-1] == pytest.approx(0.50)


def test_target_zero_always_exits():
    # buy 20%, price drops 80% -> weight ~0.048; target 0.05 is within the band
    # (no trade), then target 0 must exit even though |0 - 0.048| < band
    df = ohlc([100, 100, 20, 20, 20, 20])
    r = simulate(df, series_like(df, [0.2, 0.05, 0.05, 0, 0, 0]), band=0.10, fee=0, slippage=0)
    assert r.trades["date"].tolist() == [df.index[1], df.index[4]]
    assert list(r.trades["side"]) == ["buy", "sell"]
    assert r.exposure.iloc[-1] == 0


def test_cash_never_negative():                        # Review Focus 2
    rng = np.random.default_rng(1)
    df = ohlc(100 * np.exp(np.cumsum(rng.normal(0, 0.05, 60))))
    r = simulate(df, series_like(df, np.tile([0, 1], 30)), fee=0.002, slippage=0.002)
    cash = r.equity * (1 - r.exposure)
    assert (cash >= -1e-9).all()
    assert len(r.trades) > 50


def test_last_day_target_is_ignored():                 # Review Focus 3
    df = ohlc([100, 100, 100])
    r = simulate(df, series_like(df, [0, 0, 1]))
    assert r.trades.empty and (r.equity == 10_000).all()


def test_nan_target_means_no_trade():
    df = ohlc([100, 100, 100, 100])
    r = simulate(df, series_like(df, [np.nan, np.nan, 1, 1]), fee=0, slippage=0)
    assert r.trades["date"].tolist() == [df.index[3]]


def test_fees_recorded():
    rng = np.random.default_rng(2)
    df = ohlc(100 * np.exp(np.cumsum(rng.normal(0, 0.05, 40))))
    r = simulate(df, series_like(df, np.tile([0, 1, 0.5, 0], 10)), fee=0.001, slippage=0.0005)
    assert len(r.trades) > 10
    assert r.trades["fee"].sum() == pytest.approx((r.trades["notional"] * 0.001).sum())
    assert set(r.trades.columns) == {"date", "side", "notional", "price", "fee"}


def test_trade_from_delays_first_trade():
    df = ohlc([100] * 6)
    r = simulate(df, series_like(df, [1] * 6), trade_from=df.index[4])
    assert r.trades["date"].tolist() == [df.index[4]]
