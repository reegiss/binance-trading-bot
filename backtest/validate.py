"""Validation of the trend-following candidate (A) against HODL and the SMA200
control (B), using criteria pre-registered in
docs/superpowers/specs/2026-10-31-trend-following-validation-design.md (4.4).

Do not change the constants below after looking at results.
"""
import argparse
import itertools
import math
from datetime import date
from pathlib import Path

import pandas as pd

from . import data, metrics
from .run import to_markdown, yearly_markdown
from .trend import TrendParams, simulate, sma_regime, trend_exposure, warmup_days

# ---- pre-registered criteria (spec 4.4) -------------------------------------
C1_MAX_DD_RATIO = 0.60      # |MaxDD_A| <= 0.60 * |MaxDD_HODL|
C2_MIN_CAGR_RATIO = 0.75    # CAGR_A >= 0.75 * CAGR_HODL
C4_MIN_PASS_SHARE = 0.70    # share of grid configs passing C1 and C3
OOS_ALERT_MIN_ASSETS = 3    # out-of-sample alert threshold (diagnostic)

GRID_LOOKBACKS = ((10, 20, 50, 100), (20, 50, 100, 200), (50, 100, 200, 300))
GRID_VOL_TARGETS = (0.30, 0.40, 0.50, 0.60, 0.80, None)
GRID_BANDS = (0.0, 0.05, 0.10, 0.20)


def _ok(*values) -> bool:
    return all(v is not None and not math.isnan(v) for v in values)


def check_c1(a: dict, hodl: dict) -> bool:
    a_dd, h_dd = a["max_drawdown"], hodl["max_drawdown"]
    return _ok(a_dd, h_dd) and abs(a_dd) <= C1_MAX_DD_RATIO * abs(h_dd)


def check_c2(a: dict, hodl: dict) -> bool:
    a_cagr, h_cagr = a["cagr"], hodl["cagr"]
    if not _ok(a_cagr, h_cagr):
        return False
    if h_cagr <= 0:
        return a_cagr >= h_cagr
    return a_cagr >= C2_MIN_CAGR_RATIO * h_cagr


def check_c3(a: dict, hodl: dict, b: dict | None) -> bool:
    if not _ok(a["calmar"], hodl["calmar"]) or a["calmar"] <= hodl["calmar"]:
        return False
    if b is None:
        return True
    return _ok(b["calmar"]) and a["calmar"] > b["calmar"]


def check_c4(passes: list) -> bool:
    return len(passes) > 0 and sum(passes) / len(passes) >= C4_MIN_PASS_SHARE


def decide(a_pass: bool, b_pass: bool) -> str:
    if a_pass:
        return "integrate-A"
    return "use-B" if b_pass else "dca-hodl"


def grid_configs() -> list:
    return [TrendParams(lookbacks=lb, vol_target=vt, band=bd)
            for lb, vt, bd in itertools.product(GRID_LOOKBACKS, GRID_VOL_TARGETS, GRID_BANDS)]


