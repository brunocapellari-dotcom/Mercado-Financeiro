from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from mercado_financeiro.accounting import PortfolioAccountingLedger
from mercado_financeiro.execution import (
    BrokerOrderAck,
    DeterministicBrokerageModel,
    MarketExecutionState,
)
from mercado_financeiro.risk import OrderIntent


@dataclass(frozen=True)
class PaperFillRecord:
    fill_id: str
    client_order_id: str
    instrument: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    partial: bool


class SimulatedBrokerAdapter:
    """BrokerAdapter for backtest/paper/shadow with real accounting effects.

    It has no network/broker credential path. Market state must be supplied by the
    caller and every simulated fill is applied exactly once to the accounting ledger.
    """

    def __init__(
        self,
        *,
        brokerage_model: DeterministicBrokerageModel,
        ledger: PortfolioAccountingLedger,
    ) -> None:
        self._model = brokerage_model
        self._ledger = ledger
        self._market: dict[str, MarketExecutionState] = {}
        self._fills: list[PaperFillRecord] = []

    @property
    def ledger(self) -> PortfolioAccountingLedger:
        return self._ledger

    @property
    def fills(self) -> tuple[PaperFillRecord, ...]:
        return tuple(self._fills)

    def set_market(self, instrument: str, state: MarketExecutionState) -> None:
        key = str(instrument).strip().upper()
        if not key:
            raise ValueError("instrument is required")
        self._market[key] = state

    def submit_order(self, order: OrderIntent, *, client_order_id: str) -> BrokerOrderAck:
        market = self._market.get(order.instrument.strip().upper())
        if market is None:
            return BrokerOrderAck(accepted=False, status="market_state_unavailable")

        snapshot = self._ledger.snapshot()
        fill = self._model.simulate_market_order(
            order,
            market,
            cash_available=snapshot.cash,
        )
        if not fill.filled or fill.fill_price is None:
            return BrokerOrderAck(accepted=False, status=fill.reason)

        fill_id = f"{client_order_id}:fill:1"
        signed_quantity = fill.quantity if order.side == "buy" else -fill.quantity
        self._ledger.apply_fill(
            fill_id=fill_id,
            instrument=order.instrument,
            signed_quantity=signed_quantity,
            price=fill.fill_price,
            fee=fill.fee,
        )
        partial = fill.quantity != order.quantity
        self._fills.append(
            PaperFillRecord(
                fill_id=fill_id,
                client_order_id=client_order_id,
                instrument=order.instrument,
                side=order.side,
                quantity=fill.quantity,
                price=fill.fill_price,
                fee=fill.fee,
                partial=partial,
            )
        )
        return BrokerOrderAck(
            accepted=True,
            status="partially_filled" if partial else "filled",
            broker_order_id=fill_id,
        )
