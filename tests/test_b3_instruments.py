from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pytest

from mercado_financeiro.b3.instruments import (
    build_cash_security_observations,
    iter_equity_instruments,
    select_latest_bvbg028_member,
)


def _instrument(
    *,
    ticker: str,
    isin: str,
    cfi: str,
    market: str = "10",
    segment: str = "1",
    security_category: str = "11",
    instrument_id: str = "123",
    mkt_cap_raw: str = "1000",
) -> str:
    return f"""
      <BizGrp>
        <Document xmlns="urn:bvmf.100.02.xsd">
          <Instrm>
            <RptParams><ActvtyInd>true</ActvtyInd><RptDtAndTm><Dt>2026-08-24</Dt></RptDtAndTm><UpdTp>COMP</UpdTp></RptParams>
            <FinInstrmId><OthrId><Id>{instrument_id}</Id><Tp><Prtry>8</Prtry></Tp></OthrId><PlcOfListg><MktIdrCd>BVMF</MktIdrCd></PlcOfListg></FinInstrmId>
            <FinInstrmAttrCmon><Asst>{ticker[:4]}</Asst><AsstDesc>{ticker[:4]}</AsstDesc><Mkt>{market}</Mkt><Sgmt>{segment}</Sgmt><Desc>{ticker}</Desc></FinInstrmAttrCmon>
            <InstrmInf><EqtyInf>
              <SctyCtgy>{security_category}</SctyCtgy><ISIN>{isin}</ISIN><DstrbtnId>1</DstrbtnId><CFICd>{cfi}</CFICd>
              <SpcfctnCd>ON</SpcfctnCd><CrpnNm>TESTE S.A.</CrpnNm><TckrSymb>{ticker}</TckrSymb>
              <AllcnRndLot>1</AllcnRndLot><PricFctr>1</PricFctr><TradgStartDt>2020-01-01</TradgStartDt><TradgEndDt>9999-12-31</TradgEndDt>
              <TradgCcy>BRL</TradgCcy><MktCptlstn Ccy="BRL">{mkt_cap_raw}</MktCptlstn><LastPric Ccy="BRL">10.00</LastPric>
            </EqtyInf></InstrmInf>
          </Instrm>
        </Document>
      </BizGrp>
    """


def _xml(created: str, instruments: list[str]) -> bytes:
    return (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<Document xmlns='urn:bvmf.052.01.xsd'><BizFileHdr><Xchg><BizGrpDesc><BizGrpDtls>"
        f"<BizGrpIdr>X</BizGrpIdr><TtlNbOfMsg>{len(instruments)}</TtlNbOfMsg><BizGrpTp>BVBG.028.02</BizGrpTp><CreDtAndTm>{created}</CreDtAndTm>"
        "</BizGrpDtls></BizGrpDesc>"
        + "".join(instruments)
        + "</Xchg></BizFileHdr></Document>"
    ).encode()


def _nested_package(path: Path) -> None:
    early = _xml(
        "2026-08-24T00:20:19",
        [_instrument(ticker="OLD3", isin="BROLD0ACNOR0", cfi="ESVUFR")],
    )
    late = _xml(
        "2026-08-24T18:40:05",
        [
            _instrument(ticker="PETR4", isin="BRPETRACNPR6", cfi="EPNNPR", mkt_cap_raw="5446501379"),
            _instrument(ticker="BOVA11", isin="BRBOVACTF003", cfi="CEOGES", security_category="3"),
            _instrument(ticker="TAXA83", isin="BRTAXAINDM77", cfi="EMXXXX"),
            _instrument(ticker="PETR4F", isin="BRPETRACNPR6", cfi="EPNNPR", market="20"),
        ],
    )
    deep_io = BytesIO()
    with zipfile.ZipFile(deep_io, "w", zipfile.ZIP_DEFLATED) as deep:
        deep.writestr("BVBG.028.02_EARLY.xml", early)
        deep.writestr("BVBG.028.02_LATE.xml", late)
    middle_io = BytesIO()
    with zipfile.ZipFile(middle_io, "w", zipfile.ZIP_DEFLATED) as middle:
        middle.writestr("IN260824.zip", deep_io.getvalue())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as outer:
        outer.writestr("artifact.zip", middle_io.getvalue())


def test_selects_latest_complete_snapshot_from_nested_artifact(tmp_path: Path):
    path = tmp_path / "artifact.zip.zip"
    _nested_package(path)
    member, created = select_latest_bvbg028_member(path)
    assert member == "BVBG.028.02_LATE.xml"
    assert created == "2026-08-24T18:40:05"


def test_stream_parser_preserves_raw_b3_fields(tmp_path: Path):
    path = tmp_path / "artifact.zip.zip"
    _nested_package(path)
    rows = list(iter_equity_instruments(path))
    assert {row["ticker"] for row in rows} == {"PETR4", "BOVA11", "TAXA83", "PETR4F"}
    petr = next(row for row in rows if row["ticker"] == "PETR4")
    assert petr["isin"] == "BRPETRACNPR6"
    assert petr["market_capitalisation_raw"] == "5446501379"
    assert petr["package_created_at"] == "2026-08-24T18:40:05"


def test_cash_observations_exclude_synthetic_and_odd_lot_rows(tmp_path: Path):
    path = tmp_path / "artifact.zip.zip"
    _nested_package(path)
    out = build_cash_security_observations(path)
    assert set(out["ticker"]) == {"PETR4", "BOVA11"}
    assert out["listing_id"].is_unique
    assert set(out["security_id"]) == {"ISIN:BRPETRACNPR6", "ISIN:BRBOVACTF003"}


def test_cash_observations_fail_on_duplicate_canonical_listing(tmp_path: Path):
    xml = _xml(
        "2026-08-24T18:40:05",
        [
            _instrument(ticker="AAA3", isin="BRAAAAACNOR0", cfi="ESVUFR", instrument_id="1"),
            _instrument(ticker="AAB3", isin="BRAAAAACNOR0", cfi="ESVUFR", instrument_id="2"),
        ],
    )
    path = tmp_path / "dup.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BVBG.028.02_DUP.xml", xml)
    with pytest.raises(ValueError, match="duplicate canonical listing observations"):
        build_cash_security_observations(path)
