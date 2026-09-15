from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Callable, Protocol

from mercado_financeiro.execution import DeterministicExecutionEngine, ExecutionResult
from mercado_financeiro.risk import OrderIntent, RiskContext


class RuntimeMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    topic: str
    source: str
    occurred_at: datetime
    received_at: datetime
    payload: object
    sequence: int | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if not self.topic.strip():
            raise ValueError("topic is required")
        if not self.source.strip():
            raise ValueError("source is required")
        for name, value in (("occurred_at", self.occurred_at), ("received_at", self.received_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at cannot precede occurred_at")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence cannot be negative")


EventHandler = Callable[[EventEnvelope], None]


class EventBus(Protocol):
    """Typed event boundary shared by backtest, paper, shadow and live runtimes."""

    live_safe: bool

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        ...

    def publish(self, event: EventEnvelope) -> None:
        ...


class InMemoryEventBus:
    """Deterministic synchronous bus for research/backtest/paper tests only."""

    live_safe = False

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._lock = RLock()

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        if not topic.strip():
            raise ValueError("topic is required")
        with self._lock:
            self._handlers.setdefault(topic, []).append(handler)

    def publish(self, event: EventEnvelope) -> None:
        with self._lock:
            handlers = tuple(self._handlers.get(event.topic, ()))
        for handler in handlers:
            handler(event)


@dataclass(frozen=True)
class KernelExecution:
    mode: RuntimeMode
    order: OrderIntent
    result: ExecutionResult


class TradingKernel:
    """One execution lifecycle for all environments.

    Strategy/model code may create an ``OrderIntent`` but it cannot route around
    ``DeterministicExecutionEngine``. Backtest, paper, shadow and live therefore
    share the same risk/execution boundary; only adapters and durable backings vary.
    """

    def __init__(
        self,
        *,
        mode: RuntimeMode,
        event_bus: EventBus,
        execution_engine: DeterministicExecutionEngine,
    ) -> None:
        if mode is RuntimeMode.LIVE and not bool(getattr(event_bus, "live_safe", False)):
            raise RuntimeError("live runtime requires a durable/live-safe event bus")
        self._mode = mode
        self._event_bus = event_bus
        self._execution_engine = execution_engine

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def submit_order(self, order: OrderIntent, context: RiskContext) -> KernelExecution:
        now = datetime.now(timezone.utc)
        self._event_bus.publish(
            EventEnvelope(
                event_id=f"intent:{order.idempotency_key}",
                topic="orders.intent",
                source="trading_kernel",
                occurred_at=order.created_at.astimezone(timezone.utc),
                received_at=max(now, order.created_at.astimezone(timezone.utc)),
                payload=order,
                correlation_id=order.signal_id,
            )
        )
        result = self._execution_engine.execute(order, context)
        completed = datetime.now(timezone.utc)
        self._event_bus.publish(
            EventEnvelope(
                event_id=f"result:{order.idempotency_key}:{result.status}",
                topic="orders.result",
                source="trading_kernel",
                occurred_at=completed,
                received_at=completed,
                payload=result,
                correlation_id=order.signal_id,
            )
        )
        return KernelExecution(mode=self._mode, order=order, result=result)
