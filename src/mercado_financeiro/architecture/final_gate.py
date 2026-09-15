from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinalProjectCapabilities:
    """Evidence flags required before the project may be called operationally final.

    These values are not self-attested by model code. Production orchestration must
    derive them from immutable audit artifacts, CI/security results and reconciled
    external systems.
    """

    full_test_suite: bool = False
    security_suite: bool = False
    official_source_integration: bool = False
    historical_identity_2011_2026: bool = False
    security_master_2011_2026: bool = False
    shares_outstanding_pit: bool = False
    market_cap_pit: bool = False
    total_return_reconciled: bool = False
    investable_universe_pit: bool = False
    cvm_fundamentals_pit: bool = False
    bcb_macro_pit: bool = False
    anbima_data_validated: bool = False
    nefin_reconciled: bool = False
    news_pit: bool = False
    feature_mart_pit: bool = False
    transaction_cost_model_validated: bool = False
    tournament_walk_forward_oos: bool = False
    model_lineage_registry: bool = False
    portfolio_risk_validated: bool = False
    paper_validated: bool = False
    shadow_validated: bool = False
    broker_reconciliation_validated: bool = False
    security_red_team_validated: bool = False
    live_runtime_hardened: bool = False


@dataclass(frozen=True)
class FinalProjectReadiness:
    approved: bool
    missing: tuple[str, ...]


_FINAL_REQUIREMENTS: tuple[str, ...] = tuple(FinalProjectCapabilities.__dataclass_fields__)


def evaluate_final_project_readiness(
    capabilities: FinalProjectCapabilities,
) -> FinalProjectReadiness:
    missing = tuple(
        name for name in _FINAL_REQUIREMENTS if not bool(getattr(capabilities, name))
    )
    return FinalProjectReadiness(approved=not missing, missing=missing)


def assert_final_project_ready(
    capabilities: FinalProjectCapabilities,
) -> FinalProjectReadiness:
    result = evaluate_final_project_readiness(capabilities)
    if not result.approved:
        raise RuntimeError("final project gate blocked: " + ", ".join(result.missing))
    return result
