from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Mapping


@dataclass(frozen=True)
class OperationalCapabilities:
    current_ingestion: bool = False
    historical_ingestion: bool = False
    backfill: bool = False
    point_in_time: bool = False
    corporate_actions: bool = False
    data_quality: bool = False
    data_contracts: bool = False
    feature_reproducibility: bool = False
    backtest_reproducibility: bool = False
    transaction_costs: bool = False
    out_of_sample: bool = False
    anti_overfitting: bool = False
    risk_manager: bool = False
    portfolio_engine: bool = False
    paper_shadow: bool = False
    attribution: bool = False
    dashboard: bool = False
    automatic_jobs: bool = False
    observability: bool = False
    security: bool = False
    ci: bool = False
    deploy: bool = False
    end_to_end: bool = False


@dataclass(frozen=True)
class OperationalReadiness:
    approved: bool
    missing: tuple[str, ...]


def evaluate_operational_readiness(
    capabilities: OperationalCapabilities,
) -> OperationalReadiness:
    missing = tuple(
        field.name for field in fields(capabilities)
        if not bool(getattr(capabilities, field.name))
    )
    return OperationalReadiness(approved=not missing, missing=missing)


def assert_operational_ready(
    capabilities: OperationalCapabilities,
) -> OperationalReadiness:
    result = evaluate_operational_readiness(capabilities)
    if not result.approved:
        raise RuntimeError("operational release gate blocked: " + ", ".join(result.missing))
    return result


def capabilities_from_evidence(evidence: Mapping[str, bool]) -> OperationalCapabilities:
    names = {field.name for field in fields(OperationalCapabilities)}
    unknown = set(evidence) - names
    if unknown:
        raise ValueError("unknown operational capability: " + ", ".join(sorted(unknown)))
    return OperationalCapabilities(**{name: bool(evidence.get(name, False)) for name in names})
