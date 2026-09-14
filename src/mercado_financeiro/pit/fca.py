from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

import pandas as pd

from .cvm import _inner_zip_bytes, _read_csv

_SHARE_TICKER_RE = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")
_LEGACY_ZERO_PADDED_SHARE_RE = re.compile(r"^([A-Z]{4})0([3-8])$")


@dataclass(frozen=True)
class FCATickerBridgeAudit:
    year: int
    section_rows: int
    stock_rows: int
    rows_with_ticker: int
    normalized_rows: int
    missing_available_from: int
    invalid_ticker_rows: int
    issuers: int
    tickers: int


def _normalize_stock_type(value: object) -> str | None:
    text = "" if value is None or pd.isna(value) else str(value).strip().casefold()
    if text == "ações ordinárias".casefold():
        return "ordinary"
    if text == "ações preferenciais".casefold():
        return "preferred"
    return None


def normalize_fca_share_ticker(value: object, share_class: str) -> str | None:
    """Normalize only historically observed B3 stock ticker formatting.

    Older FCA vintages contain codes such as ``BSLI03`` that later appear as
    ``BSLI3``. The zero-padding normalization is intentionally restricted to
    ordinary/preferred share suffixes 3-8; other structures are not guessed.
    """
    if value is None or pd.isna(value):
        return None
    ticker = str(value).strip().upper().replace(" ", "")
    if not ticker:
        return None
    if share_class in {"ordinary", "preferred"}:
        match = _LEGACY_ZERO_PADDED_SHARE_RE.fullmatch(ticker)
        if match:
            ticker = f"{match.group(1)}{match.group(2)}"
    if not _SHARE_TICKER_RE.fullmatch(ticker):
        return None
    return ticker


