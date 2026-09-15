# Mercado Financeiro

Unidade quantitativa de pesquisa, validação e operação sistemática para o mercado brasileiro.

## Mandato

Construir uma mesa quantamental/sistemática auditável, com dados point-in-time, identidade histórica, validação fora da amostra, risco determinístico e execução segregada. O escopo inicial é B3, ações e ETFs líquidos, com horizonte de dias a semanas.

## Arquitetura obrigatória

`DADOS -> INTELIGÊNCIA -> PREVISÃO -> SINAL -> RISCO -> EXECUÇÃO`

Não existem atalhos entre camadas. IA/modelo pode produzir inteligência, forecast, sinal e recomendação de portfólio; não possui credenciais de trading, não altera limites em runtime e nunca bypassa Risk Engine ou Execution Engine.

A especificação canônica está em `docs/ARCHITECTURE.md` e os controles em `docs/SECURITY_ARCHITECTURE.md`.

## Dados

Fontes prioritárias: BTG Data Services, B3/vendor, Databento, broker APIs, CVM, BCB, ANBIMA, NEFIN, news feeds e fundamentals/RI conforme licença e disponibilidade.

`MarketDataProvider` é a abstração vendor-neutral. Coletores live devem registrar exchange timestamp, received timestamp e sequence quando disponível, detectar gaps/stale feed e reconectar de forma observável.

Raw é imutável; snapshots recebem fingerprint; derivados carregam proveniência, `available_from`, versão de código e data de corte.

## Pesquisa e validação

Nenhuma estratégia recebe capital real sem, no mínimo:

- universo investível point-in-time sem survivorship bias material;
- fundamentals e market cap point-in-time;
- corporate actions e total return reconciliados;
- backtest e walk-forward/out-of-sample;
- custos, slippage, liquidez e capacidade;
- testes anti-overfitting e estabilidade;
- paper;
- shadow;
- reconciliation;
- security test;
- risk validation.

## Segurança operacional

`Research != Live execution` é uma fronteira física/lógica. Broker credentials permanecem isoladas do Research e de LLMs. O Risk Engine e o Execution Engine são determinísticos. Kill switch é independente.

Limites mínimos incluem notional, posição, instrumento, horário, drawdown, daily loss, liquidez e freshness de dados. Order duplication, replay, stale feed, API/webhook spoofing, credential leak, race condition e idempotency failure fazem parte da matriz obrigatória de segurança.

## Auditoria

São domínios obrigatórios: market data, notícias, fundamentos, macro, B3, CVM, BCB, ANBIMA, NEFIN, backtests, vintages, broker, risk, execution, paper, shadow, live, logs e reconciliation.

## Estado atual

Fase P0: reconstrução point-in-time 2011–2026, identidade histórica, shares outstanding, market cap, universo investível e preparação do Tournament longitudinal.

> LIVE permanece bloqueado até aprovação formal de todos os gates estatísticos, de dados, reconciliação, segurança e risco.
