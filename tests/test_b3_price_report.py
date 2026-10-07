from io import BytesIO
import zipfile

from mercado_financeiro.data.b3_prices import parse_b3_price_report


def _xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:bvmf.217.01.xsd">
  <PricRpt>
    <TradDt><Dt>2026-10-06</Dt></TradDt>
    <SctyId><TckrSymb>PETR4</TckrSymb></SctyId>
    <FinInstrmId><OthrId>SEC-PETR4</OthrId></FinInstrmId>
    <TradDtls><TradQty>1234</TradQty></TradDtls>
    <FinInstrmAttrbts>
      <NtlFinVol>1000000.50</NtlFinVol>
      <OpnIntrst>10</OpnIntrst>
      <FinInstrmQty>30000</FinInstrmQty>
      <FrstPric>29.50</FrstPric>
      <MinPric>29.10</MinPric>
      <MaxPric>30.20</MaxPric>
      <TradAvrgPric>29.80</TradAvrgPric>
      <LastPric>30.00</LastPric>
      <RglrTxsQty>999</RglrTxsQty>
    </FinInstrmAttrbts>
  </PricRpt>
</Document>
"""


def test_parses_official_pricereport_tags_from_raw_xml():
    frame = parse_b3_price_report(_xml())
    row = frame.iloc[0]
    assert row["ticker"] == "PETR4"
    assert row["instrument_id"] == "SEC-PETR4"
    assert row["open_price"] == 29.5
    assert row["average_price"] == 29.8
    assert row["close_price"] == 30.0
    assert row["financial_volume"] == 1000000.5
    assert row["regular_transactions"] == 999.0


def test_parses_zip_and_preserves_member_lineage():
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BVBG.186.01_sample.xml", _xml())
    frame = parse_b3_price_report(stream.getvalue())
    assert frame.iloc[0]["source_member"] == "BVBG.186.01_sample.xml"