def audit_fca_ticker_issuer_bridge(
    path: str | Path,
    year: int,
) -> tuple[pd.DataFrame, FCATickerBridgeAudit]:
    """Build the represented FCA stock/ticker rows with exact publication time.

    As with FRE/DFP structured sections, the annual FCA section is a current
    materialization. Each row is linked to the submission ledger through the exact
    document id/version so ``available_from`` reflects when that represented version
    was received by CVM. No row may be made economically available before that date.
    """
    inner = _inner_zip_bytes(path)
    ledger = _read_csv(inner, f"fca_cia_aberta_{year}.csv")
    securities = _read_csv(inner, f"fca_cia_aberta_valor_mobiliario_{year}.csv")

    required_ledger = {"CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC", "DT_RECEB"}
    required_section = {
        "CNPJ_Companhia",
        "Data_Referencia",
        "Versao",
        "ID_Documento",
        "Valor_Mobiliario",
        "Sigla_Classe_Acao_Preferencial",
        "Codigo_Negociacao",
        "Mercado",
        "Sigla_Entidade_Administradora",
        "Data_Inicio_Negociacao",
        "Data_Fim_Negociacao",
        "Data_Inicio_Listagem",
        "Data_Fim_Listagem",
    }
    missing_ledger = required_ledger - set(ledger.columns)
    missing_section = required_section - set(securities.columns)
    if missing_ledger:
        raise ValueError(f"FCA {year}: missing ledger columns {sorted(missing_ledger)}")
    if missing_section:
        raise ValueError(f"FCA {year}: missing security columns {sorted(missing_section)}")

    ledger = ledger[list(required_ledger)].copy()
    ledger["DT_RECEB"] = pd.to_datetime(ledger["DT_RECEB"], errors="coerce")
    if ledger["DT_RECEB"].isna().any():
        raise ValueError(f"FCA {year}: ledger contains invalid DT_RECEB")

    duplicate_ledger = ledger.duplicated(
        ["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"], keep=False
    )
    if duplicate_ledger.any():
        raise ValueError(f"FCA {year}: duplicate submission ledger keys")

    out = securities.merge(
        ledger,
        left_on=["CNPJ_Companhia", "Data_Referencia", "Versao", "ID_Documento"],
        right_on=["CNPJ_CIA", "DT_REFER", "VERSAO", "ID_DOC"],
        how="left",
        validate="many_to_one",
    ).rename(columns={"DT_RECEB": "available_from"})

    out["share_class"] = out["Valor_Mobiliario"].map(_normalize_stock_type)
    stock = out.loc[out["share_class"].notna()].copy()
    with_ticker = stock.loc[stock["Codigo_Negociacao"].fillna("").str.strip().ne("")].copy()
    with_ticker["ticker_raw"] = with_ticker["Codigo_Negociacao"].astype(str).str.strip().str.upper()
    with_ticker["ticker"] = [
        normalize_fca_share_ticker(value, share_class)
        for value, share_class in zip(
            with_ticker["ticker_raw"], with_ticker["share_class"], strict=True
        )
    ]

    missing_available = int(with_ticker["available_from"].isna().sum())
    invalid_ticker = int(with_ticker["ticker"].isna().sum())
    if missing_available:
        raise ValueError(f"FCA {year}: {missing_available} ticker rows lack available_from")

    normalized = with_ticker.loc[with_ticker["ticker"].notna()].copy()
    normalized["issuer_id"] = normalized["CNPJ_Companhia"].astype(str).str.strip()
    normalized["reference_date"] = pd.to_datetime(
        normalized["Data_Referencia"], errors="coerce"
    )
    normalized["available_from"] = pd.to_datetime(
        normalized["available_from"], errors="coerce"
    )

    start_negotiation = pd.to_datetime(
        normalized["Data_Inicio_Negociacao"], errors="coerce"
    )
    start_listing = pd.to_datetime(normalized["Data_Inicio_Listagem"], errors="coerce")
    normalized["valid_from"] = start_negotiation.fillna(start_listing).fillna(
        normalized["reference_date"]
    )

    end_negotiation = pd.to_datetime(normalized["Data_Fim_Negociacao"], errors="coerce")
    end_listing = pd.to_datetime(normalized["Data_Fim_Listagem"], errors="coerce")
    reported_end = end_negotiation.fillna(end_listing)
    normalized["valid_to_exclusive"] = reported_end + pd.Timedelta(days=1)

    if normalized[["reference_date", "available_from", "valid_from"]].isna().any().any():
        raise ValueError(f"FCA {year}: normalized identity dates contain nulls")
    invalid_interval = normalized["valid_to_exclusive"].notna() & (
        normalized["valid_to_exclusive"] <= normalized["valid_from"]
    )
    if invalid_interval.any():
        raise ValueError(f"FCA {year}: invalid trading/listing validity interval")

    normalized["preferred_class"] = normalized["Sigla_Classe_Acao_Preferencial"].replace(
        {"": pd.NA}
    )
    normalized["evidence_document_id"] = normalized["ID_Documento"]
    normalized["evidence_version"] = normalized["Versao"]
    normalized["source"] = "CVM_FCA_VALOR_MOBILIARIO"
    normalized["vintage_mode"] = "conservative_latest_snapshot"
    normalized["identity_time_mode"] = "reported_trading_interval"

    keep = [
        "ticker",
        "ticker_raw",
        "issuer_id",
        "share_class",
        "preferred_class",
        "valid_from",
        "valid_to_exclusive",
        "reference_date",
        "available_from",
        "evidence_document_id",
        "evidence_version",
        "Mercado",
        "Sigla_Entidade_Administradora",
        "source",
        "vintage_mode",
        "identity_time_mode",
    ]
    normalized = normalized[keep].sort_values(
        ["ticker", "reference_date", "available_from"], kind="stable"
    ).reset_index(drop=True)

    audit = FCATickerBridgeAudit(
        year=year,
        section_rows=len(securities),
        stock_rows=len(stock),
        rows_with_ticker=len(with_ticker),
        normalized_rows=len(normalized),
        missing_available_from=missing_available,
        invalid_ticker_rows=invalid_ticker,
        issuers=normalized["issuer_id"].nunique(),
        tickers=normalized["ticker"].nunique(),
    )
    return normalized, audit


def combine_fca_ticker_issuer_history(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Combine annual FCA bridges while retaining every evidence vintage.

    Duplicate annual evidence is retained when its publication time differs. This is
    intentional: strict point-in-time resolution can then choose only evidence that
    existed by the research date. Exact duplicates are removed deterministically.
    """
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    required = {
        "ticker",
        "issuer_id",
        "valid_from",
        "valid_to_exclusive",
        "reference_date",
        "available_from",
    }
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"missing FCA bridge columns: {sorted(missing)}")

    out = out.drop_duplicates(
        [
            "ticker",
            "issuer_id",
            "share_class",
            "preferred_class",
            "valid_from",
            "valid_to_exclusive",
            "reference_date",
            "available_from",
            "evidence_document_id",
        ],
        keep="last",
    )
    return out.sort_values(
        ["ticker", "reference_date", "available_from"], kind="stable"
    ).reset_index(drop=True)
