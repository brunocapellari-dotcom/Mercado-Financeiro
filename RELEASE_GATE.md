# Mercado Financeiro — Operational Release Gate

Data da auditoria: 2026-10-07  
Branch de trabalho: `architecture/segregated-market-stack`  
Regra: `DONE = código + teste executado + evidência + commit`. Código ou documentação sem execução real permanecem abaixo de DONE. Negociação com dinheiro real está fora deste gate.

## Auditoria real

| Componente | Classificação | Status release | Evidência atual / gap |
|---|---|---|---|
| Repositório/branch | FUNCIONAL | DOING | PR #20 aberto e mergeável; branch divergiu de main por um commit documental. |
| B3 COTAHIST | PARCIAL | DOING | Parser e auditoria oficial existem; rotina atual cobre 2011, não backfill 2001+ nem atualização diária persistida. |
| B3 BVBG.028 | PARCIAL | DOING | Parser/auditoria histórica existem; persistência e rotina diária ainda não comprovadas. |
| B3 BVBG.186/.086 | AUSENTE | TODO | Nenhuma implementação encontrada na branch auditada. |
| CVM DFP/ITR/FCA | PARCIAL | DOING | PIT/FCA e auditorias existem; cadeia completa DFP+ITR+FCA 2001+ não possui evidência operacional. |
| BCB SGS/Expectativas | PARCIAL | DOING | SGS e Olinda/Focus possuem coletores; jobs persistentes e histórico operacional ainda sem evidência. |
| NEFIN | PARCIAL | DOING | Coletor oficial existe como BENCHMARK_ONLY; reconciliação executada ainda precisa de evidência. |
| ANBIMA público | AUSENTE | TODO | O código existente é ANBIMA Feed e fica PÓS-RELEASE; Fase 1 exige apenas consultas/downloads públicos. |
| RAW imutável | PARCIAL | TESTING | Raw vault/PIT store e contratos de cloud existem; execução persistente no ambiente principal ainda sem evidência atual. |
| Backfill 02/01/2001+ | AUSENTE | TODO | Não existe orquestrador de backfill independente da coleta atual. |
| Point-in-Time | PARCIAL | TESTING | Store, as-of e controles de leakage existem; falta execução E2E com todas as fontes prioritárias. |
| Corporate actions | PARCIAL | TESTING | Eventos e total-return existem; cobertura integral de todos os eventos exigidos ainda não comprovada. |
| Data quality | PARCIAL | TESTING | Contratos de nulidade, duplicata, ranges, timestamps, freshness e schema drift existem; falta log operacional de incidentes/ações e cobertura total. |
| Data contracts | PARCIAL | TESTING | Contratos canônicos adicionados nesta release; aguardam gate completo executado. |
| Research/features/OOS | PARCIAL | TESTING | Experimentos, PIT features, walk-forward, PBO/DSR/Reality Check existem; falta execução real 2001+ reproduzível. |
| Backtest operacional | PARCIAL | TODO | Custos/tournament/runtime existem, mas falta sessão E2E persistente e reproduzível. |
| Risk Manager | PARCIAL | TESTING | Motor determinístico independente e veto de portfolio existem; aguarda teste integral executado. |
| Portfolio | PARCIAL | TESTING | Ledger, risk e pesos básicos existem; falta sessão de construção/rebalanceamento E2E. |
| Paper/Shadow | PARCIAL | TESTING | Broker simulado integrado ao ledger foi adicionado; falta job contínuo com dados atuais e evidência de segunda execução sem edição. |
| Attribution | PARCIAL | TESTING | Attribution reconciliável foi adicionado; falta integração ao fluxo E2E real. |
| Market regimes | PARCIAL | TESTING | Classificador simples determinístico foi adicionado; falta validação histórica. |
| Dashboard | PARCIAL | TESTING | Snapshot/renderizador com as oito seções foi adicionado; não há serviço implantado. |
| Observabilidade | PARCIAL | TODO | Agent tracing existe; falta health de fonte/job/dataset/paper/risk/system. |
| Scheduler/jobs | AUSENTE | TODO | Nenhum scheduler/job operacional encontrado. |
| CI GitHub | QUEBRADO | BLOCKED | Workflows atuais encerram sem steps; não constituem teste. |
| Cloud Build/deploy | PARCIAL | BLOCKED | Configuração existe; execução/deploy atual não foi comprovado nesta auditoria. |
| Segurança | PARCIAL | TESTING | Scans e hardening existem; não há execução atual que prove zero CRITICAL/HIGH. |
| E2E completo | AUSENTE | TODO | Ainda não executado em dados reais duas vezes sem alteração manual. |

## Blocker externo atual

**BLOCKER:** GitHub Actions não aloca executor para os workflows atuais.  
**IMPACTO:** CI, segurança, source gates e E2E não podem receber status DONE com evidência de GitHub Actions.  
**SOLUÇÃO:** executar o runner-independent gate em Cloud Build (ou restaurar runner GitHub) e persistir os artefatos de evidência.  
**AÇÃO HUMANA MÍNIMA:** nenhuma enquanto um executor GCP já autorizado puder executar; se a conta exigir nova autorização/credencial, essa é a única intervenção humana necessária.

## Regra de promoção

O gate operacional termina em PAPER/SHADOW. `LIVE` e qualquer execução com dinheiro real continuam bloqueados e exigem decisão humana explícita fora desta release.
