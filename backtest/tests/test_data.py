import hashlib
import io
import urllib.error
import zipfile

import pandas as pd
import pytest

from backtest import data


def daily_zip(month: str, skip_days=()) -> bytes:
    """Binance-format 1d kline zip for every day of `month` except `skip_days`."""
    days = pd.date_range(f"{month}-01", periods=pd.Period(month).days_in_month, freq="D", tz="UTC")
    rows = []
    for d in days:
        if d.strftime("%Y-%m-%d") in skip_days:
            continue
        ms = d.value // 10**6
        rows.append(f"{ms},1,2,0.5,1.5,10,{ms + 86_399_999},0,0,0,0,0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.csv", "\n".join(rows))
    return buf.getvalue()


def fake_fetch(available: dict):
    """Serve `available[month] -> zip bytes`; anything else is HTTP 404."""
    def _fetch(url: str) -> bytes:
        name = url.rsplit("/", 1)[-1]
        checksum = name.endswith(".CHECKSUM")
        month = name.replace(".CHECKSUM", "").rsplit("-", 2)[-2:]
        month = "-".join(month).replace(".zip", "")
        if month not in available:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        payload = available[month]
        if checksum:
            return f"{hashlib.sha256(payload).hexdigest()}  {name}".encode()
        return payload
    return _fetch


def test_download_skips_leading_missing_months(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({
        "2020-08": daily_zip("2020-08"), "2020-09": daily_zip("2020-09")}))
    paths = data.download("SOLUSDT", "1d", "2020-06", "2020-09", tmp_path)
    assert [p.name for p in paths] == ["SOLUSDT-1d-2020-08.zip", "SOLUSDT-1d-2020-09.zip"]


def test_download_raises_on_internal_missing_month(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({
        "2020-08": daily_zip("2020-08"), "2020-10": daily_zip("2020-10")}))
    with pytest.raises(data.MissingDataError):
        data.download("X", "1d", "2020-08", "2020-10", tmp_path)


def test_download_raises_when_no_month_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({}))
    with pytest.raises(data.MissingDataError):
        data.download("X", "1d", "2020-08", "2020-09", tmp_path)


def test_load_raises_on_missing_day(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({
        "2020-08": daily_zip("2020-08", skip_days={"2020-08-15"})}))
    with pytest.raises(data.MissingDataError, match="2020-08-15"):
        data.load("X", "1d", "2020-08", "2020-08", tmp_path)


def test_load_from_cache_skips_leading_missing_months(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({
        "2020-08": daily_zip("2020-08"), "2020-09": daily_zip("2020-09")}))
    data.download("SOLUSDT", "1d", "2020-06", "2020-09", tmp_path)
    df = data.load("SOLUSDT", "1d", "2020-06", "2020-09", tmp_path, fetch=False)
    assert df.index[0] == pd.Timestamp("2020-08-01", tz="UTC")
    assert len(df) == 31 + 30


def test_load_from_cache_raises_on_internal_missing_month(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_fetch", fake_fetch({
        "2020-08": daily_zip("2020-08"), "2020-10": daily_zip("2020-10")}))
    data.download("X", "1d", "2020-08", "2020-08", tmp_path)
    data.download("X", "1d", "2020-10", "2020-10", tmp_path)
    with pytest.raises(data.MissingDataError):
        data.load("X", "1d", "2020-08", "2020-10", tmp_path, fetch=False)
