from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FeatureMartAudit:
    rows: int
    securities: int
    first_date: pd.Timestamp | None
    last_date: pd.Timestamp | None
    leakage_rows: int
    duplicate_rows: int


def point_in_time_asof_join(
    observations: pd.DataFrame,
    fundamentals: pd.DataFrame,
    *,
    entity_column: str = "issuer_id",
    observation_date_column: str = "feature_date",
) -> pd.DataFrame:
    """Join each observation to the latest fundamental value actually available.

    Fundamentals must carry both ``reference_date`` and ``available_from``. The
    join keys on information availability, never on the accounting reference date.
    """

    obs_required = {entity_column, observation_date_column}
    fund_required = {entity_column, "reference_date", "available_from"}
    missing_obs = obs_required - set(observations.columns)
    missing_fund = fund_required - set(fundamentals.columns)
    if missing_obs:
        raise ValueError(f"missing observation fields: {sorted(missing_obs)}")
    if missing_fund:
        raise ValueError(f"missing fundamental fields: {sorted(missing_fund)}")

    left = observations.copy()
    right = fundamentals.copy()
    left[observation_date_column] = pd.to_datetime(left[observation_date_column], errors="coerce")
    right["reference_date"] = pd.to_datetime(right["reference_date"], errors="coerce")
    right["available_from"] = pd.to_datetime(right["available_from"], errors="coerce")
    if left[observation_date_column].isna().any():
        raise ValueError("invalid observation dates")
    if right[["reference_date", "available_from"]].isna().any().any():
        raise ValueError("invalid fundamental reference/availability dates")
    if (right["available_from"] < right["reference_date"]).any():
        raise ValueError("fundamental available_from cannot precede reference_date")

    left = left.reset_index(names="__row_id")
    outputs: list[pd.DataFrame] = []
    for entity, obs_group in left.groupby(entity_column, sort=False, dropna=False):
        fund_group = right.loc[right[entity_column].eq(entity)].copy()
        if fund_group.empty:
            empty = obs_group.copy()
            for column in right.columns:
                if column not in empty.columns:
                    empty[column] = pd.NA
            outputs.append(empty)
            continue
        fund_group = fund_group.sort_values(
            ["available_from", "reference_date"], kind="stable"
        )
        obs_group = obs_group.sort_values(observation_date_column, kind="stable")
        merged = pd.merge_asof(
            obs_group,
            fund_group.drop(columns=[entity_column]),
            left_on=observation_date_column,
            right_on="available_from",
            direction="backward",
            allow_exact_matches=True,
        )
        outputs.append(merged)

    if not outputs:
        return left.drop(columns="__row_id")
    out = pd.concat(outputs, ignore_index=True)
    out = out.sort_values("__row_id", kind="stable").drop(columns="__row_id").reset_index(drop=True)
    known = out["available_from"].notna()
    leakage = known & (
        pd.to_datetime(out["available_from"]) > pd.to_datetime(out[observation_date_column])
    )
    if leakage.any():
        raise RuntimeError("point-in-time asof join produced future information")
    return out


def build_price_features_pit(prices: pd.DataFrame) -> tuple[pd.DataFrame, FeatureMartAudit]:
    """Build transparent daily price/liquidity features using only t-1 and older data.

    This produces baseline features, not alpha claims. All rolling inputs are
    shifted one trading observation so a feature dated *t* can be consumed before
    observing the close/volume of *t*.
    """

    required = {"security_id", "price_date", "close_price", "financial_volume"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"missing price feature fields: {sorted(missing)}")
    frame = prices.copy()
    frame["security_id"] = frame["security_id"].astype(str).str.strip().str.upper()
    frame["price_date"] = pd.to_datetime(frame["price_date"], errors="coerce")
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    frame["financial_volume"] = pd.to_numeric(frame["financial_volume"], errors="coerce")
    invalid = (
        frame[["price_date", "close_price", "financial_volume"]].isna().any(axis=1)
        | (frame["close_price"] <= 0)
        | (frame["financial_volume"] < 0)
    )
    if invalid.any():
        raise ValueError(f"invalid price feature rows: {int(invalid.sum())}")
    duplicates = frame.duplicated(["security_id", "price_date"])
    if duplicates.any():
        raise ValueError("duplicate security/date rows in price feature input")

    frame = frame.sort_values(["security_id", "price_date"], kind="stable").reset_index(drop=True)
    grouped = frame.groupby("security_id", sort=False)
    frame["one_day_return"] = grouped["close_price"].pct_change(fill_method=None)

    # Lag every current-day market observable by one row before any rolling
    # aggregation, preventing a close-to-close feature from seeing today's close.
    lagged_close = grouped["close_price"].shift(1)
    lagged_return = grouped["one_day_return"].shift(1)
    lagged_volume = grouped["financial_volume"].shift(1)

    frame["momentum_21"] = lagged_close / grouped["close_price"].shift(22) - 1.0
    frame["momentum_63"] = lagged_close / grouped["close_price"].shift(64) - 1.0
    frame["volatility_21"] = (
        lagged_return.groupby(frame["security_id"], sort=False)
        .rolling(21, min_periods=21)
        .std()
        .reset_index(level=0, drop=True)
    )
    frame["adv_21"] = (
        lagged_volume.groupby(frame["security_id"], sort=False)
        .rolling(21, min_periods=21)
        .mean()
        .reset_index(level=0, drop=True)
    )
    frame["feature_date"] = frame["price_date"]
    frame["source_max_date"] = grouped["price_date"].shift(1)

    feature_columns = [
        "security_id",
        "feature_date",
        "source_max_date",
        "momentum_21",
        "momentum_63",
        "volatility_21",
        "adv_21",
    ]
    out = frame[feature_columns].copy()
    leakage = out["source_max_date"].notna() & (out["source_max_date"] >= out["feature_date"])
    audit = FeatureMartAudit(
        rows=len(out),
        securities=out["security_id"].nunique(),
        first_date=out["feature_date"].min() if len(out) else None,
        last_date=out["feature_date"].max() if len(out) else None,
        leakage_rows=int(leakage.sum()),
        duplicate_rows=int(out.duplicated(["security_id", "feature_date"]).sum()),
    )
    if audit.leakage_rows or audit.duplicate_rows:
        raise RuntimeError("feature mart failed point-in-time invariants")
    return out.reset_index(drop=True), audit
