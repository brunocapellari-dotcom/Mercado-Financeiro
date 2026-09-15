from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .historical import VintageMode


class SourceTier(str, Enum):
    PRIMARY_OFFICIAL = "primary_official"
    SPECIALIZED_BENCHMARK = "specialized_benchmark"
    LICENSED_VENDOR = "licensed_vendor"
    BROKER = "broker"
    NEWS = "news"


@dataclass(frozen=True)
class SourceContract:
    name: str
    tier: SourceTier
    purpose: str
    hosts: frozenset[str]
    default_vintage_mode: VintageMode | None
    live_capable: bool
    credentials_required: bool
    canonical: bool = True


SOURCE_REGISTRY: dict[str, SourceContract] = {
    "B3": SourceContract(
        name="B3",
        tier=SourceTier.PRIMARY_OFFICIAL,
        purpose="market data, instruments, corporate actions and exchange reference data",
        hosts=frozenset({
            "www.b3.com.br",
            "b3.com.br",
            "bvmf.bmfbovespa.com.br",
            "sistemaswebb3-listados.b3.com.br",
        }),
        default_vintage_mode=VintageMode.EXACT_VINTAGE,
        live_capable=True,
        credentials_required=False,
    ),
    "CVM": SourceContract(
        name="CVM",
        tier=SourceTier.PRIMARY_OFFICIAL,
        purpose="issuer filings, fundamentals and filing vintages",
        hosts=frozenset({"dados.cvm.gov.br"}),
        default_vintage_mode=VintageMode.PUBLICATION_GATED,
        live_capable=False,
        credentials_required=False,
    ),
    "BCB": SourceContract(
        name="BCB",
        tier=SourceTier.PRIMARY_OFFICIAL,
        purpose="macro, rates, FX and monetary/financial series",
        hosts=frozenset({"api.bcb.gov.br", "olinda.bcb.gov.br", "dadosabertos.bcb.gov.br"}),
        default_vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
        live_capable=False,
        credentials_required=False,
    ),
    "ANBIMA": SourceContract(
        name="ANBIMA",
        tier=SourceTier.PRIMARY_OFFICIAL,
        purpose="fixed-income and capital-market reference/market datasets",
        hosts=frozenset({"api.anbima.com.br", "api-sandbox.anbima.com.br", "developers.anbima.com.br"}),
        default_vintage_mode=VintageMode.CONSERVATIVE_RETRIEVAL,
        live_capable=False,
        credentials_required=True,
    ),
    "NEFIN": SourceContract(
        name="NEFIN",
        tier=SourceTier.SPECIALIZED_BENCHMARK,
        purpose="independent Brazilian factor benchmark and reconciliation",
        hosts=frozenset({"nefin.com.br", "www.nefin.com.br"}),
        default_vintage_mode=VintageMode.BENCHMARK_ONLY,
        live_capable=False,
        credentials_required=False,
    ),
    "BTG_DATA_SERVICES": SourceContract(
        name="BTG_DATA_SERVICES",
        tier=SourceTier.LICENSED_VENDOR,
        purpose="licensed real-time/reference market data when contracted",
        hosts=frozenset(),
        default_vintage_mode=None,
        live_capable=True,
        credentials_required=True,
        canonical=False,
    ),
    "DATABENTO": SourceContract(
        name="DATABENTO",
        tier=SourceTier.LICENSED_VENDOR,
        purpose="licensed market-data adapter when coverage/licensing justify it",
        hosts=frozenset(),
        default_vintage_mode=None,
        live_capable=True,
        credentials_required=True,
        canonical=False,
    ),
    "BROKER": SourceContract(
        name="BROKER",
        tier=SourceTier.BROKER,
        purpose="orders, fills, balances, positions and optional broker market data",
        hosts=frozenset(),
        default_vintage_mode=None,
        live_capable=True,
        credentials_required=True,
        canonical=False,
    ),
}


def get_source_contract(name: str) -> SourceContract:
    try:
        return SOURCE_REGISTRY[name.strip().upper()]
    except KeyError as exc:
        raise KeyError(f"unregistered market source: {name}") from exc
