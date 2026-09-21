from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from .quality import DataQualityContract, DataQualityResult, evaluate_data_quality


@dataclass(frozen=True)
class FinancialSourceContract:
    """Project-owned data contract inspired by data-quality frameworks.

    The contract stays dependency-light and keeps financial point-in-time rules
    explicit instead of introducing a second data-transformation authority.
    """

    name: str
    quality: DataQualityContract
    reference_column: str | None = None
    availability_column: str | None = None
    numeric_ranges: Mapping[str, tuple[float | None, float | None]] | None = None

    def evaluate(
        self,
        frame: pd.DataFrame,
        *,
        as_of: pd.Timestamp | None = None,
        minimum_rows: int = 1,
    ) -> DataQualityResult:
        base = evaluate_data_quality(
            frame,
            self.quality,
            as_of=as_of,
            minimum_rows=minimum_rows,
            numeric_ranges=self.numeric_ranges,
        )
        violations = list(base.violations)
        metrics = dict(base.metrics)

        if self.reference_column is not None or self.availability_column is not None:
            required = {
                column
                for column in (self.reference_column, self.availability_column)
                if column is not None
            }
            missing = required - set(frame.columns)
            if missing:
                violations.append("timing_columns_missing=" + ",".join(sorted(missing)))
            elif self.reference_column and self.availability_column:
                reference = pd.to_datetime(
                    frame[self.reference_column], errors="coerce", utc=True
                )
                available = pd.to_datetime(
                    frame[self.availability_column], errors="coerce", utc=True
                )
                invalid = int((reference.isna() | available.isna()).sum())
                early = int(
                    (
                        reference.notna()
                        & available.notna()
                        & (available < reference)
                    ).sum()
                )
                metrics["invalid_information_timestamps"] = float(invalid)
                metrics["availability_before_reference"] = float(early)
                if invalid:
                    violations.append(f"invalid_information_timestamps={invalid}")
                if early:
                    violations.append(f"availability_before_reference={early}")
                if as_of is not None:
                    cutoff = pd.Timestamp(as_of)
                    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
                        raise ValueError("as_of must be timezone-aware")
                    cutoff = cutoff.tz_convert("UTC")
                    future = int((available.notna() & (available > cutoff)).sum())
                    metrics["future_information_rows"] = float(future)
                    if future:
                        violations.append(f"future_information_rows={future}")

        return DataQualityResult(
            passed=not violations,
            violations=tuple(violations),
            metrics=tuple(sorted(metrics.items())),
        )


COTAHIST_CONTRACT = FinancialSourceContract(
    name="COTAHIST",
    quality=DataQualityContract(
        name="COTAHIST",
        required_columns=(
            "trade_date",
            "ticker",
            "security_id",
            "close_price",
            "quotation_factor",
            "trades",
            "quantity",
            "financial_volume",
        ),
        not_null_columns=("trade_date", "ticker", "security_id", "close_price"),
        unique_key=("trade_date", "security_id"),
    ),
    numeric_ranges={
        "close_price": (0.0, None),
        "quotation_factor": (1.0, None),
        "trades": (0.0, None),
        "quantity": (0.0, None),
        "financial_volume": (0.0, None),
    },
)

BVBG028_CONTRACT = FinancialSourceContract(
    name="BVBG028",
    quality=DataQualityContract(
        name="BVBG028",
        required_columns=(
            "observation_date",
            "listing_id",
            "security_id",
            "instrument_id",
            "ticker",
            "isin",
            "market",
            "segment",
            "package_created_at",
        ),
        not_null_columns=(
            "observation_date",
            "listing_id",
            "security_id",
            "ticker",
            "isin",
        ),
        unique_key=("observation_date", "listing_id"),
    ),
)


