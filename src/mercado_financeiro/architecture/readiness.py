from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveCapabilities:
    """Deterministic infrastructure capabilities required before live startup."""

    durable_idempotency: bool = False
    durable_webhook_replay_protection: bool = False
    external_immutable_audit_log: bool = False
    secret_manager: bool = False
    restricted_egress: bool = False
    independent_reconciliation: bool = False
    independent_kill_switch: bool = False
    separate_live_identity: bool = False
    broker_mfa: bool = False
    ip_restriction_enforced_or_unsupported: bool = False


@dataclass(frozen=True)
class RuntimeReadiness:
    approved: bool
    missing: tuple[str, ...]


_REQUIRED_CAPABILITIES: tuple[str, ...] = (
    "durable_idempotency",
    "durable_webhook_replay_protection",
    "external_immutable_audit_log",
    "secret_manager",
    "restricted_egress",
    "independent_reconciliation",
    "independent_kill_switch",
    "separate_live_identity",
    "broker_mfa",
    "ip_restriction_enforced_or_unsupported",
)


def evaluate_live_runtime(capabilities: LiveCapabilities) -> RuntimeReadiness:
    """Fail closed when the live environment still relies on research/test controls."""

    missing = tuple(
        name for name in _REQUIRED_CAPABILITIES if not bool(getattr(capabilities, name))
    )
    return RuntimeReadiness(approved=not missing, missing=missing)


def assert_live_runtime(capabilities: LiveCapabilities) -> RuntimeReadiness:
    result = evaluate_live_runtime(capabilities)
    if not result.approved:
        raise RuntimeError("live runtime is not hardened: " + ", ".join(result.missing))
    return result
