from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _text(value: str, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


@dataclass(frozen=True)
class Provenance:
    source: str
    reference_time: datetime
    available_from: datetime
    ingestion_time: datetime
    vintage: str
    revision_time: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.source, "source")
        _text(self.vintage, "vintage")
        for name in ("reference_time", "available_from", "ingestion_time"):
            _aware(getattr(self, name), name)
        if self.revision_time is not None:
            _aware(self.revision_time, "revision_time")
        if self.available_from > self.ingestion_time:
            raise ValueError("available_from cannot be after ingestion_time")


@dataclass(frozen=True)
class Asset:
    asset_id: str
    ticker: str
    valid_from: datetime
    valid_to: datetime | None = None
    isin: str | None = None
    issuer_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.asset_id, "asset_id")
        _text(self.ticker, "ticker")
        _aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _aware(self.valid_to, "valid_to")
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to cannot precede valid_from")


@dataclass(frozen=True)
class Price:
    asset_id: str
    observed_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    provenance: Provenance

    def __post_init__(self) -> None:
        _text(self.asset_id, "asset_id")
        _aware(self.observed_at, "observed_at")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be positive")
        if self.volume < 0:
            raise ValueError("volume cannot be negative")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high is below another price field")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low is above another price field")


@dataclass(frozen=True)
class Fundamental:
    issuer_id: str
    metric: str
    value: Decimal
    reference_period_end: datetime
    publication_date: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        _text(self.issuer_id, "issuer_id")
        _text(self.metric, "metric")
        _aware(self.reference_period_end, "reference_period_end")
        _aware(self.publication_date, "publication_date")
        if self.provenance.available_from < self.publication_date:
            raise ValueError("fundamental cannot be available before publication_date")


@dataclass(frozen=True)
class Macro:
    series_id: str
    value: Decimal
    reference_period_end: datetime
    publication_date: datetime
    provenance: Provenance

    def __post_init__(self) -> None:
        _text(self.series_id, "series_id")
        _aware(self.reference_period_end, "reference_period_end")
        _aware(self.publication_date, "publication_date")
        if self.provenance.available_from < self.publication_date:
            raise ValueError("macro observation cannot be available before publication_date")


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    asset_id: str
    action_type: str
    effective_date: datetime
    provenance: Provenance
    ex_date: datetime | None = None
    cash_amount: Decimal | None = None
    ratio: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.action_id, "action_id")
        _text(self.asset_id, "asset_id")
        _text(self.action_type, "action_type")
        _aware(self.effective_date, "effective_date")
        if self.ex_date is not None:
            _aware(self.ex_date, "ex_date")
        if self.cash_amount is not None and self.cash_amount < 0:
            raise ValueError("cash_amount cannot be negative")
        if self.ratio is not None and self.ratio <= 0:
            raise ValueError("ratio must be positive")


@dataclass(frozen=True)
class Feature:
    asset_id: str
    name: str
    value: Decimal
    feature_time: datetime
    source_max_available_from: datetime
    version: str

    def __post_init__(self) -> None:
        _text(self.asset_id, "asset_id")
        _text(self.name, "name")
        _text(self.version, "version")
        _aware(self.feature_time, "feature_time")
        _aware(self.source_max_available_from, "source_max_available_from")
        if self.source_max_available_from > self.feature_time:
            raise ValueError("feature contains future information")


@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy_id: str
    asset_id: str
    generated_at: datetime
    side: Literal["buy", "sell", "flat"]
    strength: Decimal

    def __post_init__(self) -> None:
        _text(self.signal_id, "signal_id")
        _text(self.strategy_id, "strategy_id")
        _text(self.asset_id, "asset_id")
        _aware(self.generated_at, "generated_at")
        if self.strength < -1 or self.strength > 1:
            raise ValueError("strength must be in [-1, 1]")


@dataclass(frozen=True)
class Order:
    order_id: str
    signal_id: str
    asset_id: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    created_at: datetime
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.order_id, "order_id")
        _text(self.signal_id, "signal_id")
        _text(self.asset_id, "asset_id")
        _aware(self.created_at, "created_at")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit_price must be positive")


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    asset_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    occurred_at: datetime
    partial: bool = False

    def __post_init__(self) -> None:
        _text(self.fill_id, "fill_id")
        _text(self.order_id, "order_id")
        _text(self.asset_id, "asset_id")
        _aware(self.occurred_at, "occurred_at")
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")
        if self.fee < 0:
            raise ValueError("fee cannot be negative")


@dataclass(frozen=True)
class Position:
    asset_id: str
    quantity: Decimal
    average_price: Decimal
    market_price: Decimal
    as_of: datetime

    def __post_init__(self) -> None:
        _text(self.asset_id, "asset_id")
        _aware(self.as_of, "as_of")
        if self.market_price <= 0:
            raise ValueError("market_price must be positive")
        if self.quantity == 0 and self.average_price != 0:
            raise ValueError("flat position must have zero average_price")
        if self.quantity != 0 and self.average_price <= 0:
            raise ValueError("open position requires positive average_price")


@dataclass(frozen=True)
class Portfolio:
    portfolio_id: str
    as_of: datetime
    cash: Decimal
    equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal

    def __post_init__(self) -> None:
        _text(self.portfolio_id, "portfolio_id")
        _aware(self.as_of, "as_of")
        if self.equity < 0 or self.gross_exposure < 0:
            raise ValueError("equity and gross_exposure cannot be negative")
