from __future__ import annotations

from hashlib import sha256
import json

import pandas as pd


_DEFAULT_STATE_FIELDS = (
    "ticker",
    "instrument_id",
    "isin",
    "market",
    "segment",
    "security_category",
    "cfi_code",
    "specification_code",
    "corporation_name",
    "trading_start_date",
    "trading_end_date",
)


def _json_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _state_payload(row: pd.Series, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: _json_value(row.get(field)) for field in fields}


def _state_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def build_security_master_scd2(
    observations: pd.DataFrame,
    *,
    state_fields: tuple[str, ...] = _DEFAULT_STATE_FIELDS,
) -> pd.DataFrame:
    """Build an SCD2 listing history from authoritative complete B3 snapshots.

    `valid_to_exclusive` is the first supplied snapshot date on which the prior
    state is no longer observed (because it disappeared or an identity attribute
    changed). Therefore the caller must only pass snapshots considered complete and
    authoritative for their dates. Sparse inputs preserve an observed boundary, not
    an invented exact delisting date.
    """
    required = {"listing_id", "security_id", "observation_date", *state_fields}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"missing security-master fields: {sorted(missing)}")

    data = observations.copy()
    data["observation_date"] = pd.to_datetime(data["observation_date"], errors="coerce")
    if data["observation_date"].isna().any():
        raise ValueError("observation_date contains null or invalid values")
    if data[["listing_id", "security_id"]].isna().any().any():
        raise ValueError("listing_id/security_id cannot be null")

    duplicates = data.duplicated(["observation_date", "listing_id"], keep=False)
    if duplicates.any():
        raise ValueError("duplicate listing_id within a snapshot")

    snapshot_dates = sorted(data["observation_date"].unique())
    active: dict[str, dict[str, object]] = {}
    intervals: list[dict[str, object]] = []

    def close_interval(listing_id: str, valid_to: pd.Timestamp) -> None:
        item = active.pop(listing_id)
        item["valid_to_exclusive"] = valid_to
        intervals.append(item)

    for raw_date in snapshot_dates:
        date = pd.Timestamp(raw_date)
        snapshot = data.loc[data["observation_date"] == date]
        current_ids = set(snapshot["listing_id"].astype(str))

        for listing_id in list(active):
            if listing_id not in current_ids:
                close_interval(listing_id, date)

        for _, row in snapshot.iterrows():
            listing_id = str(row["listing_id"])
            payload = _state_payload(row, state_fields)
            fingerprint = _state_fingerprint(payload)
            current = active.get(listing_id)

            if current is not None and current["state_fingerprint"] != fingerprint:
                close_interval(listing_id, date)
                current = None

            if current is None:
                current = {
                    "listing_id": listing_id,
                    "security_id": str(row["security_id"]),
                    "valid_from": date,
                    "valid_to_exclusive": pd.NaT,
                    "first_observed_date": date,
                    "last_observed_date": date,
                    "snapshot_count": 1,
                    "state_fingerprint": fingerprint,
                    **payload,
                }
                active[listing_id] = current
            else:
                if current["security_id"] != str(row["security_id"]):
                    raise ValueError(f"security_id drift inside listing_id {listing_id}")
                current["last_observed_date"] = date
                current["snapshot_count"] = int(str(current["snapshot_count"])) + 1

    intervals.extend(active.values())
    out = pd.DataFrame(intervals)
    if out.empty:
        return out

    out = out.sort_values(["listing_id", "valid_from"], kind="stable").reset_index(drop=True)
    validate_security_master_scd2(out)
    return out


def validate_security_master_scd2(history: pd.DataFrame) -> None:
    required = {"listing_id", "valid_from", "valid_to_exclusive"}
    missing = required - set(history.columns)
    if missing:
        raise ValueError(f"missing SCD2 fields: {sorted(missing)}")

    data = history.copy()
    data["valid_from"] = pd.to_datetime(data["valid_from"], errors="coerce")
    data["valid_to_exclusive"] = pd.to_datetime(data["valid_to_exclusive"], errors="coerce")
    if data["valid_from"].isna().any():
        raise ValueError("valid_from cannot be null")

    for listing_id, group in data.groupby("listing_id", sort=False):
        ordered = group.sort_values("valid_from", kind="stable")
        previous_end: pd.Timestamp | None = None
        open_interval_seen = False
        for row in ordered.itertuples(index=False):
            start = pd.Timestamp(row.valid_from)
            end = row.valid_to_exclusive
            if previous_end is not None and start < previous_end:
                raise ValueError(f"overlapping SCD2 intervals for {listing_id}")
            if open_interval_seen:
                raise ValueError(f"open SCD2 interval is not last for {listing_id}")
            if pd.isna(end):
                open_interval_seen = True
                previous_end = None
            else:
                end_ts = pd.Timestamp(end)
                if end_ts <= start:
                    raise ValueError(f"non-positive SCD2 interval for {listing_id}")
                previous_end = end_ts
