# Mercado Financeiro — Operational Release Gate

Data da auditoria: 2026-10-13  
Branch: `architecture/segregated-market-stack`  
Escopo: PAPER/SHADOW. LIVE com dinheiro real permanece explicitamente fora deste gate.

Regra: **DONE = código + teste executado + evidência + commit**.

## Evidência-base verde

O commit `024ded70b2d28921ba36de1feb9d4bb144edc0c2` concluiu com sucesso, no mesmo estado de código:

- full-project-gate;
- CodeQL;
- deterministic Python 3.11 e 3.12;
- B3/CVM historical identity;
- FRE share history;
- B3 company events;
- source diagnostics;
- CVM PIT;
- BVBG;
- macro/BCB.

## Matriz de release

| Componente | Estado | Evidência / bloqueio |
|---|---|---|
| Segurança estática e dependências | DONE no baseline verde | CodeQL + gate determinístico passaram no commit `024ded70`. |
| Testes Python 3.11/3.12 | DONE no baseline verde | Gate completo passou nas duas versões. |
| B3 COTAHIST / identidade histórica | DONE no gate atual | Auditoria oficial 2011–2026 verde no baseline. |
| B3 BVBG | DONE no gate atual | Integração oficial verde. |
| CVM PIT | DONE no gate atual | Gate oficial verde. |
| FRE / shares | DONE no gate atual | Vintages inconsistentes são excluídos por filing, fail-closed e contabilizados. |
| BCB / macro | DONE no gate atual | SGS/Olinda/Focus auditados pelo gate. |
| Eventos corporativos B3 | DONE no gate atual | Integração oficial verde. |
| Point-in-Time / anti-lookahead | DONE no core | Contratos, as-of e invariantes cobertos por testes. |
| Risk Manager determinístico | DONE no core | Veto pré-trade, limites e kill-switch boundaries testados. |
| Broker simulado / ledger | DONE no core | PAPER/BACKTEST usam o mesmo caminho determinístico sem broker real. |
| Runtime PAPER/SHADOW | READY / TESTING | Operational cycle e imagem non-root adicionados após baseline verde; novo CI não conseguiu iniciar runners. |
| Runtime LIVE | BLOCKED BY DESIGN | Sem deploy, identidade ou segredo de broker nesta release. |
| Cloud data layers | READY / TESTING | `raw -> normalized -> canonical -> derived -> analytics`; research isolado. |
| Evidência operacional | READY / TESTING | Upload append-only para o bucket RAW versionado; aguarda execução cloud. |
| Terraform | READY / TESTING | GCP compartilhado `ai-holding-prod-bc`; validação entrou no gate, mas runner não iniciou. |
| Container | READY / TESTING | Base por digest, usuário non-root; build entrou no gate, mas runner não iniciou. |
| WIF deploy | HUMAN BLOCKER | Holding PR #67 cria provider dedicado `mf-deploy-main`; não aplicar sem aprovação humana. |
| Market data atual autorizado | HUMAN BLOCKER | Necessário acesso/licença/distribuidor autorizado; scraping B3 não é aceito. |
| E2E cloud #1 e #2 | BLOCKED | Depende de WIF aprovado + segredo market data + CI executável. |
| Scheduler recorrente | PÓS-DEPLOY IMEDIATO | Deve reutilizar a identidade bounded da Holding; não criar segundo orquestrador. |
| GO-LIVE PAPER/SHADOW | NOT YET | Exige dois E2E consecutivos e evidência persistida. |

## Outage do executor

Após o baseline verde, novos workflows de Mercado Financeiro e AI-Holding passaram a concluir com falha sem executar qualquer step, inclusive CodeQL. Essa condição não pode ser usada como evidência de aprovação nem como evidência de regressão. O gate permanece fail-closed até o runner executar novamente.

## Dependências humanas

1. Revisar e aprovar a mudança de trust boundary na AI-Holding PR #67 quando o CI voltar a funcionar.
2. Disponibilizar acesso autorizado de market data atual e criar a versão do segredo `mf-authorized-price-report-url` sem expor o valor em Git/chat/log.

Detalhamento e sequência operacional: `GO_LIVE_STATUS.md`.
