from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    INTEREST_ON_EQUITY = "interest_on_equity"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    BONUS = "bonus"
    SUBSCRIPTION = "subscription"
    MERGER = "merger"
    SPIN_OFF = "spin_off"
    OTHER = "other"


_MECHANICAL_ACTIONS = frozenset(
    {
        CorporateActionType.CASH_DIVIDEND.value,
        CorporateActionType.INTEREST_ON_EQUITY.value,
        CorporateActionType.SPLIT.value,
        CorporateActionType.REVERSE_SPLIT.value,
        CorporateActionType.BONUS.value,
    }
)


@dataclass(frozen=True)
class TotalReturnAudit:
    rows: int
    event_days: int
    cash_event_days: int
    share_ratio_event_days: int
    blocked_complex_event_days: int
    invalid_rows: int


def normalize_corporate_actions(events: pd.DataFrame) -> pd.DataFrame:
    """Validate the canonical corporate-action contract.

    Required columns are security identity, ex/effective date, type and
    information-availability timestamp. Cash amounts are expressed per pre-event
    share. ``share_ratio`` is new shares per old share (2.0 for a 2-for-1 split,
    0.5 for a 1-for-2 reverse split). Complex actions remain explicit and are not
    approximated as ordinary splits/cash distributions.
    """

    required = {"security_id", "effective_date", "action_type", "available_from"}
    missing = required - set(events.columns)
    if missing:
        raise ValueError(f"missing corporate-action fields: {sorted(missing)}")

    out = events.copy()
    out["security_id"] = out["security_id"].astype(str).str.strip().str.upper()
    if out["security_id"].eq("").any():
        raise ValueError("security_id cannot be empty")
    out["effective_date"] = pd.to_datetime(out["effective_date"], errors="coerce")
    out["available_from"] = pd.to_datetime(out["available_from"], errors="coerce", utc=True)
    if out[["effective_date", "available_from"]].isna().any().any():
        raise ValueError("invalid effective_date/available_from")

    valid_types = {item.value for item in CorporateActionType}
    out["action_type"] = out["action_type"].astype(str).str.strip().str.lower()
    unknown = sorted(set(out["action_type"]) - valid_types)
    if unknown:
        raise ValueError(f"unknown corporate action types: {unknown[:10]}")

    if "cash_per_share" not in out.columns:
        out["cash_per_share"] = 0.0
    if "share_ratio" not in out.columns:
        out["share_ratio"] = 1.0
    out["cash_per_share"] = pd.to_numeric(out["cash_per_share"], errors="coerce").fillna(0.0)
    out["share_ratio"] = pd.to_numeric(out["share_ratio"], errors="coerce").fillna(1.0)
    if (out["cash_per_share"] < 0).any():
        raise ValueError("cash_per_share cannot be negative")
    if (out["share_ratio"] <= 0).any():
        raise ValueError("share_ratio must be positive")

    cash_types = out["action_type"].isin(
        [CorporateActionType.CASH_DIVIDEND.value, CorporateActionType.INTEREST_ON_EQUITY.value]
    )
    ratio_types = out["action_type"].isin(
        [
            CorporateActionType.SPLIT.value,
            CorporateActionType.REVERSE_SPLIT.value,
            CorporateActionType.BONUS.value,
        ]
    )
    if (out.loc[cash_types, "cash_per_share"] <= 0).any():
        raise ValueError("cash distributions require positive cash_per_share")
    if (~out.loc[cash_types, "share_ratio"].eq(1.0)).any():
        raise ValueError("cash-only actions must use share_ratio=1")
    if (~out.loc[ratio_types, "cash_per_share"].eq(0.0)).any():
        raise ValueError("share-ratio-only actions must use cash_per_share=0")
    if out.loc[ratio_types, "share_ratio"].eq(1.0).any():
        raise ValueError("split/bonus actions require share_ratio different from 1")

    out["mechanical_total_return_supported"] = out["action_type"].isin(_MECHANICAL_ACTIONS)
    out["event_id"] = out.get("event_id", pd.Series(index=out.index, dtype="object"))
    missing_event_id = out["event_id"].isna() | out["event_id"].astype(str).str.strip().eq("")
    if missing_event_id.any():
        generated = (
            out.loc[missing_event_id, "security_id"]
            + "|"
            + out.loc[missing_event_id, "effective_date"].dt.strftime("%Y-%m-%d")
            + "|"
            + out.loc[missing_event_id, "action_type"]
            + "|"
            + out.loc[missing_event_id].groupby(
                ["security_id", "effective_date", "action_type"], sort=False
            ).cumcount().astype(str)
        )
        out.loc[missing_event_id, "event_id"] = generated
    if out["event_id"].duplicated().any():
        raise ValueError("duplicate corporate-action event_id")

    return out.sort_values(["security_id", "effective_date", "event_id"], kind="stable").reset_index(drop=True)


