"""Daily trend-following strategy (candidate A) and SMA regime (control B).

Spec: docs/superpowers/specs/2026-10-31-trend-following-validation-design.md

All functions are pure (no I/O). A target computed from the close of day t
is executed at the open of day t+1.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

ANNUALIZATION = np.sqrt(365)


@dataclass(frozen=True)
class TrendParams:
    lookbacks: tuple = (20, 50, 100, 200)
    vol_window: int = 30
    vol_target: float | None = 0.50
    band: float = 0.10


def warmup_days(p: TrendParams) -> int:
    """Number of leading days for which `trend_exposure` is NaN."""
    return max(max(p.lookbacks), p.vol_window if p.vol_target is not None else 0)


def trend_exposure(close: pd.Series, p: TrendParams) -> pd.Series:
    """Target exposure in [0, 1]: mean of time-series momentum signals,
    scaled down when realised volatility exceeds `vol_target`."""
    signals = [(close > close.shift(L)).astype(float).where(close.shift(L).notna())
               for L in p.lookbacks]
    raw = pd.concat(signals, axis=1).mean(axis=1, skipna=False)
    if p.vol_target is None:
        return raw
    vol = np.log(close).diff().rolling(p.vol_window).std() * ANNUALIZATION
    scale = (p.vol_target / vol).where(vol > 0, 1.0).clip(upper=1.0).where(vol.notna())
    return raw * scale


def sma_regime(close: pd.Series, window: int = 200) -> pd.Series:
    """1.0 when close is above its `window`-day simple moving average, else 0.0."""
    sma = close.rolling(window).mean()
    return (close > sma).astype(float).where(sma.notna())


@dataclass
class TrendResult:
    equity: pd.Series     # end-of-day equity
    exposure: pd.Series   # end-of-day weight of the position in [0, 1]
    trades: pd.DataFrame  # date, side, notional, price, fee


def simulate(daily: pd.DataFrame, target: pd.Series, capital: float = 10_000.0,
             band: float = 0.0, fee: float = 0.001, slippage: float = 0.0005,
             trade_from: pd.Timestamp | None = None) -> TrendResult:
    """Trade `target[t]` at the open of day t+1 (spec 2.3)."""
    opens = daily["open"].to_numpy(dtype=float)
    closes = daily["close"].to_numpy(dtype=float)
    tgt = target.reindex(daily.index).to_numpy(dtype=float)
    dates = daily.index
    n = len(daily)
    cash, qty = float(capital), 0.0
    equity, exposure, trades = np.empty(n), np.empty(n), []

    for i in range(n):
        want = tgt[i - 1] if i > 0 else np.nan
        allowed = trade_from is None or dates[i] >= trade_from
        if not np.isnan(want) and allowed:
            px = opens[i]
            eq_open = cash + qty * px
            w = qty * px / eq_open if eq_open > 0 else 0.0
            if abs(want - w) > band or (want == 0 and w > 0):
                delta = want * eq_open - qty * px
                if delta > 0:
                    notional = min(delta, cash / (1 + fee))
                    exec_px = px * (1 + slippage)
                    qty += notional / exec_px
                    cash -= notional * (1 + fee)
                    side = "buy"
                elif delta < 0:
                    sell_qty = qty if want == 0 else min(qty, -delta / px)
                    exec_px = px * (1 - slippage)
                    notional = sell_qty * exec_px
                    qty -= sell_qty
                    cash += notional * (1 - fee)
                    side = "sell"
                else:
                    side = None
                if side is not None and notional > 0:
                    trades.append((dates[i], side, notional, exec_px, notional * fee))
        equity[i] = cash + qty * closes[i]
        exposure[i] = qty * closes[i] / equity[i] if equity[i] > 0 else 0.0

    return TrendResult(
        equity=pd.Series(equity, index=dates),
        exposure=pd.Series(exposure, index=dates),
        trades=pd.DataFrame(trades, columns=["date", "side", "notional", "price", "fee"]),
    )
