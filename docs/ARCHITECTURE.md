# Mercado Financeiro — Arquitetura Canônica

## Princípio estrutural

O sistema é dividido obrigatoriamente em seis camadas, sem atalhos entre elas:

`DADOS -> INTELIGÊNCIA -> PREVISÃO -> SINAL -> RISCO -> EXECUÇÃO`

Nenhuma IA, estratégia, modelo, operador ou serviço pode pular o Risk Engine ou enviar ordens diretamente ao broker.

## 1. DADOS

Responsável por aquisição, normalização, point-in-time, proveniência, qualidade, reconciliação e saúde de fontes.

Fontes prioritárias:

- BTG Data Services;
- B3 e vendors autorizados;
- Databento;
- broker APIs;
- CVM;
- BCB;
- ANBIMA;
- NEFIN;
- news feeds;
- fundamentals/RI e demais fontes licenciadas.

O contrato comum para dados de mercado é `MarketDataProvider`. Implementações específicas não podem vazar detalhes de vendor para as camadas superiores.

Coletores live devem manter: reconexão, sequence number quando disponível, detecção de gap, detecção de stale feed, exchange timestamp, received timestamp, source/provider, instrument, schema/version e source health.

## 2. INTELIGÊNCIA

Transforma dados aprovados em contexto explicável, sem autoridade para negociar.

Agentes/IAS oficiais:

- MARKET CHIEF AI;
- REAL-TIME MARKET AI;
- NEWS AI;
- MACRO AI;
- FUNDAMENTAL AI;
- TECHNICAL AI;
- MICROSTRUCTURE AI;
- QUANT RESEARCH AI;
- BULL AI;
- BEAR AI.

A camada deve produzir evidências, hipóteses, divergências, cenários e incerteza. Todo output deve referenciar dados e vintages usados.

## 3. PREVISÃO

A FORECAST AI e modelos estatísticos/ML transformam features point-in-time em previsões com horizonte, timestamp de geração, versão de modelo, intervalo/incerteza e validade temporal.

Previsão não é sinal. Métricas de forecast e calibração são avaliadas independentemente da estratégia.

## 4. SINAL

Converte previsões e inteligência em propostas de ação com força, horizonte, validade, universo, direção e explicação. Um sinal é somente uma intenção de pesquisa/trading e não possui permissão de execução.

A PORTFOLIO AI pode combinar sinais e propor pesos/targets, sempre antes do Risk Engine.

## 5. RISCO

O Risk Engine é determinístico e independente de LLM.

Limites mínimos:

- notional por ordem e agregado;
- posição absoluta e concentração;
- instrumento/allowlist;
- janela de horário;
- drawdown;
- perda diária;
- liquidez/participação em ADV;
- idade máxima de market data;
- kill switch independente.

A RISK AUDITOR AI pode analisar e recomendar, mas nunca alterar ou ignorar a decisão do Risk Engine em runtime.

## 6. EXECUÇÃO

O Execution Engine é determinístico, idempotente, auditável e isolado da pesquisa. Somente ele possui acesso indireto a um BrokerAdapter autorizado. Credenciais de broker ficam fora do contexto de LLM e fora do ambiente de Research.

A EXECUTION MONITOR AI observa telemetria, reconciliação e anomalias, sem possuir credenciais de trading nem autoridade para enviar ordens.

## Separação Research x Live

`Research != Live execution` é uma fronteira física/lógica obrigatória.

Research pode produzir artefatos assinados/versionados de modelo, sinal e configuração. Live pode consumir somente artefatos promovidos por pipeline aprovado. Live não importa notebooks, prompts, caches, credenciais ou estado de sessão de IA.

## Auditoria obrigatória

O catálogo de auditoria cobre no mínimo:

- market data;
- notícias;
- fundamentos;
- macro;
- B3;
- CVM;
- BCB;
- ANBIMA;
- NEFIN;
- backtests;
- vintages;
- broker;
- risk;
- execution;
- paper;
- shadow;
- live;
- logs;
- reconciliation.

Cada auditoria deve registrar status, timestamp UTC, run/commit, fonte, versão, métricas, violações e artefatos de evidência.

## Promoção operacional

A sequência mínima é:

`backtest -> walk-forward -> paper -> shadow -> reconciliation -> security test -> risk validation -> live`

Dinheiro real permanece bloqueado se qualquer gate obrigatório estiver ausente, vencido ou reprovado.

## Segurança e anti-hack

Controles obrigatórios:

- LLM sem credenciais de trading;
- credenciais do broker isoladas em secret manager/ambiente live;
- allowlist de endpoints e política default-deny para egress live;
- MFA e IP restrictions quando suportados pelo broker/vendor;
- verificação/assinatura de webhook quando possível;
- logs append-only/imutáveis para ordens, decisões de risco, fills e reconciliação;
- idempotency key por intenção de ordem;
- proteção contra replay;
- timestamps e sequence numbers validados;
- reconciliação independente com broker;
- kill switch fora do caminho de decisão de IA.

Testes de segurança mínimos antes de live:

- order duplication;
- replay;
- stale data;
- API spoofing/host substitution;
- webhook spoofing;
- credential leak;
- race condition;
- idempotency failure.

## Regra de autoridade

IA pode sugerir, explicar, pesquisar, prever e monitorar. IA não pode:

1. possuir credencial de trading;
2. mudar limites em runtime;
3. desativar kill switch;
4. ignorar stale feed;
5. pular reconciliação;
6. enviar ordem diretamente ao broker;
7. promover estratégia para live sem todos os gates aprovados.
