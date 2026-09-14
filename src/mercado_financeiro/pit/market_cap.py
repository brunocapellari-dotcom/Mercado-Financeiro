from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .shares import shares_outstanding_asof


@dataclass(frozen=True)
class MarketCapResult:
    security_caps: pd.DataFrame
    issuer_caps: pd.DataFrame


def classify_share_class(cfi_code: object) -> str:
    """Map ISO-10962 CFI families to the share buckets reported by CVM DFP.

    Only classes that can be reconciled directly to DFP composition-of-capital are
    admitted. Units, funds, BDRs and other structures remain unsupported instead of
    being forced into an issuer share bucket.
    """
    value = "" if cfi_code is None or pd.isna(cfi_code) else str(cfi_code).upper().strip()
    if value.startswith("ES"):
        return "ordinary"
    if value.startswith("EP"):
        return "preferred"
    return "unsupported"


def resolve_security_issuer_asof(
    security_history: pd.DataFrame,
    ticker_issuer_history: pd.DataFrame,
    asof: str | pd.Timestamp,
) -> pd.DataFrame:
    """Resolve active B3 securities to CVM issuers without future information.

    `ticker_issuer_history` is the normalized historical bridge sourced from FCA or
    another primary source. The bridge is only eligible after `available_from` and
    inside its own validity interval. Ambiguous issuer mappings fail closed.
    """
    sec_required = {
        "security_id",
        "ticker",
        "cfi_code",
        "valid_from",
        "valid_to_exclusive",
    }
    map_required = {
        "ticker",
        "issuer_id",
        "valid_from",
        "valid_to_exclusive",
        "available_from",
    }
    missing_sec = sec_required - set(security_history.columns)
    missing_map = map_required - set(ticker_issuer_history.columns)
    if missing_sec:
        raise ValueError(f"missing security-history fields: {sorted(missing_sec)}")
    if missing_map:
        raise ValueError(f"missing ticker-issuer fields: {sorted(missing_map)}")

    ts = pd.Timestamp(asof)
    securities = security_history.copy()
    mappings = ticker_issuer_history.copy()

    for frame, columns in (
        (securities, ("valid_from", "valid_to_exclusive")),
        (mappings, ("valid_from", "valid_to_exclusive", "available_from")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")

    if securities["valid_from"].isna().any():
        raise ValueError("security valid_from cannot be null")
    if mappings[["valid_from", "available_from"]].isna().any().any():
        raise ValueError("mapping valid_from/available_from cannot be null")

    securities = securities.loc[
        (securities["valid_from"] <= ts)
        & (securities["valid_to_exclusive"].isna() | (ts < securities["valid_to_exclusive"]))
    ].copy()
    mappings = mappings.loc[
        (mappings["valid_from"] <= ts)
        & (mappings["available_from"] <= ts)
        & (mappings["valid_to_exclusive"].isna() | (ts < mappings["valid_to_exclusive"]))
    ].copy()

    if securities.duplicated("security_id", keep=False).any():
        raise ValueError("multiple active security states for the same security_id")

    ambiguous_tickers = mappings.groupby("ticker", dropna=False)["issuer_id"].nunique()
    ambiguous_tickers = set(ambiguous_tickers[ambiguous_tickers > 1].index.astype(str))
    if ambiguous_tickers:
        sample = sorted(ambiguous_tickers)[:10]
        raise ValueError(f"ambiguous active ticker-to-issuer mappings: {sample}")

    mappings = mappings.sort_values(
        ["ticker", "available_from", "valid_from"], kind="stable"
    ).drop_duplicates("ticker", keep="last")

    out = securities.merge(
        mappings[["ticker", "issuer_id", "available_from"]],
        on="ticker",
        how="left",
        validate="many_to_one",
    )
    out["share_class"] = out["cfi_code"].map(classify_share_class)
    out["issuer_resolution_status"] = out["issuer_id"].notna().map(
        {True: "resolved", False: "unresolved_issuer"}
    )

    supported = out.loc[
        (out["issuer_resolution_status"] == "resolved")
        & (out["share_class"].isin(["ordinary", "preferred"]))
    ]
    counts = supported.groupby(["issuer_id", "share_class"])["security_id"].transform("nunique")
    out["class_resolution_status"] = "unsupported_class"
    resolved_index = supported.index
    out.loc[resolved_index, "class_resolution_status"] = "resolved"
    out.loc[resolved_index[counts.to_numpy() > 1], "class_resolution_status"] = (
        "ambiguous_multiple_securities"
    )
    out.loc[out["issuer_id"].isna(), "class_resolution_status"] = "unresolved_issuer"
    return out.reset_index(drop=True)


def compute_market_cap_asof(
    prices: pd.DataFrame,
    shares_history: pd.DataFrame,
    security_bridge: pd.DataFrame,
    asof: str | pd.Timestamp,
) -> MarketCapResult:
    """Compute conservative security- and issuer-level market cap at one date.

    The function never allocates aggregate preferred shares across multiple preferred
    securities. An issuer market cap is marked complete only when every non-zero DFP
    share bucket is represented by exactly one resolved security with a valid price.
    """
    price_required = {"security_id", "price_date", "close_price"}
    bridge_required = {
        "security_id",
        "issuer_id",
        "share_class",
        "issuer_resolution_status",
        "class_resolution_status",
    }
    missing_price = price_required - set(prices.columns)
    missing_bridge = bridge_required - set(security_bridge.columns)
    if missing_price:
        raise ValueError(f"missing price fields: {sorted(missing_price)}")
    if missing_bridge:
        raise ValueError(f"missing bridge fields: {sorted(missing_bridge)}")

    ts = pd.Timestamp(asof)
    price_frame = prices.copy()
    price_frame["price_date"] = pd.to_datetime(price_frame["price_date"], errors="coerce")
    price_frame["close_price"] = pd.to_numeric(price_frame["close_price"], errors="coerce")
    if price_frame[["price_date", "close_price"]].isna().any().any():
        raise ValueError("price_date/close_price contains null or invalid values")
    if (price_frame["close_price"] <= 0).any():
        raise ValueError("close_price must be positive")

    price_frame = price_frame.loc[price_frame["price_date"] == ts].copy()
    if price_frame.duplicated("security_id", keep=False).any():
        raise ValueError("duplicate security prices at asof")

    shares = shares_outstanding_asof(shares_history, ts)
    if shares.empty:
        empty = pd.DataFrame()
        return MarketCapResult(security_caps=empty, issuer_caps=empty)

    bridge = security_bridge.copy()
    bridge = bridge.loc[
        (bridge["issuer_resolution_status"] == "resolved")
        & (bridge["class_resolution_status"] == "resolved")
        & (bridge["share_class"].isin(["ordinary", "preferred"]))
    ].copy()

    joined = bridge.merge(price_frame, on="security_id", how="left", validate="one_to_one")
    joined = joined.merge(
        shares[
            [
                "issuer_id",
                "ordinary_outstanding",
                "preferred_outstanding",
                "available_from",
                "reference_date",
            ]
        ],
        on="issuer_id",
        how="inner",
        validate="many_to_one",
        suffixes=("", "_shares"),
    )

    if joined.empty:
        issuer_rows = shares[["issuer_id"]].copy()
        issuer_rows["asof"] = ts
        issuer_rows["issuer_market_cap"] = pd.NA
        issuer_rows["market_cap_status"] = "unresolved_no_priced_security"
        return MarketCapResult(security_caps=joined, issuer_caps=issuer_rows)

    joined["class_shares_outstanding"] = joined.apply(
        lambda row: (
            row["ordinary_outstanding"]
            if row["share_class"] == "ordinary"
            else row["preferred_outstanding"]
        ),
        axis=1,
    )
    joined["security_market_cap"] = joined["close_price"] * joined["class_shares_outstanding"]
    joined.loc[joined["close_price"].isna(), "security_market_cap"] = pd.NA
    joined["asof"] = ts

    issuer_rows: list[dict[str, object]] = []
    bridge_supported = security_bridge.loc[
        security_bridge["issuer_id"].notna()
        & security_bridge["share_class"].isin(["ordinary", "preferred"])
    ].copy()

    for share_row in shares.itertuples(index=False):
        issuer_id = share_row.issuer_id
        issuer_bridge = bridge_supported.loc[bridge_supported["issuer_id"] == issuer_id]
        priced = joined.loc[joined["issuer_id"] == issuer_id]
        reasons: list[str] = []
        total = 0.0

        for share_class, count in (
            ("ordinary", float(share_row.ordinary_outstanding)),
            ("preferred", float(share_row.preferred_outstanding)),
        ):
            if count == 0:
                continue
            candidates = issuer_bridge.loc[issuer_bridge["share_class"] == share_class]
            resolved = candidates.loc[candidates["class_resolution_status"] == "resolved"]
            if len(candidates) != 1 or len(resolved) != 1:
                reasons.append(f"{share_class}_class_unresolved")
                continue
            security_id = resolved.iloc[0]["security_id"]
            cap_row = priced.loc[priced["security_id"] == security_id]
            if len(cap_row) != 1 or pd.isna(cap_row.iloc[0]["security_market_cap"]):
                reasons.append(f"{share_class}_price_missing")
                continue
            total += float(cap_row.iloc[0]["security_market_cap"])

        complete = not reasons
        issuer_rows.append(
            {
                "issuer_id": issuer_id,
                "asof": ts,
                "issuer_market_cap": total if complete else pd.NA,
                "market_cap_status": "resolved" if complete else ";".join(sorted(reasons)),
                "shares_reference_date": share_row.reference_date,
                "shares_available_from": share_row.available_from,
            }
        )

    issuer_caps = pd.DataFrame(issuer_rows)
    security_columns = [
        "security_id",
        "ticker",
        "issuer_id",
        "share_class",
        "price_date",
        "close_price",
        "class_shares_outstanding",
        "security_market_cap",
        "asof",
    ]
    available_columns = [column for column in security_columns if column in joined.columns]
    return MarketCapResult(
        security_caps=joined[available_columns].reset_index(drop=True),
        issuer_caps=issuer_caps.reset_index(drop=True),
    )
