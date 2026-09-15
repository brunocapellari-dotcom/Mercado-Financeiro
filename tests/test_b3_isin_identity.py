from __future__ import annotations

from io import BytesIO, TextIOWrapper
import csv
import zipfile

import pandas as pd

from mercado_financeiro.pit.b3_isin import (
    enrich_historical_identity_with_exact_isin,
    isin_checksum_valid,
    parse_b3_isin_registry_zip,
)


def _registry_zip() -> bytes:
    emissor = BytesIO()
    text = TextIOWrapper(emissor, encoding="latin-1", newline="", write_through=True)
    writer = csv.writer(text)
    writer.writerow(["PETR", "PETROBRAS", "33000167000101", "20000101"])
    writer.writerow(["VALE", "VALE S.A.", "33592510000154", "20000101"])
    text.flush()

    numeraca = BytesIO()
    text2 = TextIOWrapper(numeraca, encoding="latin-1", newline="", write_through=True)
    writer2 = csv.writer(text2)
    row = [""] * 45
    row[0] = "20110103"
    row[2] = "BRPETRACNOR9"
    row[3] = "PETR"
    row[4] = "ESVUFR"
    row[5] = "PETROBRAS ON"
    row[42] = "ATIVO"
    row[44] = "BR"
    writer2.writerow(row)
    row2 = [""] * 45
    row2[0] = "20110103"
    row2[2] = "BRVALEACNOR0"
    row2[3] = "VALE"
    row2[4] = "ESVUFR"
    row2[5] = "VALE ON"
    row2[42] = "ATIVO"
    row2[44] = "BR"
    writer2.writerow(row2)
    text2.flush()

    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("EMISSOR.TXT", emissor.getvalue())
        archive.writestr("NUMERACA.TXT", numeraca.getvalue())
    return out.getvalue()


def test_isin_checksum_validation():
    assert isin_checksum_valid("BRPETRACNOR9")
    assert isin_checksum_valid("BRVALEACNOR0")
    assert not isin_checksum_valid("BRPETRACNOR8")
    assert not isin_checksum_valid("PETR3")


def test_registry_exact_isin_to_cnpj():
    registry, audit = parse_b3_isin_registry_zip(
        _registry_zip(),
        evidence_available_from="2026-09-14T20:00:07-03:00",
        source_sha256="abc",
    )
    assert audit.valid_issuers == 2
    assert audit.valid_security_rows == 2
    assert audit.ambiguous_isins == 0
    mapping = dict(zip(registry["security_id"], registry["issuer_id"], strict=True))
    assert mapping["BRPETRACNOR9"] == "33.000.167/0001-01"
    assert mapping["BRVALEACNOR0"] == "33.592.510/0001-54"


def test_exact_isin_resolves_and_marks_later_evidence():
    registry, _ = parse_b3_isin_registry_zip(
        _registry_zip(), evidence_available_from="2026-09-14T20:00:07-03:00"
    )
    universe = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2011-01-03")],
            "security_id": ["BRPETRACNOR9"],
            "ticker": ["PETR3"],
            "issuer_id": [pd.NA],
            "identity_mapping_status": ["unresolved_no_fca_evidence"],
            "financial_volume": [1_000_000.0],
        }
    )
    enriched, audit = enrich_historical_identity_with_exact_isin(universe, registry)
    assert enriched.loc[0, "issuer_id"] == "33.000.167/0001-01"
    assert enriched.loc[0, "identity_resolution_method"] == "B3_ISIN_EXACT"
    assert bool(enriched.loc[0, "identity_reconstruction_uses_later_evidence"])
    assert audit.mapped_volume_ratio == 1.0


def test_exact_isin_outranks_weaker_ticker_conflict_but_preserves_flag():
    registry, _ = parse_b3_isin_registry_zip(
        _registry_zip(), evidence_available_from="2026-09-14T20:00:07-03:00"
    )
    universe = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2011-01-03")],
            "security_id": ["BRPETRACNOR9"],
            "ticker": ["PETR3"],
            "issuer_id": [pd.NA],
            "identity_mapping_status": ["ambiguous_source_conflict"],
            "financial_volume": [1_000_000.0],
        }
    )
    enriched, audit = enrich_historical_identity_with_exact_isin(universe, registry)
    assert enriched.loc[0, "identity_mapping_status"] == "resolved"
    assert enriched.loc[0, "issuer_id"] == "33.000.167/0001-01"
    assert bool(enriched.loc[0, "identity_weaker_source_disagreed"])
    assert audit.exact_overrides_prior_conflict_rows == 1
