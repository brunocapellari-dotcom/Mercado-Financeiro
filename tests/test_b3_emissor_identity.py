from __future__ import annotations

from io import BytesIO, TextIOWrapper
import csv
import zipfile

import pandas as pd

from mercado_financeiro.pit.b3_emissor import (
    enrich_historical_identity_with_b3_emissor,
    normalize_cnpj,
    parse_b3_emissor_zip,
    resolve_b3_emissor_identity,
    ticker_issuer_code,
)


def _emissor_zip(rows: list[list[str]]) -> bytes:
    text = BytesIO()
    wrapper = TextIOWrapper(text, encoding="latin-1", newline="", write_through=True)
    writer = csv.writer(wrapper)
    writer.writerows(rows)
    wrapper.flush()
    csv_bytes = text.getvalue()
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("EMISSOR.TXT", csv_bytes)
    return out.getvalue()


def _universe(status: str = "unresolved_no_fca_evidence", issuer_id=None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2011-01-03")],
            "security_id": ["BRPETRACNOR9"],
            "ticker": ["PETR3"],
            "issuer_id": [issuer_id],
            "identity_mapping_status": [status],
            "financial_volume": [1_000_000.0],
        }
    )


def test_cnpj_and_ticker_prefix_normalization():
    assert normalize_cnpj("33000167000101") == "33.000.167/0001-01"
    assert normalize_cnpj("00.000.000/0000-00") is None
    assert ticker_issuer_code("PETR3") == "PETR"
    assert ticker_issuer_code("ENMA3B") == "ENMA"


def test_parse_and_resolve_emissor_zip():
    payload = _emissor_zip(
        [
            ["PETR", "PETROLEO BRASILEIRO S A PETROBRAS", "33000167000101", "20000101"],
            ["VALE", "VALE S.A.", "33592510000154", "20000101"],
            ["BAD!", "INVALID", "33000167000101", "20000101"],
        ]
    )
    frame, audit = parse_b3_emissor_zip(
        payload,
        evidence_available_from="2026-09-14T03:00:00-03:00",
        source_sha256="abc",
    )
    assert audit.valid_rows == 2
    assert audit.invalid_code_rows == 1
    resolved = resolve_b3_emissor_identity(pd.Series(["PETR3", "VALE5"]), frame)
    assert dict(zip(resolved["ticker"], resolved["issuer_id"], strict=True))["PETR3"] == "33.000.167/0001-01"


def test_enrichment_resolves_only_static_identity_and_marks_later_evidence():
    payload = _emissor_zip(
        [["PETR", "PETROLEO BRASILEIRO S A PETROBRAS", "33000167000101", "20000101"]]
    )
    evidence, _ = parse_b3_emissor_zip(
        payload,
        evidence_available_from="2026-09-14T03:00:00-03:00",
    )
    enriched, audit = enrich_historical_identity_with_b3_emissor(_universe(), evidence)
    row = enriched.iloc[0]
    assert row["issuer_id"] == "33.000.167/0001-01"
    assert row["identity_mapping_status"] == "resolved"
    assert row["identity_resolution_method"] == "B3_EMISSOR_PREFIX4"
    assert bool(row["identity_reconstruction_uses_later_evidence"])
    assert audit.newly_resolved_rows == 1
    assert audit.mapped_volume_ratio == 1.0


def test_weaker_current_prefix_disagreement_does_not_erase_historical_fca_identity():
    payload = _emissor_zip(
        [["PETR", "PETROLEO BRASILEIRO S A PETROBRAS", "33000167000101", "20000101"]]
    )
    evidence, _ = parse_b3_emissor_zip(
        payload,
        evidence_available_from="2026-09-14T03:00:00-03:00",
    )
    universe = _universe(status="resolved", issuer_id="33.592.510/0001-54")
    enriched, audit = enrich_historical_identity_with_b3_emissor(universe, evidence)
    assert enriched.loc[0, "identity_mapping_status"] == "resolved"
    assert enriched.loc[0, "issuer_id"] == "33.592.510/0001-54"
    assert bool(enriched.loc[0, "identity_weaker_source_disagreed"])
    assert audit.conflict_rows == 1
    assert audit.mapped_volume_ratio == 1.0
