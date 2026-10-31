"""Simulation of the bot's trailing-trade strategy (single grid, default config).

Mirrors app/cronjob/trailingTrade:
  * get-indicators   lowestPrice = min low of the last `lookback_hours` 1h
                     candles (incl. the forming one); athPrice = max high of
                     the last `ath_days` 1d candles (incl. the forming one).
  * determine-action buy when price <= lowestPrice * buy_trigger, unless
                     lowestPrice * buy_trigger >= athPrice * ath_restriction.
                     sell when price >= lastBuyPrice * sell_trigger.
                     optional stop-loss: market sell at lastBuyPrice * max_loss.
  * place-*-order    STOP_LOSS_LIMIT at price*stop / price*limit.
  * handle-open-orders  cancel buy if order.stop > price*buy_limit (price fell),
                     cancel sell if order.stop < price*sell_limit (price rose);
                     the order is re-placed at the current price on the same
                     tick if the entry condition still holds. That is what
                     makes the stop "trail".

Intrabar path model: each 1m candle is replayed as the ticks
open -> low -> high -> close (green candle) or open -> high -> low -> close
(red candle) and the price is assumed continuous between ticks, so stop
orders fill exactly at their stop price (plus configurable slippage).
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

INF = float("inf")


@dataclass
class TrailingParams:
    lookback_hours: int = 100          # jobs.trailingTrade.candles (1h x 100)
    buy_trigger: float = 1.0
    buy_stop: float = 1.02
    buy_limit: float = 1.021
    sell_trigger: float = 1.06
    sell_stop: float = 0.98
    sell_limit: float = 0.979
    ath_enabled: bool = True
    ath_days: int = 30
    ath_restriction: float = 0.9
    stop_loss_enabled: bool = False
    stop_loss_max_loss: float = 0.8
    stop_loss_disable_minutes: int = 360
    # Variant (not in the bot): only open new positions when the last closed
    # daily candle is above its N-day simple moving average. 0 disables it.
    trend_filter_days: int = 0
    fee: float = 0.001                 # 0.1% per fill (Binance spot, no BNB discount)
    slippage: float = 0.0005           # adverse slippage applied to every fill


@dataclass
class Result:
    equity: pd.Series                  # bar-close equity, in quote asset
    trades: pd.DataFrame
    position: pd.Series = field(repr=False)  # 1 when holding base asset


def _indicator_arrays(df: pd.DataFrame, p: TrailingParams):
    idx = df.index
    hour = idx.floor("h")
    day = idx.floor("D")

    hourly_low = df["low"].groupby(hour).min()
    n_prev_h = p.lookback_hours - 1
    if n_prev_h > 0:
        prev_low = hourly_low.shift(1).rolling(n_prev_h, min_periods=n_prev_h).min()
    else:
        prev_low = pd.Series(INF, index=hourly_low.index)
    prev_low_bar = prev_low.reindex(hour).to_numpy(dtype=float)

    daily_high = df["high"].groupby(day).max()
    n_prev_d = p.ath_days - 1
    if not p.ath_enabled:
        prev_high = pd.Series(0.0, index=daily_high.index)
    elif n_prev_d > 0:
        prev_high = daily_high.shift(1).rolling(n_prev_d, min_periods=n_prev_d).max()
    else:
        prev_high = pd.Series(0.0, index=daily_high.index)
    prev_high_bar = prev_high.reindex(day).to_numpy(dtype=float)

    if p.trend_filter_days > 0:
        daily_close = df["close"].groupby(day).last()
        sma = daily_close.rolling(p.trend_filter_days, min_periods=p.trend_filter_days).mean()
        ok = (daily_close > sma).shift(1)  # decided on the previous closed day
        trend_ok = ok.reindex(day).fillna(False).to_numpy(dtype=bool)
        trend_ready = sma.shift(1).reindex(day).notna().to_numpy()
    else:
        trend_ok = np.ones(len(df), dtype=bool)
        trend_ready = np.ones(len(df), dtype=bool)

    ready = ~np.isnan(prev_low_bar) & ~np.isnan(prev_high_bar) & trend_ready
    hour_id = hour.asi8
    day_id = day.asi8
    return prev_low_bar, prev_high_bar, trend_ok, ready, hour_id, day_id


def warmup_end(df: pd.DataFrame, p: TrailingParams) -> pd.Timestamp:
    """First timestamp at which every indicator has enough history."""
    ready = _indicator_arrays(df, p)[3]
    pos = int(np.argmax(ready))
    if not ready[pos]:
        raise ValueError("not enough data to warm up the indicators")
    return df.index[pos]


def run(df: pd.DataFrame, p: TrailingParams = TrailingParams(),
        capital: float = 10_000.0, trade_from=None) -> Result:
    """Simulate the strategy. Orders are only placed from `trade_from`
    (and once indicators are warm), so variants can share a start date."""
    # Timestamps below are handled as int64 nanoseconds regardless of the
    # index resolution (pandas >= 2 may use ms/us units).
    df = df.set_axis(df.index.as_unit("ns"))
    prev_low_bar, prev_high_bar, trend_ok, ready, hour_id, day_id = _indicator_arrays(df, p)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    ts = df.index.asi8  # ns
    n = len(df)
    if trade_from is not None:
        ready = ready & (ts >= pd.Timestamp(trade_from).as_unit("ns").value)

    cash, qty = capital, 0.0
    last_buy = 0.0
    entry_ts, entry_cost = 0, 0.0
    order = None          # (side, stop, limit)
    disabled_until = -1   # ns timestamp; buys disabled after stop-loss
    cur_hour, cur_day = None, None
    hour_low, day_high = INF, -INF
    prev_tick = None

    equity = np.empty(n)
    holding = np.zeros(n, dtype=np.int8)
    trades = []

    fee, slip = p.fee, p.slippage

    def buy_fill(price, t):
        nonlocal cash, qty, last_buy, entry_ts, entry_cost
        fill = price * (1 + slip)
        qty = cash * (1 - fee) / fill
        entry_cost = cash
        cash = 0.0
        last_buy = fill
        entry_ts = t

    def sell_fill(price, t, reason):
        nonlocal cash, qty, last_buy
        fill = price * (1 - slip)
        proceeds = qty * fill * (1 - fee)
        trades.append((entry_ts, t, last_buy, fill, proceeds / entry_cost - 1, reason))
        cash, qty, last_buy = proceeds, 0.0, 0.0

    for i in range(n):
        if hour_id[i] != cur_hour:
            cur_hour, hour_low = hour_id[i], INF
        if day_id[i] != cur_day:
            cur_day, day_high = day_id[i], -INF
        t = ts[i]
        can_trade = ready[i]
        ticks = (o[i], l[i], h[i], c[i]) if c[i] >= o[i] else (o[i], h[i], l[i], c[i])

        for px in ticks:
            if px < hour_low:
                hour_low = px
            if px > day_high:
                day_high = px

            # 1) exchange side: stop orders fill when price crosses the stop
            if order is not None and prev_tick is not None:
                side, stop, _limit = order
                if side == "buy" and prev_tick < stop <= px:
                    buy_fill(stop, t)
                    order = None
                elif side == "sell" and prev_tick > stop >= px:
                    sell_fill(stop, t, "sell")
                    order = None
            prev_tick = px

            if not can_trade:
                continue

            # 2) bot side: handle-open-orders (cancel when price moved away)
            if order is not None:
                side, stop, limit = order
                if side == "buy" and (stop > px * p.buy_limit or px > limit):
                    order = None
                elif side == "sell" and (stop < px * p.sell_limit or px < limit):
                    order = None
            if order is not None:
                continue

            # 3) bot side: determine-action + place order
            if qty == 0.0:
                lowest = prev_low_bar[i] if prev_low_bar[i] < hour_low else hour_low
                trigger = lowest * p.buy_trigger
                if px > trigger:
                    continue
                if p.ath_enabled:
                    ath = prev_high_bar[i] if prev_high_bar[i] > day_high else day_high
                    if trigger >= ath * p.ath_restriction:
                        continue
                if t < disabled_until or not trend_ok[i]:
                    continue
                order = ("buy", px * p.buy_stop, px * p.buy_limit)
            else:
                if px >= last_buy * p.sell_trigger:
                    order = ("sell", px * p.sell_stop, px * p.sell_limit)
                elif p.stop_loss_enabled and px <= last_buy * p.stop_loss_max_loss:
                    sell_fill(px, t, "stop-loss")
                    disabled_until = t + p.stop_loss_disable_minutes * 60 * 10**9

        equity[i] = cash + qty * c[i]
        holding[i] = 1 if qty > 0 else 0

    if qty > 0:  # mark-to-market the open position at the end
        open_ret = qty * c[-1] * (1 - fee) / entry_cost - 1
        trades.append((entry_ts, None, last_buy, c[-1], open_ret, "open"))
    index = df.index
    trades_df = pd.DataFrame(
        trades, columns=["entry_time", "exit_time", "entry_price", "exit_price", "return", "reason"])
    for col in ("entry_time", "exit_time"):
        trades_df[col] = pd.to_datetime(trades_df[col], unit="ns", utc=True)
    return Result(equity=pd.Series(equity, index=index),
                  trades=trades_df,
                  position=pd.Series(holding, index=index))
