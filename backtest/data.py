"""Download and load historical spot klines from data.binance.vision.

Files are the official monthly archives (one zip per symbol/interval/month),
verified against the published SHA256 checksum and cached on disk.
"""
import hashlib
import io
import os
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

BASE_URL = "https://data.binance.vision/data/spot/monthly/klines"
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"

class MissingDataError(Exception):
    """Requested data is missing inside the series (never silently filled)."""


COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _months(start: str, end: str):
    """Yield 'YYYY-MM' strings from start to end inclusive."""
    for p in pd.period_range(start=start, end=end, freq="M"):
        yield p.strftime("%Y-%m")


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 (fixed https host)
        return resp.read()


def download(symbol: str, interval: str, start: str, end: str,
             data_dir: Path = DEFAULT_DATA_DIR) -> list:
    """Download monthly kline zips (skipping cached ones). Returns local paths.

    Months before the first available one (symbol not listed yet) are skipped;
    a missing month after that raises MissingDataError.
    """
    target = Path(data_dir) / symbol / interval
    target.mkdir(parents=True, exist_ok=True)
    paths = []
    for month in _months(start, end):
        name = f"{symbol}-{interval}-{month}.zip"
        path = target / name
        if not path.exists():
            url = f"{BASE_URL}/{symbol}/{interval}/{name}"
            try:
                payload = _fetch(url)
            except urllib.error.HTTPError as err:
                if err.code != 404:
                    raise
                if paths:
                    raise MissingDataError(f"{name} missing") from err
                continue
            expected = _fetch(url + ".CHECKSUM").decode().split()[0]
            actual = hashlib.sha256(payload).hexdigest()
            if actual != expected:
                raise ValueError(f"checksum mismatch for {name}: {actual} != {expected}")
            tmp = path.with_suffix(".part")
            tmp.write_bytes(payload)
            os.replace(tmp, path)
        paths.append(path)
    if not paths:
        raise MissingDataError(f"no data for {symbol} {interval} {start}..{end}")
    return paths


def _to_utc(ts: pd.Series) -> pd.DatetimeIndex:
    # Binance switched spot archives from milliseconds to microseconds in 2025.
    ts = ts.astype("int64")
    unit_us = ts > 10**14
    ms = ts.where(~unit_us, ts // 1000)
    return pd.DatetimeIndex(pd.to_datetime(ms, unit="ms", utc=True)).as_unit("ns")


def read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            raw = fh.read()
    df = pd.read_csv(io.BytesIO(raw), header=None, names=COLUMNS)
    # Some archives ship a header row; drop it if present.
    df = df[pd.to_numeric(df["open_time"], errors="coerce").notna()]
    out = pd.DataFrame({
        "open": df["open"].astype(float).values,
        "high": df["high"].astype(float).values,
        "low": df["low"].astype(float).values,
        "close": df["close"].astype(float).values,
        "volume": df["volume"].astype(float).values,
    }, index=_to_utc(df["open_time"]))
    out.index.name = "open_time"
    return out


def load(symbol: str, interval: str, start: str, end: str,
         data_dir: Path = DEFAULT_DATA_DIR, fetch: bool = True) -> pd.DataFrame:
    """Load klines for [start, end] months as a UTC-indexed OHLCV DataFrame."""
    if fetch:
        paths = download(symbol, interval, start, end, data_dir)
    else:
        target = Path(data_dir) / symbol / interval
        candidates = [target / f"{symbol}-{interval}-{m}.zip" for m in _months(start, end)]
        exists = [p.exists() for p in candidates]
        if not any(exists):
            raise MissingDataError(f"no cached data for {symbol} {interval} {start}..{end}")
        first = exists.index(True)
        paths = candidates[first:]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            raise MissingDataError(f"missing cached files: {missing[:3]}")
    frames = [read_zip(p) for p in paths]
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    if interval == "1d":
        expected = pd.date_range(df.index[0], df.index[-1], freq="D")
        gaps = expected.difference(df.index)
        if len(gaps):
            raise MissingDataError(
                f"{symbol} missing {len(gaps)} day(s): {[d.strftime('%Y-%m-%d') for d in gaps[:3]]}")
    return df
