"""CLI: backtest the bot's trailing strategy against buy & hold and DCA.

Example:
    python -m backtest.run --symbols BTCUSDT ETHUSDT --start 2019-01 --end 2026-09
"""
import argparse
from dataclasses import replace
from pathlib import Path

import pandas as pd

from . import data, metrics, trailing

PCT = {"total_return", "cagr", "max_drawdown", "volatility", "time_in_market",
       "win_rate", "avg_trade", "worst_trade", "open_position_return"}


def _fmt(key, value):
    if pd.isna(value):
        return "-"
    if key in PCT:
        return f"{value * 100:.1f}%"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def variants(base: trailing.TrailingParams, names):
    table = {
        "bot-default": base,
        "bot+stoploss": replace(base, stop_loss_enabled=True),
        "bot+trend200": replace(base, trend_filter_days=200),
        "bot+trend200+stoploss": replace(base, trend_filter_days=200, stop_loss_enabled=True),
    }
    return {k: table[k] for k in names}


def backtest_symbol(df, params_by_name, capital):
    # Common start for every strategy: after the longest warm-up.
    start = max(trailing.warmup_end(df, p) for p in params_by_name.values())
    rows, yearly = {}, {}
    for name, p in params_by_name.items():
        res = trailing.run(df, p, capital, trade_from=start)
        eq = res.equity[start:]
        eq = eq / eq.iloc[0] * capital
        rows[name] = metrics.summarize(eq, res.trades, res.position[start:])
        yearly[name] = metrics.yearly_returns(eq)
    sliced = df[start:]
    fee, slip = next(iter(params_by_name.values())).fee, next(iter(params_by_name.values())).slippage
    for name, eq in (("buy&hold", metrics.buy_and_hold(sliced, capital, fee, slip)),
                     ("dca-weekly", metrics.dca(sliced, capital, "W-SUN", fee, slip))):
        rows[name] = metrics.summarize(eq)
        yearly[name] = metrics.yearly_returns(eq)
    return start, pd.DataFrame(rows), pd.DataFrame(yearly)


def to_markdown(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for key, row in df.iterrows():
        lines.append(f"| {key} | " + " | ".join(_fmt(key, v) for v in row) + " |")
    return "\n".join(lines)


def yearly_markdown(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| year | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for ts, row in df.iterrows():
        lines.append(f"| {ts.year} | " + " | ".join(f"{v * 100:.1f}%" for v in row) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    ap.add_argument("--start", default="2019-01", help="first month (YYYY-MM), includes warm-up")
    ap.add_argument("--end", default="2026-09", help="last month (YYYY-MM)")
    ap.add_argument("--interval", default="1m")
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--slippage", type=float, default=0.0005)
    ap.add_argument("--variants", nargs="+",
                    default=["bot-default", "bot+stoploss", "bot+trend200", "bot+trend200+stoploss"])
    ap.add_argument("--no-fetch", action="store_true", help="use cached files only")
    ap.add_argument("--data-dir", type=Path, default=data.DEFAULT_DATA_DIR)
    ap.add_argument("--report", type=Path, default=Path("backtest/report.md"))
    args = ap.parse_args(argv)

    base = trailing.TrailingParams(fee=args.fee, slippage=args.slippage)
    params = variants(base, args.variants)
    out = [f"# Backtest report\n\nPeriod: {args.start} .. {args.end}, interval {args.interval}, "
           f"fee {args.fee:.3%}/fill, slippage {args.slippage:.3%}/fill, capital {args.capital:,.0f}\n"]
    for sym in args.symbols:
        df = data.load(sym, args.interval, args.start, args.end, args.data_dir, fetch=not args.no_fetch)
        start, summary, yearly = backtest_symbol(df, params, args.capital)
        block = (f"## {sym} (from {start:%Y-%m-%d})\n\n{to_markdown(summary)}\n\n"
                 f"### Yearly returns\n\n{yearly_markdown(yearly)}\n")
        print(block)
        out.append(block)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(out))
    print(f"report written to {args.report}")


if __name__ == "__main__":
    main()
