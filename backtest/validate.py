"""Validation of the trend-following candidate (A) against HODL and the SMA200
control (B), using criteria pre-registered in
docs/superpowers/specs/2026-10-31-trend-following-validation-design.md (4.4).

Do not change the constants below after looking at results.
"""
import itertools
import math

from .trend import TrendParams

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
