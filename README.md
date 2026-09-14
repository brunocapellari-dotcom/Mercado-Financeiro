# Mercado Financeiro

Unidade quantitativa de pesquisa, validação e operação sistemática para o mercado brasileiro.

## Mandato

Construir uma mesa quantamental/sistemática auditável, com dados point-in-time, identidade histórica, validação fora da amostra e risco determinístico. O escopo inicial é B3, ações e ETFs líquidos, com horizonte de dias a semanas.

## Regra de promoção

Nenhuma estratégia recebe capital real sem, no mínimo:

- universo investível point-in-time sem survivorship bias material;
- fundamentals e market cap point-in-time;
- corporate actions e total return reconciliados;
- validação walk-forward/out-of-sample;
- custos, slippage, liquidez e capacidade;
- testes anti-overfitting e estabilidade;
- Risk Gate independente;
- shadow/paper trading aprovado.

## Arquitetura de dados inicial

Fontes prioritárias: B3 COTAHIST/BVBG, CVM DFP/ITR/FRE/FCA, Banco Central e NEFIN. Raw é imutável; snapshots recebem fingerprint; derivados carregam proveniência, `available_from`, versão de código e data de corte.

## Estado atual

Fase P0: reconstrução point-in-time 2011–2026, identidade histórica, shares outstanding, market cap, universo investível e preparação do Tournament longitudinal.

> LIVE permanece bloqueado até aprovação formal dos gates estatísticos, de dados e de risco.
