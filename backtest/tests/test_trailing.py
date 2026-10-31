import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from backtest import data, metrics, trailing

# Small windows so synthetic series stay short: lowest = last 2 hours,
# ATH = last 1 day. No fees/slippage unless a test sets them.
P = trailing.TrailingParams(lookback_hours=2, ath_days=1, fee=0.0, slippage=0.0)


def bars(prices, start="2024-01-01"):
    """Flat 1m candles (o=h=l=c) following `prices`."""
    prices = np.asarray(prices, dtype=float)
    idx = pd.date_range(start, periods=len(prices), freq="1min", tz="UTC")
    return pd.DataFrame({"open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": 1.0}, index=idx)


def path(*segments):
    """Concatenate linear segments: path((100, 120, 60), (120, 90, 30)) ..."""
    out = []
    for a, b, n in segments:
        out.extend(np.linspace(a, b, n, endpoint=False))
    return out


WARMUP = [(100, 100, 120)]  # 2h flat at 100 -> indicators ready


def test_warmup_blocks_trading():
    res = trailing.run(bars(path((100, 50, 60), (50, 50, 10))), P)
    assert res.trades.empty
    assert res.position.sum() == 0


def test_trade_from_delays_first_order():
    prices = path(*WARMUP, (100, 80, 200), (80, 85, 100), (85, 85, 10))
    df = bars(prices)
    late = trailing.run(df, P, trade_from=df.index[-1])
    assert late.trades.empty
    assert (late.equity == 10_000.0).all()


def test_buy_trails_the_low_and_fills_two_percent_above_it():
    # Drop from 100 to 80, then rebound to 85: buy stop trails to 80*1.02.
    prices = path(*WARMUP, (100, 80, 200), (80, 85, 100), (85, 85, 10))
    res = trailing.run(bars(prices), P)
    assert len(res.trades) == 1 and res.trades.iloc[0]["reason"] == "open"
    entry = res.trades.iloc[0]["entry_price"]
    # Re-placement granularity is ~0.1% (buy_limit / buy_stop), so allow it.
    assert entry == pytest.approx(80 * 1.02, rel=2e-3)


def test_no_buy_when_rebound_is_smaller_than_stop():
    prices = path(*WARMUP, (100, 80, 200), (80, 81, 100))
    res = trailing.run(bars(prices), P)
    assert res.trades.empty


def test_ath_restriction_blocks_buy_near_the_high():
    # Price drops only 5% from the daily high: trigger (95) >= 0.9 * ATH (90).
    prices = path(*WARMUP, (100, 95, 100), (95, 100, 100))
    res = trailing.run(bars(prices), P)
    assert res.trades.empty
    # Without the restriction the same path produces a buy.
    res2 = trailing.run(bars(prices), trailing.TrailingParams(**{**P.__dict__, "ath_enabled": False}))
    assert len(res2.trades) == 1


def test_sell_trails_the_high_and_closes_the_trade():
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50),  # buy at 81.6
                  (81.6, 100, 200), (100, 90, 100), (90, 90, 10))  # peak 100, sell at 98
    res = trailing.run(bars(prices), P)
    trade = res.trades.iloc[0]
    assert trade["reason"] == "sell"
    assert trade["exit_price"] == pytest.approx(100 * 0.98, rel=2e-3)
    assert trade["return"] == pytest.approx(trade["exit_price"] / trade["entry_price"] - 1, rel=1e-9)
    assert res.position.iloc[-1] == 0


def test_without_stop_loss_position_is_held_through_a_crash():
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50), (81.6, 30, 200))
    res = trailing.run(bars(prices), P)
    assert res.trades.iloc[0]["reason"] == "open"
    assert res.trades.iloc[0]["return"] < -0.6


def test_stop_loss_exits_and_disables_buys():
    params = trailing.TrailingParams(**{**P.__dict__, "stop_loss_enabled": True})
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50), (81.6, 30, 200), (30, 40, 100))
    res = trailing.run(bars(prices), params)
    first = res.trades.iloc[0]
    assert first["reason"] == "stop-loss"
    assert first["exit_price"] == pytest.approx(first["entry_price"] * 0.8, rel=1e-2)
    # Rebound to 40 happens within the 360-minute cool-down: no new entry.
    assert len(res.trades) == 1


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_stop_loss_cooldown_is_independent_of_index_resolution(unit):
    params = trailing.TrailingParams(**{**P.__dict__, "stop_loss_enabled": True,
                                        "stop_loss_disable_minutes": 60})
    # Crash -> stop-loss, then a second dip/rebound 3h later must be bought.
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50), (81.6, 30, 200),
                  (30, 30, 180), (30, 20, 100), (20, 21, 50))
    df = bars(prices)
    df = df.set_axis(df.index.as_unit(unit))
    res = trailing.run(df, params)
    assert list(res.trades["reason"]) == ["stop-loss", "open"]
    first, second = res.trades.iloc[0], res.trades.iloc[1]
    assert first["entry_time"] == df.index[370]          # crossed 80 * 1.02
    assert second["entry_time"] - first["exit_time"] >= pd.Timedelta(minutes=60)
    assert second["entry_time"] <= df.index[-1]


