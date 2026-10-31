"""Benchmarks (buy & hold, DCA) and performance metrics."""
import numpy as np
import pandas as pd


def buy_and_hold(df: pd.DataFrame, capital: float = 10_000.0,
                 fee: float = 0.001, slippage: float = 0.0005) -> pd.Series:
    price = df["open"].iloc[0] * (1 + slippage)
    qty = capital * (1 - fee) / price
    return qty * df["close"]


def dca(df: pd.DataFrame, capital: float = 10_000.0, freq: str = "W-SUN",
        fee: float = 0.001, slippage: float = 0.0005) -> pd.Series:
    """Invest `capital` in equal slices at the first bar of each period
    (default: weekly periods ending on Sunday, i.e. buy every Monday 00:00 UTC)."""
    periods = df.index.tz_convert(None).to_period(freq)
    first_bar = ~pd.Series(periods, index=df.index).duplicated()
    buy_idx = np.flatnonzero(first_bar.to_numpy())
    slice_ = capital / len(buy_idx)
    opens = df["open"].to_numpy()
    bought = np.zeros(len(df))
    bought[buy_idx] = slice_ * (1 - fee) / (opens[buy_idx] * (1 + slippage))
    qty = np.cumsum(bought)
    spent = np.cumsum(np.where(first_bar.to_numpy(), slice_, 0.0))
    return pd.Series(capital - spent + qty * df["close"].to_numpy(), index=df.index)


def summarize(equity: pd.Series, trades: pd.DataFrame = None,
              position: pd.Series = None) -> dict:
    daily = equity.resample("D").last().dropna()
    rets = daily.pct_change().dropna()
    years = (daily.index[-1] - daily.index[0]).days / 365.25
    total = daily.iloc[-1] / daily.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else np.nan
    dd = daily / daily.cummax() - 1
    max_dd = dd.min()
    vol = rets.std() * np.sqrt(365)
    sharpe = rets.mean() / rets.std() * np.sqrt(365) if rets.std() > 0 else np.nan
    out = {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "volatility": vol,
        "sharpe": sharpe,
        "calmar": cagr / abs(max_dd) if max_dd < 0 else np.nan,
    }
    if position is not None:
        out["time_in_market"] = position.mean()
    if trades is not None:
        closed = trades[trades["reason"] != "open"]
        out["trades"] = len(closed)
        out["win_rate"] = (closed["return"] > 0).mean() if len(closed) else np.nan
        out["avg_trade"] = closed["return"].mean() if len(closed) else np.nan
        out["worst_trade"] = trades["return"].min() if len(trades) else np.nan
        if len(trades):
            end = trades["exit_time"].fillna(equity.index[-1])
            out["longest_trade_days"] = (end - trades["entry_time"]).dt.days.max()
        else:
            out["longest_trade_days"] = np.nan
        out["open_position_return"] = (
            trades.loc[trades["reason"] == "open", "return"].iloc[0]
            if (trades["reason"] == "open").any() else np.nan)
    return out


def yearly_returns(equity: pd.Series) -> pd.Series:
    yearly = equity.resample("YE").last()
    first = equity.iloc[0]
    return yearly.pct_change().fillna(yearly.iloc[0] / first - 1)