def compute_total_returns(
    prices: pd.DataFrame,
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, TotalReturnAudit]:
    """Compute one-day total returns while failing closed on complex actions.

    Price rows must be unadjusted closes. On a mechanical event day the wealth
    numerator is ``close_t * cumulative_share_ratio + cumulative_cash_per_old_share``.
    Subscriptions, mergers, spin-offs and unknown/other complex actions are marked
    blocked rather than being silently approximated.
    """

    required = {"security_id", "price_date", "close_price"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"missing price fields: {sorted(missing)}")
    frame = prices.copy()
    frame["security_id"] = frame["security_id"].astype(str).str.strip().str.upper()
    frame["price_date"] = pd.to_datetime(frame["price_date"], errors="coerce")
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    invalid = frame[["price_date", "close_price"]].isna().any(axis=1) | (frame["close_price"] <= 0)
    if invalid.any():
        raise ValueError(f"invalid price rows: {int(invalid.sum())}")
    if frame.duplicated(["security_id", "price_date"]).any():
        raise ValueError("duplicate security/date price rows")

    actions = normalize_corporate_actions(events)
    grouped_actions: dict[tuple[str, pd.Timestamp], dict[str, object]] = {}
    for (security_id, effective_date), group in actions.groupby(
        ["security_id", "effective_date"], sort=False
    ):
        complex_actions = group.loc[~group["mechanical_total_return_supported"]]
        grouped_actions[(str(security_id), pd.Timestamp(effective_date))] = {
            "cash": float(group.loc[group["mechanical_total_return_supported"], "cash_per_share"].sum()),
            "share_ratio": float(
                group.loc[group["mechanical_total_return_supported"], "share_ratio"].prod()
            ),
            "blocked": not complex_actions.empty,
            "event_count": len(group),
            "types": ";".join(sorted(set(group["action_type"].astype(str)))),
        }

    frame = frame.sort_values(["security_id", "price_date"], kind="stable").reset_index(drop=True)
    frame["previous_close"] = frame.groupby("security_id", sort=False)["close_price"].shift(1)
    frame["event_cash_per_old_share"] = 0.0
    frame["event_share_ratio"] = 1.0
    frame["corporate_action_types"] = ""
    frame["total_return_status"] = "resolved"
    event_days = cash_days = ratio_days = blocked_days = 0

    for index, row in frame.iterrows():
        event = grouped_actions.get((row["security_id"], row["price_date"]))
        if event is None:
            continue
        event_days += 1
        frame.at[index, "event_cash_per_old_share"] = event["cash"]
        frame.at[index, "event_share_ratio"] = event["share_ratio"]
        frame.at[index, "corporate_action_types"] = event["types"]
        if float(str(event["cash"])) > 0:
            cash_days += 1
        if float(str(event["share_ratio"])) != 1.0:
            ratio_days += 1
        if bool(event["blocked"]):
            blocked_days += 1
            frame.at[index, "total_return_status"] = "blocked_complex_corporate_action"

    previous = frame["previous_close"]
    numerator = (
        frame["close_price"] * frame["event_share_ratio"]
        + frame["event_cash_per_old_share"]
    )
    frame["raw_price_return"] = frame["close_price"] / previous - 1.0
    frame["total_return"] = numerator / previous - 1.0
    first_observation = previous.isna()
    frame.loc[first_observation, ["raw_price_return", "total_return"]] = pd.NA
    blocked = frame["total_return_status"].ne("resolved")
    frame.loc[blocked, "total_return"] = pd.NA

    audit = TotalReturnAudit(
        rows=len(frame),
        event_days=event_days,
        cash_event_days=cash_days,
        share_ratio_event_days=ratio_days,
        blocked_complex_event_days=blocked_days,
        invalid_rows=0,
    )
    return frame, audit
