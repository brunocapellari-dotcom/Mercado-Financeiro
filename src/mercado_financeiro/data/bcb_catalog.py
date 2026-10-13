from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BCBSeries(str, Enum):
    SELIC_TARGET = "selic_target"
    SELIC_DAILY = "selic_daily"
    IPCA_MONTHLY = "ipca_monthly"
    USD_BRL_SELL = "usd_brl_sell"
    USD_BRL_BUY = "usd_brl_buy"


@dataclass(frozen=True)
class BCBSeriesContract:
    key: BCBSeries
    sgs_code: int
    name: str
    periodicity: str
    unit: str
    publication_lag_days: int | None = None


# Codes/names are from the official BCB SGS catalogue. Publication lags are
# deliberately left unset until each release calendar/vintage behavior is audited.
BCB_SERIES_CATALOG: dict[BCBSeries, BCBSeriesContract] = {
    BCBSeries.SELIC_TARGET: BCBSeriesContract(
        key=BCBSeries.SELIC_TARGET,
        sgs_code=432,
        name="Taxa de juros - Meta Selic definida pelo Copom",
        periodicity="daily",
        unit="percent_per_year",
    ),
    BCBSeries.SELIC_DAILY: BCBSeriesContract(
        key=BCBSeries.SELIC_DAILY,
        sgs_code=11,
        name="Taxa de juros - Selic",
        periodicity="daily",
        unit="percent_per_day",
    ),
    BCBSeries.IPCA_MONTHLY: BCBSeriesContract(
        key=BCBSeries.IPCA_MONTHLY,
        sgs_code=433,
        name="Índice Nacional de Preços ao Consumidor Amplo (IPCA)",
        periodicity="monthly",
        unit="monthly_percent_change",
    ),
    BCBSeries.USD_BRL_SELL: BCBSeriesContract(
        key=BCBSeries.USD_BRL_SELL,
        sgs_code=1,
        name="Taxa de câmbio - Livre - Dólar americano (venda)",
        periodicity="daily",
        unit="brl_per_usd",
    ),
    BCBSeries.USD_BRL_BUY: BCBSeriesContract(
        key=BCBSeries.USD_BRL_BUY,
        sgs_code=10813,
        name="Taxa de câmbio - Livre - Dólar americano (compra)",
        periodicity="daily",
        unit="brl_per_usd",
    ),
}


def get_bcb_series_contract(series: BCBSeries | str) -> BCBSeriesContract:
    key = series if isinstance(series, BCBSeries) else BCBSeries(series)
    return BCB_SERIES_CATALOG[key]