B3_LENDING_OPEN_POSITION_CONTRACT = FinancialSourceContract(
    name="B3_LENDING_OPEN_POSITION",
    quality=DataQualityContract(
        name="B3_LENDING_OPEN_POSITION",
        required_columns=(
            "reference_date",
            "ticker",
            "isin",
            "security_id",
            "identity_status",
            "asset",
            "balance_quantity",
            "trade_average_price",
            "price_factor",
            "balance_value",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "reference_date",
            "ticker",
            "identity_status",
            "asset",
            "balance_quantity",
            "price_factor",
            "balance_value",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
    ),
    reference_column="reference_date",
    availability_column="available_from",
    numeric_ranges={
        "balance_quantity": (0.0, None),
        "trade_average_price": (0.0, None),
        "price_factor": (0.000000000001, None),
        "balance_value": (0.0, None),
    },
)

B3_LOAN_BALANCE_CONTRACT = FinancialSourceContract(
    name="B3_LOAN_BALANCE",
    quality=DataQualityContract(
        name="B3_LOAN_BALANCE",
        required_columns=(
            "reference_date",
            "ticker",
            "isin",
            "security_id",
            "asset",
            "market_name",
            "contracts_day",
            "shares_day",
            "contracts_value_day",
            "donor_min_rate",
            "donor_average_rate",
            "donor_max_rate",
            "taker_min_rate",
            "taker_average_rate",
            "taker_max_rate",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "reference_date",
            "ticker",
            "isin",
            "security_id",
            "asset",
            "market_name",
            "contracts_day",
            "shares_day",
            "contracts_value_day",
            "donor_min_rate",
            "donor_average_rate",
            "donor_max_rate",
            "taker_min_rate",
            "taker_average_rate",
            "taker_max_rate",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
    ),
    reference_column="reference_date",
    availability_column="available_from",
    numeric_ranges={
        "contracts_day": (0.0, None),
        "shares_day": (0.0, None),
        "contracts_value_day": (0.0, None),
    },
)

CVM_FUNDAMENTALS_CONTRACT = FinancialSourceContract(
    name="CVM_FUNDAMENTALS",
    quality=DataQualityContract(
        name="CVM_FUNDAMENTALS",
        required_columns=(
            "issuer_id",
            "metric",
            "value",
            "reference_date",
            "available_from",
            "filing_version",
            "source",
        ),
        not_null_columns=(
            "issuer_id",
            "metric",
            "value",
            "reference_date",
            "available_from",
            "filing_version",
            "source",
        ),
        unique_key=(
            "issuer_id",
            "metric",
            "reference_date",
            "filing_version",
            "source",
        ),
    ),
    reference_column="reference_date",
    availability_column="available_from",
)

BCB_CONTRACT = FinancialSourceContract(
    name="BCB",
    quality=DataQualityContract(
        name="BCB",
        required_columns=(
            "reference_date",
            "value",
            "series_code",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "reference_date",
            "value",
            "series_code",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        unique_key=("reference_date", "series_code"),
    ),
    reference_column="reference_date",
    availability_column="available_from",
)

NEFIN_CONTRACT = FinancialSourceContract(
    name="NEFIN",
    quality=DataQualityContract(
        name="NEFIN",
        required_columns=(
            "reference_date",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "reference_date",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        unique_key=("reference_date",),
    ),
    reference_column="reference_date",
    availability_column="available_from",
)


CVM_FUND_DAILY_CONTRACT = FinancialSourceContract(
    name="CVM_FUND_DAILY",
    quality=DataQualityContract(
        name="CVM_FUND_DAILY",
        required_columns=(
            "fund_id",
            "reference_date",
            "total_portfolio",
            "nav",
            "quota_value",
            "inflows",
            "outflows",
            "shareholders",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "fund_id",
            "reference_date",
            "nav",
            "quota_value",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        unique_key=("fund_id", "reference_date"),
    ),
    reference_column="reference_date",
    availability_column="available_from",
    numeric_ranges={
        "total_portfolio": (0.0, None),
        "nav": (0.0, None),
        "quota_value": (0.0, None),
        "inflows": (0.0, None),
        "outflows": (0.0, None),
        "shareholders": (0.0, None),
    },
)


CVM_FUND_HOLDINGS_CONTRACT = FinancialSourceContract(
    name="CVM_FUND_HOLDINGS",
    quality=DataQualityContract(
        name="CVM_FUND_HOLDINGS",
        required_columns=(
            "fund_id",
            "reference_date",
            "block",
            "asset_code",
            "source_member",
            "confidential_positions_present",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "fund_id",
            "reference_date",
            "block",
            "source_member",
            "confidential_positions_present",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
    ),
    reference_column="reference_date",
    availability_column="available_from",
)

CVM_FUND_CODED_ASSET_AGGREGATE_CONTRACT = FinancialSourceContract(
    name="CVM_FUND_CODED_ASSET_AGGREGATE",
    quality=DataQualityContract(
        name="CVM_FUND_CODED_ASSET_AGGREGATE",
        required_columns=(
            "reference_date",
            "asset_code",
            "quantity",
            "market_value",
            "fund_count",
            "coverage_status",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        not_null_columns=(
            "reference_date",
            "asset_code",
            "fund_count",
            "coverage_status",
            "available_from",
            "source_retrieved_at",
            "source_sha256",
        ),
        unique_key=("reference_date", "asset_code"),
    ),
    reference_column="reference_date",
    availability_column="available_from",
    numeric_ranges={"fund_count": (0.0, None)},
)

CORPORATE_DATA_CONTRACT = FinancialSourceContract(
    name="CORPORATE_DATA",
    quality=CVM_FUNDAMENTALS_CONTRACT.quality,
    reference_column="reference_date",
    availability_column="available_from",
)

MARKET_SERIES_CONTRACT = FinancialSourceContract(
    name="MARKET_SERIES",
    quality=DataQualityContract(
        name="MARKET_SERIES",
        required_columns=(
            "instrument",
            "reference_date",
            "value",
            "available_from",
            "source",
        ),
        not_null_columns=(
            "instrument",
            "reference_date",
            "value",
            "available_from",
            "source",
        ),
        unique_key=("instrument", "reference_date", "source"),
    ),
    reference_column="reference_date",
    availability_column="available_from",
)

SOURCE_CONTRACTS: Mapping[str, FinancialSourceContract] = {
    contract.name: contract
    for contract in (
        COTAHIST_CONTRACT,
        BVBG028_CONTRACT,
        B3_LENDING_OPEN_POSITION_CONTRACT,
        B3_LOAN_BALANCE_CONTRACT,
        CVM_FUNDAMENTALS_CONTRACT,
        CVM_FUND_DAILY_CONTRACT,
        CVM_FUND_HOLDINGS_CONTRACT,
        CVM_FUND_CODED_ASSET_AGGREGATE_CONTRACT,
        CORPORATE_DATA_CONTRACT,
        BCB_CONTRACT,
        NEFIN_CONTRACT,
        MARKET_SERIES_CONTRACT,
    )
}


def get_financial_source_contract(name: str) -> FinancialSourceContract:
    key = str(name).strip().upper()
    try:
        return SOURCE_CONTRACTS[key]
    except KeyError as exc:
        raise KeyError(f"unknown financial source contract: {name}") from exc
