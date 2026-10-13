from __future__ import annotations

from dataclasses import asdict, dataclass
from html import escape
import json
from typing import Mapping


@dataclass(frozen=True)
class OperationalDashboardSnapshot:
    data_health: Mapping[str, object]
    strategies: Mapping[str, object]
    portfolio: Mapping[str, object]
    risk: Mapping[str, object]
    paper_trading: Mapping[str, object]
    performance: Mapping[str, object]
    experiments: Mapping[str, object]
    system_health: Mapping[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def render_html(self) -> str:
        sections = []
        for title, payload in self.to_dict().items():
            body = escape(json.dumps(payload, sort_keys=True, indent=2, default=str))
            sections.append(f"<section><h2>{escape(title)}</h2><pre>{body}</pre></section>")
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Mercado Financeiro</title></head><body>"
            "<h1>Mercado Financeiro — Operational Dashboard</h1>"
            + "".join(sections)
            + "</body></html>"
        )
