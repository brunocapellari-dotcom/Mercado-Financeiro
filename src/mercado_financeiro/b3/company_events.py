from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Iterable

import pandas as pd

from mercado_financeiro.security import (
    DownloadPolicy,
    RetryPolicy,
    download_https_with_retry,
)


_COMPANY_INFO_URL = (
    "https://sistemaswebb3-listados.b3.com.br/"
    "listedCompaniesProxy/CompanyCall/GetListedSupplementCompany/{token}"
)
_ISSUING_COMPANY_RE = re.compile(r"^[A-Z0-9]{3,12}$")


@dataclass(frozen=True)
class B3CompanyEventsAudit:
    issuing_company: str
    rows: int
    cash_rows: int
    stock_rows: int
    subscription_rows: int
    rows_with_isin: int
    source_sha256: str
    retrieved_at: pd.Timestamp


def encode_b3_company_request(issuing_company: str, *, language: str = "pt-br") -> str:
    """Encode the documented B3 listed-company request payload."""
    company = issuing_company.strip().upper()
    if not _ISSUING_COMPANY_RE.fullmatch(company):
        raise ValueError("invalid B3 issuing-company code")
    payload = json.dumps(
        {"issuingCompany": company, "language": language},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def _br_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"invalid B3 numeric value: {value!r}") from exc


def _b3_date(value: object) -> pd.Timestamp | pd.NaT:
    if value is None or pd.isna(value) or not str(value).strip():
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        raise ValueError(f"invalid B3 event date: {value!r}")
    return pd.Timestamp(parsed).normalize()


def _security_id(row: dict[str, object]) -> str | None:
    for key in ("isinCode", "assetIssued"):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip().upper()
        if len(text) == 12 and text[:2].isalpha() and text.isalnum():
            return f"ISIN:{text}"
    return None


def parse_b3_company_events(
    payload: bytes,
    *,
    issuing_company: str,
    retrieved_at: datetime | pd.Timestamp,
) -> tuple[pd.DataFrame, B3CompanyEventsAudit]:
    """Parse one official B3 listed-company snapshot into a lossless event ledger.

    The endpoint is a current snapshot. ``available_from`` is therefore the retrieval
    timestamp, not the historical approval date. Historical approval/last-COM/payment
    dates are preserved separately so later reconciliation with CVM IPE can establish
    publication-time availability without rewriting source evidence.
    """
    if not payload:
        raise ValueError("empty B3 company-event payload")
    company = issuing_company.strip().upper()
    if not _ISSUING_COMPANY_RE.fullmatch(company):
        raise ValueError("invalid B3 issuing-company code")
    retrieved = pd.to_datetime(retrieved_at, errors="coerce", utc=True)
    if pd.isna(retrieved):
        raise ValueError("retrieved_at must be a valid timezone-aware timestamp")

    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid B3 company-event JSON") from exc
    if not isinstance(obj, list) or not obj or not isinstance(obj[0], dict):
        raise ValueError("unexpected B3 company-event payload shape")
    root = obj[0]
    digest = sha256(payload).hexdigest()

    records: list[dict[str, object]] = []
    families = (
        ("cash", "cashDividends"),
        ("stock", "stockDividends"),
        ("subscription", "subscriptions"),
    )
    for family, key in families:
        values = root.get(key, []) or []
        if not isinstance(values, list):
            raise ValueError(f"unexpected B3 {key} payload shape")
        for sequence, raw in enumerate(values):
            if not isinstance(raw, dict):
                raise ValueError(f"unexpected B3 {key} event row")
            record: dict[str, object] = {
                "issuing_company": company,
                "event_family": family,
                "security_id": _security_id(raw),
                "asset_issued": raw.get("assetIssued"),
                "isin_code": raw.get("isinCode"),
                "event_type_raw": str(raw.get("label") or "").strip().upper(),
                "declared_date": _b3_date(raw.get("approvedOn")),
                "last_date_prior": _b3_date(raw.get("lastDatePrior")),
                "pay_date": _b3_date(raw.get("paymentDate")),
                "cash_per_share_raw": _br_number(raw.get("rate")),
                "stock_factor_raw": _br_number(raw.get("factor")),
                "subscription_percentage_raw": _br_number(raw.get("percentage")),
                "subscription_price_raw": _br_number(raw.get("priceUnit")),
                "subscription_deadline": _b3_date(raw.get("subscriptionDate")),
                "related_to": raw.get("relatedTo"),
                "remarks": raw.get("remarks"),
                "available_from": retrieved,
                "source_retrieved_at": retrieved,
                "source_sha256": digest,
                "source": "B3_LISTED_SUPPLEMENT_COMPANY_CURRENT_SNAPSHOT",
                "source_sequence": sequence,
            }
            records.append(record)

    columns = [
        "issuing_company",
        "event_family",
        "security_id",
        "asset_issued",
        "isin_code",
        "event_type_raw",
        "declared_date",
        "last_date_prior",
        "pay_date",
        "cash_per_share_raw",
        "stock_factor_raw",
        "subscription_percentage_raw",
        "subscription_price_raw",
        "subscription_deadline",
        "related_to",
        "remarks",
        "available_from",
        "source_retrieved_at",
        "source_sha256",
        "source",
        "source_sequence",
    ]
    frame = pd.DataFrame.from_records(records, columns=columns)
    audit = B3CompanyEventsAudit(
        issuing_company=company,
        rows=len(frame),
        cash_rows=int(frame["event_family"].eq("cash").sum()) if len(frame) else 0,
        stock_rows=int(frame["event_family"].eq("stock").sum()) if len(frame) else 0,
        subscription_rows=int(frame["event_family"].eq("subscription").sum()) if len(frame) else 0,
        rows_with_isin=int(frame["security_id"].notna().sum()) if len(frame) else 0,
        source_sha256=digest,
        retrieved_at=pd.Timestamp(retrieved),
    )
    return frame, audit


