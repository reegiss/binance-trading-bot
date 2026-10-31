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
