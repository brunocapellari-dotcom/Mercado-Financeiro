from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import csv
from pathlib import PurePosixPath
import re
import zipfile

import pandas as pd

_ISSUER_CODE_RE = re.compile(r"^[A-Z0-9]{4}$")


@dataclass(frozen=True)
class B3EmissorAudit:
    rows: int
    valid_rows: int
    invalid_code_rows: int
    invalid_cnpj_rows: int
    unique_issuer_codes: int
    ambiguous_issuer_codes: int


def _cnpj_check_digits(digits12: str) -> str:
    def digit(base: str, weights: list[int]) -> str:
        total = sum(int(ch) * weight for ch, weight in zip(base, weights, strict=True))
        remainder = total % 11
        value = 0 if remainder < 2 else 11 - remainder
        return str(value)

    d1 = digit(digits12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = digit(digits12 + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return d1 + d2


def normalize_cnpj(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 14 or len(set(digits)) == 1:
        return None
    if _cnpj_check_digits(digits[:12]) != digits[-2:]:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"


def ticker_issuer_code(ticker: object) -> str | None:
    if ticker is None or pd.isna(ticker):
        return None
    text = str(ticker).strip().upper().replace(" ", "")
    if len(text) < 5:
        return None
    code = text[:4]
    return code if _ISSUER_CODE_RE.fullmatch(code) else None


def parse_b3_emissor_zip(
    payload: bytes,
    *,
    evidence_available_from: str | pd.Timestamp,
    source_sha256: str | None = None,
) -> tuple[pd.DataFrame, B3EmissorAudit]:
    """Parse B3 EMISSOR.TXT as static issuer-identity evidence.

    EMISSOR is not used as publication-time economic data. Its current snapshot may
    reconstruct historical static identity only, and its evidence timestamp is kept
    so every ex-post mapping remains auditable.
    """
    if not payload:
        raise ValueError("empty B3 EMISSOR ZIP payload")
    available = pd.Timestamp(evidence_available_from)
    if pd.isna(available):
        raise ValueError("invalid evidence_available_from")

    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid B3 EMISSOR ZIP") from exc

    with archive:
        candidates = []
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe member path in B3 EMISSOR ZIP")
            if path.name.upper() == "EMISSOR.TXT":
                candidates.append(info)
        if len(candidates) != 1:
            raise ValueError(f"expected exactly one EMISSOR.TXT, found {len(candidates)}")
        with archive.open(candidates[0]) as raw:
            wrapper = TextIOWrapper(raw, encoding="latin-1", newline="")
            rows = list(csv.reader(wrapper))

    records: list[dict[str, object]] = []
    invalid_code = 0
    invalid_cnpj = 0
    for row in rows:
        if len(row) < 3:
            continue
        code = row[0].strip().upper()
        if not _ISSUER_CODE_RE.fullmatch(code):
            invalid_code += 1
            continue
        cnpj = normalize_cnpj(row[2])
        if cnpj is None:
            invalid_cnpj += 1
            continue
        records.append(
            {
                "issuer_code": code,
                "issuer_id": cnpj,
                "issuer_name": row[1].strip(),
                "upstream_date_raw": row[3].strip() if len(row) > 3 else None,
                "identity_evidence_available_from": available,
                "identity_evidence_source": "B3_EMISSOR_CURRENT_SNAPSHOT",
                "identity_source_sha256": source_sha256,
            }
        )

    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        frame = pd.DataFrame(
            columns=[
                "issuer_code",
                "issuer_id",
                "issuer_name",
                "upstream_date_raw",
                "identity_evidence_available_from",
                "identity_evidence_source",
                "identity_source_sha256",
            ]
        )
        ambiguous_codes = 0
        unique_codes = 0
    else:
        frame = frame.drop_duplicates().reset_index(drop=True)
        counts = frame.groupby("issuer_code")["issuer_id"].nunique()
        ambiguous_codes = int((counts > 1).sum())
        unique_codes = int(counts.size)

    audit = B3EmissorAudit(
        rows=len(rows),
        valid_rows=len(frame),
        invalid_code_rows=invalid_code,
        invalid_cnpj_rows=invalid_cnpj,
        unique_issuer_codes=unique_codes,
        ambiguous_issuer_codes=ambiguous_codes,
    )
    return frame, audit


def resolve_b3_emissor_identity(
    tickers: pd.Series,
    emissor: pd.DataFrame,
) -> pd.DataFrame:
    required = {"issuer_code", "issuer_id", "identity_evidence_available_from"}
    missing = required - set(emissor.columns)
    if missing:
        raise ValueError(f"missing B3 EMISSOR columns: {sorted(missing)}")

    evidence = emissor.copy()
    counts = evidence.groupby("issuer_code")["issuer_id"].nunique()
    ambiguous = set(counts[counts > 1].index.astype(str))
    evidence = evidence.sort_values(
        ["issuer_code", "identity_evidence_available_from"], kind="stable"
    ).drop_duplicates(["issuer_code", "issuer_id"], keep="last")

    input_frame = pd.DataFrame({"ticker": tickers.astype(str)})
    input_frame["issuer_code"] = input_frame["ticker"].map(ticker_issuer_code)
    out = input_frame.merge(evidence, on="issuer_code", how="left", validate="many_to_many")

    duplicated_ticker = out.groupby("ticker")["issuer_id"].nunique(dropna=True)
    ambiguous_tickers = set(duplicated_ticker[duplicated_ticker > 1].index.astype(str))
    out["identity_mapping_status"] = "unresolved_no_b3_emissor_evidence"
    resolved_mask = out["issuer_id"].notna()
    out.loc[resolved_mask, "identity_mapping_status"] = "resolved"
    out.loc[
        out["issuer_code"].isin(ambiguous) | out["ticker"].isin(ambiguous_tickers),
        "identity_mapping_status",
    ] = "ambiguous_issuer"
    out.loc[out["identity_mapping_status"] != "resolved", "issuer_id"] = pd.NA
    out = out.sort_values(["ticker", "identity_evidence_available_from"], kind="stable")
    out = out.drop_duplicates("ticker", keep="last")
    return out.reset_index(drop=True)