def _cash_action_type(raw_label: object) -> str:
    label = "" if raw_label is None else str(raw_label).strip().upper()
    if label in {"JRS CAP PROPRIO", "JUROS SOBRE CAPITAL PROPRIO", "JCP"}:
        return "interest_on_equity"
    if label == "DIVIDENDO":
        return "cash_dividend"
    return "other"


def _next_observed_session(
    last_date_prior: pd.Timestamp,
    sessions: pd.DatetimeIndex,
) -> pd.Timestamp | None:
    position = sessions.searchsorted(pd.Timestamp(last_date_prior).normalize(), side="right")
    if position >= len(sessions):
        return None
    return pd.Timestamp(sessions[position]).normalize()


def b3_cash_actions_to_canonical(
    events: pd.DataFrame,
    *,
    observed_sessions: Iterable[object],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert B3 cash events to the canonical corporate-action contract.

    B3 reports ``lastDatePrior`` (the last COM session), not the EX session. The EX
    date is therefore resolved as the *next actually observed B3 session*. Weekday
    arithmetic is forbidden. Rows without ISIN, positive cash amount, last-COM date,
    or next observed session remain in the returned unresolved ledger.

    Current-snapshot ``available_from`` is preserved. These rows are suitable for
    historical return reconciliation, not as publication-time trading features until
    independently linked to a contemporaneous disclosure such as CVM IPE.
    """
    required = {
        "event_family",
        "security_id",
        "event_type_raw",
        "last_date_prior",
        "declared_date",
        "pay_date",
        "cash_per_share_raw",
        "available_from",
        "source_sha256",
        "source",
    }
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"missing B3 event fields: {sorted(missing)}")

    sessions = pd.DatetimeIndex(pd.to_datetime(list(observed_sessions), errors="coerce"))
    if sessions.isna().any():
        raise ValueError("observed B3 sessions contain invalid dates")
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    sessions = sessions.normalize().drop_duplicates().sort_values()
    if len(sessions) < 2:
        raise ValueError("at least two observed B3 sessions are required")

    cash = events.loc[events["event_family"].eq("cash")].copy()
    canonical: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    for row in cash.to_dict(orient="records"):
        reason: str | None = None
        security_id = row.get("security_id")
        amount = row.get("cash_per_share_raw")
        last_prior = row.get("last_date_prior")
        effective_date: pd.Timestamp | None = None
        if not security_id:
            reason = "missing_security_isin"
        elif amount is None or float(amount) <= 0:
            reason = "missing_or_nonpositive_cash_amount"
        elif pd.isna(last_prior):
            reason = "missing_last_com_date"
        else:
            effective_date = _next_observed_session(pd.Timestamp(last_prior), sessions)
            if effective_date is None:
                reason = "next_session_outside_observed_coverage"

        if reason is not None:
            unresolved.append({**row, "canonical_status": reason})
            continue

        action_type = _cash_action_type(row.get("event_type_raw"))
        event_key = "|".join(
            [
                str(security_id),
                str(effective_date.date()),
                action_type,
                str(amount),
                str(row.get("declared_date")),
            ]
        )
        canonical.append(
            {
                "event_id": "B3:" + sha256(event_key.encode("utf-8")).hexdigest()[:24],
                "security_id": str(security_id).upper(),
                "effective_date": effective_date,
                "ex_date": effective_date,
                "declared_date": row.get("declared_date"),
                "record_date": pd.NaT,
                "pay_date": row.get("pay_date"),
                "action_type": action_type,
                "cash_per_share": float(amount),
                "share_ratio": 1.0,
                "available_from": row.get("available_from"),
                "last_date_prior": row.get("last_date_prior"),
                "source": row.get("source"),
                "source_sha256": row.get("source_sha256"),
                "evidence_mode": "historical_reconciliation_only",
            }
        )

    return (
        pd.DataFrame.from_records(canonical),
        pd.DataFrame.from_records(unresolved),
    )


class B3CompanyEventsSource:
    """Official B3 listed-company event snapshot collector."""

    name = "B3_LISTED_SUPPLEMENT_COMPANY"

    def __init__(
        self,
        *,
        policy: DownloadPolicy | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._policy = policy or DownloadPolicy(
            allowed_hosts=frozenset({"sistemaswebb3-listados.b3.com.br"}),
            timeout_seconds=60.0,
            max_bytes=50_000_000,
        )
        self._retry = retry_policy or RetryPolicy(
            attempts=5,
            initial_delay_seconds=2.0,
            max_delay_seconds=20.0,
        )

    def fetch(
        self,
        issuing_company: str,
        *,
        retrieved_at: datetime | None = None,
    ) -> tuple[pd.DataFrame, B3CompanyEventsAudit]:
        company = issuing_company.strip().upper()
        token = encode_b3_company_request(company)
        url = _COMPANY_INFO_URL.format(token=token)
        payload = download_https_with_retry(
            url,
            self._policy,
            retry_policy=self._retry,
        )
        when = retrieved_at or datetime.now(timezone.utc)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return parse_b3_company_events(
            payload,
            issuing_company=company,
            retrieved_at=when,
        )
