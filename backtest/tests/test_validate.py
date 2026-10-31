import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from backtest import validate

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


# ---- orchestration ---------------------------------------------------------

def write_daily_zips(root, symbol, start, end, seed):
    """Random-walk 1d klines in Binance archive format under root/symbol/1d/."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D", tz="UTC")
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.04, len(days))))
    open_ = np.r_[100.0, close[:-1]]
    target = root / symbol / "1d"
    target.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"open": open_, "close": close}, index=days)
    for month, g in frame.groupby(days.strftime("%Y-%m")):
        rows = []
        for d, r in g.iterrows():
            ms = d.value // 10**6
            hi, lo = max(r.open, r.close) * 1.01, min(r.open, r.close) * 0.99
            rows.append(f"{ms},{r.open},{hi},{lo},{r.close},1,{ms + 86_399_999},0,0,0,0,0")
        with zipfile.ZipFile(target / f"{symbol}-1d-{month}.zip", "w") as zf:
            zf.writestr("x.csv", "\n".join(rows))


def daily_frame(n, start="2020-01-01", price=100.0):
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": price, "high": price, "low": price, "close": price,
                         "volume": 1.0}, index=idx)


def test_run_portfolio_splits_capital_equally():
    dfs = {"A": daily_frame(10), "B": daily_frame(10, price=5.0)}
    start = dfs["A"].index[2]
    eq, expo, trades = validate.run_portfolio(
        dfs, lambda c: pd.Series(0.0, index=c.index), band=0.0, fee=0.001, slippage=0.0,
        start=start, capital=1000.0)
    assert eq.index[0] == start - pd.Timedelta(days=1)    # base point: capital before start
    assert eq.index[1] == start and (eq == 1000.0).all()
    assert (expo == 0).all() and trades.empty


def test_run_portfolio_full_exposure_matches_sleeves():
    dfs = {"A": daily_frame(5), "B": daily_frame(5)}
    eq, expo, trades = validate.run_portfolio(
        dfs, lambda c: pd.Series(1.0, index=c.index), band=0.0, fee=0.0, slippage=0.0,
        start=dfs["A"].index[0], capital=1000.0)
    assert eq.iloc[-1] == pytest.approx(1000.0)
    assert expo.iloc[-1] == pytest.approx(1.0) and len(trades) == 2


def test_start_after_warmup_is_latest_across_symbols():
    dfs = {"A": daily_frame(400), "B": daily_frame(300, start="2020-03-01")}
    assert validate.start_after_warmup(dfs, 200) == dfs["B"].index[200]


def test_late_listed_asset_starts_at_own_warmup(tmp_path):    # Review Focus 4
    write_daily_zips(tmp_path, "SOLUSDT", "2019-07-01", "2021-12-31", seed=7)
    df = validate.load_symbols(["SOLUSDT"], "2019-01", "2021-12", tmp_path, fetch=False)["SOLUSDT"]
    assert df.index[0] == pd.Timestamp("2019-07-01", tz="UTC")
    assert validate.start_after_warmup({"SOLUSDT": df}, 200) == df.index[200]


def test_main_end_to_end_on_synthetic_data(tmp_path):
    for i, sym in enumerate(validate.MAIN_SYMBOLS + validate.OOS_SYMBOLS):
        start = "2019-07-01" if sym == "SOLUSDT" else "2019-01-01"
        write_daily_zips(tmp_path, sym, start, "2021-12-31", seed=i)
    out = tmp_path / "r.md"
    validate.main(["--start", "2019-01", "--end", "2021-12", "--no-fetch",
                   "--data-dir", str(tmp_path), "--out", str(out)])
    text = out.read_text()
    for key in ["C1", "C2", "C3", "C4", "C5", "Recomendação", "SOLUSDT", "Ano a ano"]:
        assert key in text
    assert text.count("APROVADO") + text.count("REPROVADO") >= 9
    assert text.count("\n| (") >= 72          # one grid row per configuration


# ---- common base & execution day (final review finding #1/#2) --------------

def trending_frames(n=420, seed=3):
    rng = np.random.default_rng(seed)
    out = {}
    for i, sym in enumerate(["A", "B"]):
        close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, n)))
        idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
        out[sym] = pd.DataFrame({"open": np.r_[100.0, close[:-1]], "high": close, "low": close,
                                 "close": close, "volume": 1.0}, index=idx)
    return out


def test_hodl_doubled_costs_change_metrics():
    dfs = trending_frames()
    start = dfs["A"].index[10]
    base = metrics.summarize(validate.hodl_portfolio(dfs, 0.001, 0.0005, start, 1000.0))
    dbl = metrics.summarize(validate.hodl_portfolio(dfs, 0.002, 0.002, start, 1000.0))
    assert dbl["total_return"] < base["total_return"]


def test_full_exposure_strategy_matches_hodl_including_entry_costs():
    dfs = trending_frames()
    start = dfs["A"].index[10]
    eq, _, _ = validate.run_portfolio(dfs, lambda c: pd.Series(1.0, index=c.index), band=0.0,
                                      fee=0.001, slippage=0.0005, start=start, capital=1000.0)
    hodl = validate.hodl_portfolio(dfs, 0.001, 0.0005, start, 1000.0)
    pd.testing.assert_series_equal(eq, hodl, check_names=False)


def test_every_config_and_control_first_trades_on_execution_start():
    dfs = trending_frames()
    configs = [TrendParams(lookbacks=(10, 20, 50, 100)), TrendParams(lookbacks=(50, 100, 200, 300))]
    start = validate.execution_start(dfs, configs)
    for p in configs:
        _, _, tr = validate.run_portfolio(dfs, validate._a_fn(p), 0.0, 0.0, 0.0, start, 1000.0)
        assert tr["date"].min() == start
    _, _, tr = validate.run_portfolio(dfs, validate._b_fn, 0.0, 0.0, 0.0, start, 1000.0)
    assert tr["date"].min() == start
