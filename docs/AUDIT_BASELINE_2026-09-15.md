# Auditoria Baseline — 2026-09-15

Escopo: estado técnico do repositório Mercado-Financeiro após a atualização arquitetural. Status não significa aprovação para live.

| Domínio | Status | Evidência / Lacuna principal |
|---|---|---|
| Market data | PARCIAL | COTAHIST/BVBG e auditorias B3 existem; `MarketDataProvider` e `LiveFeedMonitor` foram definidos. Faltam adapters reais BTG/Databento/broker/vendor e observabilidade persistida de feed. |
| Notícias | GAP | Não há pipeline de news feed operacional no repositório. |
| Fundamentos | PARCIAL | CVM/FCA/DFP/FRE e regras PIT existem em parte. Ainda faltam fechamento histórico completo, normalização final e ligação integral ao Feature Mart. |
| Macro | GAP | Não há adapter BCB/curvas/macro operacional no código atual. |
| B3 | PARCIAL FORTE | COTAHIST, instrumentos, auditorias de BVBG e identidade histórica existem. Backfill/identidade 2011+ ainda não está fechado no gate final. |
| CVM | PARCIAL | FCA e snapshots fundamentais existem; vintages e disponibilidade PIT continuam em fechamento. |
| BCB | GAP | Fonte prevista, mas adapter/ingestão não está implementado no repositório atual. |
| ANBIMA | GAP | Fonte prevista; sem implementação operacional atual. |
| NEFIN | GAP | Ainda sem ingestão/reconciliação de fatores/benchmarks no repositório atual. |
| Backtests | GAP CRÍTICO | Tournament longitudinal e framework walk-forward ainda não estão materializados no repositório atual. |
| Vintages | PARCIAL | Política PIT, `available_from`, provenance/hash e identidade histórica estão em evolução. |
| Broker | CONTRATO | `BrokerAdapter` existe como fronteira; nenhuma credencial ou integração real foi adicionada. |
| Risk | CORE IMPLEMENTADO | `DeterministicRiskEngine` cobre notional, posição, instrumento, horário, drawdown, daily loss, liquidez, stale data e kill switch. Precisa integração e testes com ambiente paper/broker. |
| Execution | CORE IMPLEMENTADO | Engine determinístico, client order ID e idempotência local/race protection implementados. Live exige store atômico durável e deduplicação broker-side. |
| Paper | BLOQUEADO | Só deve iniciar depois dos gates históricos/backtest mínimos e integração simulada. |
| Shadow | BLOQUEADO | Depende de paper, reconciliação e feeds reais. |
| Live | BLOQUEADO | Sem autorização até todos os gates obrigatórios aprovados. |
| Logs | PARCIAL | Ledger hash-chained de referência implementado; falta sink durável append-only/tamper-evident. |
| Reconciliation | CORE IMPLEMENTADO | Reconciler determinístico de posição/caixa implementado; falta integração com snapshots reais do broker. |

## Gaps P0

1. Fechar identidade/survivorship e universo PIT 2011–2026.
2. Fechar market cap PIT e corporate actions/Total Return.
3. Implementar adapters reais de BCB, NEFIN e fontes necessárias ao Tournament.
4. Materializar Feature Mart point-in-time.
5. Executar Tournament walk-forward ~15 anos com custos/slippage/liquidez/capacidade.
6. Implementar provider real de market data/broker somente após a camada de pesquisa estar validada.
7. Persistir audit ledger e reconciliation em storage durável/imutável.
8. Separar fisicamente Research e Live em identidades, rede e Secret Manager antes de qualquer credencial de trading.

## Gates de live

Todos devem estar explicitamente `PASS` e com evidência válida:

- backtest;
- walk-forward;
- paper;
- shadow;
- reconciliation;
- security test;
- risk validation.

Qualquer gate ausente, vencido ou `FAIL` mantém Live bloqueado.