# ---- orchestration (spec 4.1 - 4.5) -----------------------------------------
MAIN_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
OOS_SYMBOLS = ["LTCUSDT", "XRPUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]
SMA_WINDOW = 200
FEE, SLIPPAGE = 0.001, 0.0005
DOUBLE_FEE, DOUBLE_SLIPPAGE = 0.002, 0.002
CAPITAL = 10_000.0
RECOMMENDATION_TEXT = {
    "integrate-A": "A aprovada: abrir projeto de integração ao bot (spec própria), "
                   "depois testnet e capital pequeno.",
    "use-B": "A reprovada e B aprovada: recomendar o controle B (mais simples).",
    "dca-hodl": "A e B reprovadas: recomendar DCA/HODL e não integrar estratégia ao bot.",
}


def load_symbols(symbols, start, end, data_dir, fetch=True) -> dict:
    return {s: data.load(s, "1d", start, end, data_dir, fetch=fetch) for s in symbols}


def start_after_warmup(daily_by_symbol: dict, warm: int) -> pd.Timestamp:
    """Latest, across symbols, of the day preceded by `warm` days of history."""
    return max(df.index[warm] for df in daily_by_symbol.values())


def execution_start(daily_by_symbol: dict, params_list) -> pd.Timestamp:
    """First common execution day: every config in `params_list` and the SMA
    control have a valid target on the previous close, so all strategies and
    HODL execute at the same open."""
    warm = max(max(warmup_days(p) for p in params_list), SMA_WINDOW - 1)
    return start_after_warmup(daily_by_symbol, warm + 1)


def _with_base(equity: pd.Series, capital: float) -> pd.Series:
    """Prepend `capital` one day before the first point, so every curve is
    measured from the same base and entry costs/first-day moves count."""
    base = pd.Series([capital], index=[equity.index[0] - pd.Timedelta(days=1)])
    return pd.concat([base, equity])


def _hodl(df, start, capital, fee, slippage) -> pd.Series:
    return metrics.buy_and_hold(df[start:], capital, fee, slippage)


def run_portfolio(daily_by_symbol, target_fn, band, fee, slippage, start, capital):
    """Equal-capital independent sleeves. Returns (equity, exposure, trades) from `start`."""
    sleeve_capital = capital / len(daily_by_symbol)
    equities, weighted, trades = [], [], []
    for sym, df in daily_by_symbol.items():
        res = simulate(df, target_fn(df["close"]), sleeve_capital, band, fee, slippage,
                       trade_from=start)
        eq = res.equity[start:]
        equities.append(eq)
        weighted.append(res.exposure[start:] * eq)
        if not res.trades.empty:
            trades.append(res.trades.assign(symbol=sym))
    equity = metrics.combine(equities)
    exposure = metrics.combine(weighted) / equity
    equity = _with_base(equity, capital)
    trades_df = (pd.concat(trades, ignore_index=True) if trades else
                 pd.DataFrame(columns=["date", "side", "notional", "price", "fee", "symbol"]))
    return equity, exposure, trades_df


def hodl_portfolio(daily_by_symbol, fee, slippage, start, capital) -> pd.Series:
    sleeve = capital / len(daily_by_symbol)
    return _with_base(metrics.combine([_hodl(df, start, sleeve, fee, slippage)
                                       for df in daily_by_symbol.values()]), capital)


def dca_portfolio(daily_by_symbol, fee, slippage, start, capital) -> pd.Series:
    sleeve = capital / len(daily_by_symbol)
    return _with_base(metrics.combine([metrics.dca(df[start:], sleeve, "W-SUN", fee, slippage)
                                       for df in daily_by_symbol.values()]), capital)


def _a_fn(p):
    return lambda close: trend_exposure(close, p)


def _b_fn(close):
    return sma_regime(close, SMA_WINDOW)


def _evaluate(dfs, p, fee, slip, start, capital=CAPITAL):
    """Summaries for A (params p), B and HODL on one window and cost level."""
    a_eq, a_x, a_tr = run_portfolio(dfs, _a_fn(p), p.band, fee, slip, start, capital)
    b_eq, b_x, b_tr = run_portfolio(dfs, _b_fn, 0.0, fee, slip, start, capital)
    h_eq = hodl_portfolio(dfs, fee, slip, start, capital)
    out = {}
    for name, eq, x, tr in (("A", a_eq, a_x, a_tr), ("B", b_eq, b_x, b_tr), ("HODL", h_eq, None, None)):
        summary = metrics.summarize(eq, position=x)
        if tr is not None:
            summary["trades"] = len(tr)
            summary["costs"] = float(tr["fee"].sum() + (tr["notional"] * slip).sum()) if len(tr) else 0.0
        out[name] = {"summary": summary, "equity": eq}
    return out


def yearly_drawdown(equity: pd.Series) -> pd.Series:
    daily = equity.resample("D").last().dropna()
    return daily.groupby(daily.index.year).apply(lambda s: (s / s.cummax() - 1).min()).set_axis(
        pd.to_datetime([f"{y}-12-31" for y in daily.index.year.unique()], utc=True))


def _verdict(ok: bool) -> str:
    return "APROVADO" if ok else "REPROVADO"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trend following validation (spec 4)")
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--data-dir", type=Path, default=data.DEFAULT_DATA_DIR)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=Path(f"backtest/results/{date.today():%Y-%m-%d}-trend-validation.md"))
    args = ap.parse_args(argv)
    fetch = not args.no_fetch

    main_dfs = load_symbols(MAIN_SYMBOLS, args.start, args.end, args.data_dir, fetch)
    base = TrendParams()
    start = execution_start(main_dfs, [base])

    # 4.2.1 main test
    main_res = _evaluate(main_dfs, base, FEE, SLIPPAGE, start)
    a, b, h = (main_res[k]["summary"] for k in ("A", "B", "HODL"))
    dca_eq = dca_portfolio(main_dfs, FEE, SLIPPAGE, start, CAPITAL)
    single = {f"HODL {s[:3]}": _with_base(_hodl(main_dfs[s], start, CAPITAL, FEE, SLIPPAGE), CAPITAL)
              for s in MAIN_SYMBOLS}

    # 4.2.2 sensitivity grid
    grid = grid_configs()
    grid_start = execution_start(main_dfs, grid)
    grid_rows, grid_pass = [], []
    b_grid = h_grid = None
    for p in grid:
        res = _evaluate(main_dfs, p, FEE, SLIPPAGE, grid_start)
        ga, gb, gh = (res[k]["summary"] for k in ("A", "B", "HODL"))
        b_grid, h_grid = gb, gh
        c1, c3 = check_c1(ga, gh), check_c3(ga, gh, gb)
        grid_pass.append(c1 and c3)
        grid_rows.append(f"| {p.lookbacks} | {p.vol_target} | {p.band:.2f} | {ga['cagr']:.1%} | "
                         f"{ga['max_drawdown']:.1%} | {ga['calmar']:.2f} | {_verdict(c1)} | {_verdict(c3)} |")

    # 4.2.3 doubled costs
    dbl = _evaluate(main_dfs, base, DOUBLE_FEE, DOUBLE_SLIPPAGE, start)
    da, db, dh = (dbl[k]["summary"] for k in ("A", "B", "HODL"))

    # 4.2.4 out of sample (diagnostic)
    oos_rows, oos_bad = [], 0
    oos_dfs = load_symbols(OOS_SYMBOLS, args.start, args.end, args.data_dir, fetch)
    for sym, df in oos_dfs.items():
        s0 = execution_start({sym: df}, [base])
        oa = metrics.summarize(run_portfolio({sym: df}, _a_fn(base), base.band, FEE, SLIPPAGE, s0, CAPITAL)[0])
        oh = metrics.summarize(_with_base(_hodl(df, s0, CAPITAL, FEE, SLIPPAGE), CAPITAL))
        bad = not (oa["calmar"] >= oh["calmar"]) or abs(oa["max_drawdown"]) > abs(oh["max_drawdown"])
        oos_bad += bad
        oos_rows.append(f"| {sym} | {s0:%Y-%m-%d} | {oa['cagr']:.1%} | {oh['cagr']:.1%} | "
                        f"{oa['max_drawdown']:.1%} | {oh['max_drawdown']:.1%} | {oa['calmar']:.2f} | "
                        f"{oh['calmar']:.2f} | {'pior' if bad else 'ok'} |")
    oos_alert = oos_bad >= OOS_ALERT_MIN_ASSETS

    # 4.4 criteria
    a_checks = {
        "C1": check_c1(a, h), "C2": check_c2(a, h), "C3": check_c3(a, h, b),
        "C4": check_c4(grid_pass), "C5": check_c1(da, dh) and check_c3(da, dh, db),
    }
    b_checks = {
        "C1": check_c1(b, h), "C2": check_c2(b, h), "C3": check_c3(b, h, None),
        "C5": check_c1(db, dh) and check_c3(db, dh, None),
    }
    recommendation = decide(all(a_checks.values()), all(b_checks.values()))

    # report
    table = pd.DataFrame({
        "A (trend)": a, "B (SMA200)": b, "HODL 50/50": h,
        "DCA 50/50": metrics.summarize(dca_eq),
        **{k: metrics.summarize(v) for k, v in single.items()},
    })
    curves = {"A (trend)": main_res["A"]["equity"], "B (SMA200)": main_res["B"]["equity"],
              "HODL 50/50": main_res["HODL"]["equity"]}
    yearly_ret = pd.DataFrame({k: metrics.yearly_returns(v) for k, v in curves.items()})
    yearly_dd = pd.DataFrame({k: yearly_drawdown(v) for k, v in curves.items()})
    criteria_desc = {
        "C1": f"|MaxDD| <= {C1_MAX_DD_RATIO:.0%} do HODL",
        "C2": f"CAGR >= {C2_MIN_CAGR_RATIO:.0%} do HODL",
        "C3": "Calmar > HODL (e > B, para A)",
        "C4": f">= {C4_MIN_PASS_SHARE:.0%} da grade passa C1 e C3 ({sum(grid_pass)}/{len(grid_pass)})",
        "C5": "custos em dobro: C1 e C3",
    }
    lines = [
        "# Validação trend following — BTC/ETH spot", "",
        f"Período de dados {args.start}..{args.end}; janela principal a partir de {start:%Y-%m-%d}; "
        f"grade a partir de {grid_start:%Y-%m-%d}. Custos {FEE:.2%} + slippage {SLIPPAGE:.2%} por execução. "
        "Spec: docs/superpowers/specs/2026-10-31-trend-following-validation-design.md", "",
        "## Critérios", "", "| critério | descrição | A | B |", "|---|---|---|---|",
    ]
    for c, desc in criteria_desc.items():
        b_cell = _verdict(b_checks[c]) if c in b_checks else "-"
        lines.append(f"| {c} | {desc} | {_verdict(a_checks[c])} | {b_cell} |")
    lines += ["", f"**Recomendação:** {RECOMMENDATION_TEXT[recommendation]}", "",
              f"Calmar no teste principal: A {a['calmar']:.4f}, B {b['calmar']:.4f}, "
              f"HODL {h['calmar']:.4f}. Todas as curvas partem do capital no dia anterior "
              f"a {start:%Y-%m-%d} e executam pela primeira vez na abertura desse dia.", "",
              "## Teste principal (carteira 50/50)", "", to_markdown(table), "",
              "## Ano a ano — retorno", "", yearly_markdown(yearly_ret), "",
              "## Ano a ano — drawdown máximo no ano", "", yearly_markdown(yearly_dd), "",
              "## Custos em dobro", "",
              to_markdown(pd.DataFrame({"A (trend)": da, "B (SMA200)": db, "HODL 50/50": dh})), "",
              f"## Sensibilidade ({len(grid)} configurações, janela da grade)", "",
              f"Referências na janela da grade: HODL Calmar {h_grid['calmar']:.2f}, "
              f"MaxDD {h_grid['max_drawdown']:.1%}; B Calmar {b_grid['calmar']:.2f}.", "",
              "| lookbacks | vol_target | band | CAGR | MaxDD | Calmar | C1 | C3 |",
              "|---|---|---|---|---|---|---|---|", *grid_rows, "",
              "## Fora da amostra (diagnóstico, A padrão vs HODL do ativo)", "",
              ("**ALERTA:** " if oos_alert else "") +
              f"A ficou pior que o HODL em {oos_bad} de {len(OOS_SYMBOLS)} ativos "
              f"(limite de alerta: {OOS_ALERT_MIN_ASSETS}).", "",
              "| ativo | início | CAGR A | CAGR HODL | MaxDD A | MaxDD HODL | Calmar A | Calmar HODL | |",
              "|---|---|---|---|---|---|---|---|---|", *oos_rows, ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"recommendation: {recommendation}; criteria A={a_checks} B={b_checks}")
    print(f"report written to {args.out}")


if __name__ == "__main__":
    main()