def test_fees_and_slippage_reduce_round_trip_return():
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50),
                  (81.6, 100, 200), (100, 90, 100), (90, 90, 10))
    gross = trailing.run(bars(prices), P).trades.iloc[0]["return"]
    params = trailing.TrailingParams(**{**P.__dict__, "fee": 0.001, "slippage": 0.0005})
    net = trailing.run(bars(prices), params).trades.iloc[0]["return"]
    expected = (1 + gross) * (1 - 0.001) ** 2 * (1 - 0.0005) / (1 + 0.0005) - 1
    assert net == pytest.approx(expected, rel=1e-9)


def test_equity_is_conserved_when_flat():
    prices = path(*WARMUP, (100, 101, 60))
    res = trailing.run(bars(prices), P, capital=1234.0)
    assert (res.equity == 1234.0).all()


def test_trend_filter_blocks_entries_in_a_downtrend():
    # 12 days falling with small intraday dips; SMA(5) filter on daily closes.
    days = 12
    prices = []
    for d in range(days):
        base = 100 * (0.97 ** d)
        prices += path((base, base * 0.85, 600), (base * 0.85, base * 0.97, 840))
    df = bars(prices)
    plain = trailing.run(df, trailing.TrailingParams(**{**P.__dict__, "ath_enabled": False}))
    filtered = trailing.run(df, trailing.TrailingParams(
        **{**P.__dict__, "ath_enabled": False, "trend_filter_days": 5}))
    assert len(plain.trades) > 0
    assert len(filtered.trades) == 0


def test_buy_and_hold_and_dca_benchmarks():
    df = bars(np.linspace(100, 200, 60 * 24 * 14))  # two weeks, doubles
    bh = metrics.buy_and_hold(df, 1000.0, fee=0.0, slippage=0.0)
    assert bh.iloc[-1] == pytest.approx(1000.0 * df["close"].iloc[-1] / 100, rel=1e-9)
    d = metrics.dca(df, 1000.0, fee=0.0, slippage=0.0)
    assert d.iloc[0] == pytest.approx(1000.0)
    assert 1000.0 < d.iloc[-1] < bh.iloc[-1]


def test_summary_handles_closed_and_open_trades():
    prices = path(*WARMUP, (100, 80, 200), (80, 81.6, 50), (81.6, 100, 200), (100, 90, 100),
                  (90, 70, 200), (70, 71.4, 50), (71.4, 60, 100))
    res = trailing.run(bars(prices), P)
    assert list(res.trades["reason"]) == ["sell", "open"]
    assert str(res.trades["exit_time"].dtype).startswith("datetime64")
    s = metrics.summarize(res.equity, res.trades, res.position)
    assert s["trades"] == 1 and s["win_rate"] == 1.0
    assert s["open_position_return"] < 0
    assert s["longest_trade_days"] >= 0


def test_summary_metrics_on_known_series():
    idx = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    eq = pd.Series([100.0, 50.0, 100.0], index=idx)
    s = metrics.summarize(eq)
    assert s["total_return"] == pytest.approx(0.0)
    assert s["max_drawdown"] == pytest.approx(-0.5)


def test_read_zip_handles_millisecond_and_microsecond_timestamps(tmp_path):
    ms = 1704067200000          # 2024-01-01 00:00 UTC
    us = 1735689600000000       # 2025-01-01 00:00 UTC (new archive format)
    rows = [f"{ms},1,2,0.5,1.5,10,{ms + 59999},0,0,0,0,0",
            f"{us},1,2,0.5,1.5,10,{us + 59999999},0,0,0,0,0"]
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("x.csv", "\n".join(rows))
    df = data.read_zip(p)
    assert list(df.index) == [pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")]
    assert df["high"].tolist() == [2.0, 2.0]
