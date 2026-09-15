from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class ReconciliationMismatch:
    key: str
    internal_value: Decimal
    broker_value: Decimal
    difference: Decimal


@dataclass(frozen=True)
class ReconciliationResult:
    approved: bool
    position_mismatches: tuple[ReconciliationMismatch, ...]
    cash_mismatch: ReconciliationMismatch | None


class DeterministicReconciler:
    """Fail-closed reconciliation between the internal ledger and broker state."""

    def __init__(self, *, position_tolerance: Decimal = Decimal("0"), cash_tolerance: Decimal = Decimal("0.01")) -> None:
        if position_tolerance < 0 or cash_tolerance < 0:
            raise ValueError("reconciliation tolerances cannot be negative")
        self._position_tolerance = position_tolerance
        self._cash_tolerance = cash_tolerance

    def reconcile(
        self,
        *,
        internal_positions: Mapping[str, Decimal],
        broker_positions: Mapping[str, Decimal],
        internal_cash: Decimal,
        broker_cash: Decimal,
    ) -> ReconciliationResult:
        mismatches: list[ReconciliationMismatch] = []
        for key in sorted(set(internal_positions) | set(broker_positions)):
            internal = internal_positions.get(key, Decimal("0"))
            broker = broker_positions.get(key, Decimal("0"))
            diff = broker - internal
            if abs(diff) > self._position_tolerance:
                mismatches.append(
                    ReconciliationMismatch(
                        key=key,
                        internal_value=internal,
                        broker_value=broker,
                        difference=diff,
                    )
                )

        cash_diff = broker_cash - internal_cash
        cash_mismatch = None
        if abs(cash_diff) > self._cash_tolerance:
            cash_mismatch = ReconciliationMismatch(
                key="cash",
                internal_value=internal_cash,
                broker_value=broker_cash,
                difference=cash_diff,
            )

        return ReconciliationResult(
            approved=not mismatches and cash_mismatch is None,
            position_mismatches=tuple(mismatches),
            cash_mismatch=cash_mismatch,
        )
