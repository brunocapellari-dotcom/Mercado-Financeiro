from __future__ import annotations

from html import escape
import json
from decimal import Decimal

from .session import PaperShadowSnapshot


def snapshot_payload(snapshot: PaperShadowSnapshot) -> dict[str, object]:
    def dec(value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")

    return {
        "mode": snapshot.mode.value,
        "orders": snapshot.orders,
        "fills": snapshot.fills,
        "rejected": snapshot.rejected,
        "duplicates": snapshot.duplicates,
        "turnover": dec(snapshot.turnover),
        "fees": dec(snapshot.fees),
        "realized_pnl": dec(snapshot.realized_pnl),
        "unrealized_pnl": dec(snapshot.unrealized_pnl),
        "equity": dec(snapshot.equity),
        "gross_exposure": dec(snapshot.gross_exposure),
        "positions": {key: dec(value) for key, value in snapshot.positions.items()},
        "records": [
            {
                "order_id": row.order_id,
                "signal_id": row.signal_id,
                "instrument": row.instrument,
                "side": row.side,
                "quantity": dec(row.quantity),
                "requested_price": dec(row.requested_price),
                "status": row.status,
                "risk_reasons": list(row.risk_reasons),
                "fill_price": dec(row.fill_price),
                "fee": dec(row.fee),
                "slippage_bps": dec(row.slippage_bps),
                "realized_pnl_delta": dec(row.realized_pnl_delta),
                "duplicate": row.duplicate,
                "created_at": row.created_at.isoformat(),
            }
            for row in snapshot.records
        ],
    }


def snapshot_json(snapshot: PaperShadowSnapshot) -> str:
    return json.dumps(snapshot_payload(snapshot), ensure_ascii=False, sort_keys=True)


def render_dashboard_html(snapshot: PaperShadowSnapshot) -> str:
    payload = snapshot_payload(snapshot)
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(row['instrument']))}</td>"
        f"<td>{escape(str(row['side']))}</td>"
        f"<td>{escape(str(row['quantity']))}</td>"
        f"<td>{escape(str(row['status']))}</td>"
        f"<td>{escape(str(row['fill_price']))}</td>"
        f"<td>{escape(str(row['fee']))}</td>"
        f"<td>{escape(str(row['signal_id']))}</td>"
        "</tr>"
        for row in payload["records"]
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Mercado Financeiro — Paper/Shadow</title>"
        "<style>body{font-family:system-ui;margin:24px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ddd;padding:6px;text-align:left}.kpi{display:inline-block;margin:0 18px 18px 0}"
        "</style></head><body>"
        "<h1>Mercado Financeiro — Paper/Shadow</h1>"
        f"<div class='kpi'><b>Modo</b><br>{escape(str(payload['mode']))}</div>"
        f"<div class='kpi'><b>Ordens</b><br>{payload['orders']}</div>"
        f"<div class='kpi'><b>Fills</b><br>{payload['fills']}</div>"
        f"<div class='kpi'><b>Rejeitadas</b><br>{payload['rejected']}</div>"
        f"<div class='kpi'><b>Equity</b><br>{escape(str(payload['equity']))}</div>"
        f"<div class='kpi'><b>P&L realizado</b><br>{escape(str(payload['realized_pnl']))}</div>"
        f"<div class='kpi'><b>P&L não realizado</b><br>{escape(str(payload['unrealized_pnl']))}</div>"
        f"<div class='kpi'><b>Custos</b><br>{escape(str(payload['fees']))}</div>"
        "<h2>Ordens simuladas</h2><table><thead><tr><th>Ativo</th><th>Lado</th><th>Qtd.</th>"
        "<th>Status</th><th>Fill</th><th>Taxa</th><th>Sinal</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>"
    )
