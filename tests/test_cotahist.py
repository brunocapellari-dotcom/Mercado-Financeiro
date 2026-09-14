from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from mercado_financeiro.b3.cotahist import (
    parse_cotahist_record,
    read_cotahist,
    select_regular_share_quotes,
)


def _put(chars: list[str], start: int, end: int, value: str) -> None:
    width = end - start
    if len(value) > width:
        raise ValueError(value)
    chars[start:end] = list(value.ljust(width))


def _put_num(chars: list[str], start: int, end: int, value: int) -> None:
    width = end - start
    raw = str(value)
    if len(raw) > width:
        raise ValueError(value)
    chars[start:end] = list(raw.zfill(width))


def _record(
    *,
    date: str = "20200102",
    bdi: str = "02",
    ticker: str = "PETR4",
    market: int = 10,
    specification: str = "PN      N2",
    close_cents: int = 3070,
    factor: int = 1,
    isin: str = "BRPETRACNPR6",
) -> str:
    chars = list(" " * 245)
    _put(chars, 0, 2, "01")
    _put(chars, 2, 10, date)
    _put(chars, 10, 12, bdi)
    _put(chars, 12, 24, ticker)
    _put_num(chars, 24, 27, market)
    _put(chars, 27, 39, "PETROBRAS")
    _put(chars, 39, 49, specification)
    _put(chars, 49, 52, "")
    _put(chars, 52, 56, "R$")
    for start, end, value in (
        (56, 69, 3051),
        (69, 82, 3070),
        (82, 95, 3031),
        (95, 108, 3057),
        (108, 121, close_cents),
        (121, 134, 3069),
        (134, 147, 3070),
    ):
        _put_num(chars, start, end, value)
    _put_num(chars, 147, 152, 64405)
    _put_num(chars, 152, 170, 37774500)
    _put_num(chars, 170, 188, 115477749300)
    _put_num(chars, 188, 201, 0)
    _put_num(chars, 201, 202, 0)
    _put_num(chars, 202, 210, 99991231)
    _put_num(chars, 210, 217, factor)
    _put_num(chars, 217, 230, 0)
    _put(chars, 230, 242, isin)
    _put_num(chars, 242, 245, 196)
    return "".join(chars)


def test_parse_official_layout_positions_and_per_unit_price():
    row = parse_cotahist_record(_record(close_cents=3070, factor=1))
    assert row["trade_date"] == pd.Timestamp("2020-01-02")
    assert row["ticker"] == "PETR4"
    assert row["market_type"] == 10
    assert row["close_quote"] == 30.70
    assert row["close_price"] == 30.70
    assert row["isin"] == "BRPETRACNPR6"
    assert row["security_id"] == "ISIN:BRPETRACNPR6"


def test_quotation_factor_converts_quote_to_per_unit_price():
    row = parse_cotahist_record(_record(close_cents=125000, factor=1000))
    assert row["close_quote"] == 1250.0
    assert row["close_price"] == 1.25


def test_parse_rejects_bad_length_and_non_record_01():
    with pytest.raises(ValueError, match="245 chars"):
        parse_cotahist_record("01")
    with pytest.raises(ValueError, match="record type 01"):
        parse_cotahist_record("00" + " " * 243)


def test_read_raw_and_wrapped_zip(tmp_path: Path):
    header = "00" + " " * 243
    trailer = "99" + " " * 243
    payload = (header + "\n" + _record() + "\n" + trailer + "\n").encode("latin-1")

    raw_zip = tmp_path / "COTAHIST_A2020.ZIP"
    with zipfile.ZipFile(raw_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("COTAHIST_A2020.TXT", payload)

    raw_df = read_cotahist(raw_zip)
    assert len(raw_df) == 1
    assert raw_df.iloc[0]["ticker"] == "PETR4"

    wrapper = tmp_path / "artifact.zip"
    with zipfile.ZipFile(wrapper, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("COTAHIST_A2020.ZIP", raw_zip.read_bytes())
    wrapped_df = read_cotahist(wrapper)
    pd.testing.assert_frame_equal(raw_df, wrapped_df)


def test_regular_share_filter_keeps_distressed_bdi_but_excludes_fractional_and_nonshare():
    rows = [
        parse_cotahist_record(_record(bdi="02", ticker="PETR4", specification="PN")),
        parse_cotahist_record(
            _record(bdi="08", ticker="ABCD3", specification="ON", isin="BRABCDACNOR1")
        ),
        parse_cotahist_record(
            _record(bdi="96", ticker="PETR4F", specification="PN", isin="BRPETRACNPR6")
        ),
        parse_cotahist_record(
            _record(bdi="12", ticker="FUND11", specification="CI", isin="BRFUNDCTF000")
        ),
    ]
    frame = pd.DataFrame(rows)

    selected, audit = select_regular_share_quotes(frame)

    assert set(selected["ticker"]) == {"PETR4", "ABCD3"}
    assert audit.share_rows == 2
    assert audit.unique_isins == 2
    assert audit.missing_isin_rows == 0


def test_regular_share_filter_rejects_duplicate_security_date():
    row = parse_cotahist_record(_record())
    frame = pd.DataFrame([row, row])
    with pytest.raises(ValueError, match="duplicate canonical security/date"):
        select_regular_share_quotes(frame)
