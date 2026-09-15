# Revisão arquitetural final — Mercado Financeiro

## Regra de desenvolvimento

Este projeto não promove componentes isoladamente. Toda alteração relevante deve terminar no `full-project-gate`, que executa a suíte completa, segurança estática/dependências e integrações oficiais sem secrets. Uma alteração localmente correta não é considerada versão aprovada se o projeto completo não estiver verde.

## Padrões externos revisados e decisão de uso

### NautilusTrader

Padrões adotados conceitualmente: common trading kernel, event-driven boundaries, ports/adapters, um mesmo caminho Risk -> Execution entre backtest/paper/shadow/live, reconciliação de startup e tratamento explícito de outcomes ambíguos de transporte. O projeto não depende de NautilusTrader; os contratos locais preservam o domínio B3/PIT existente.

### QuantConnect LEAN

Padrões adotados conceitualmente: separar fill, fees, slippage, buying power e settlement da lógica da estratégia. O `DeterministicBrokerageModel` usa parâmetros explícitos e falha fechado quando o calendário de settlement não foi validado. Não são embutidas taxas atuais de broker/B3 sem fonte e vigência auditadas.

### Feast

Padrões adotados conceitualmente: point-in-time historical joins e paridade entre features de treinamento e serving. O projeto mantém feature schema versionado, hash do schema, hash do snapshot, parent hashes e cutoff temporal. Não se adiciona Feast como dependência enquanto a infraestrutura local cumprir o contrato necessário.

### MLflow / Qlib

Padrões adotados conceitualmente: experiment/model lineage, artefatos imutáveis, métricas vinculadas à versão e promoção explícita. `ModelManifest` liga modelo a commit, dataset manifest, feature schema, janela de treinamento e cutoff. Aliases apontam para versões imutáveis. Promoção não pode pular stages/gates.

### OpenBB

A arquitetura de providers é útil como referência, porém o projeto já possui `MarketDataProvider`, `HistoricalDataSource` e registro de fontes. Não se adiciona OpenBB apenas para duplicar essa abstração. Um adapter pode ser criado futuramente se uma fonte suportada por OpenBB reduzir manutenção de forma material.

## Melhorias incorporadas nesta revisão

1. Um workflow único `full-project-gate` sem path filters para testar o projeto inteiro.
2. Matrix Python 3.11/3.12, compile-all, secret/data scan, pytest integral, Bandit e pip-audit.
3. Integração oficial obrigatória no gate: identidade B3/CVM, BVBG.028 e macro oficial.
4. Runtime comum event-driven para backtest, paper, shadow e live.
5. Event bus em memória explicitamente `live_safe=False`.
6. Brokerage simulation determinística com bid/ask, liquidez, ADV, slippage, impact, fee e buying power.
7. Settlement fail-closed quando não existe calendário verificado.
8. Model Registry imutável com lineage completo e promoção fail-closed.
9. Feature schema/lineage versionados e training-serving parity.
10. Kill switch lido dentro do Execution Engine, fora da autoridade da estratégia/modelo.
11. Submission outcome ambíguo não é automaticamente reenviado; exige reconciliation.
12. Live readiness exige idempotência durável, broker-side client-order dedup, event bus durável, model registry durável, log imutável, startup reconciliation e settlement calendar verificado.
13. Exact B3 ISIN identity e Historical Identity Gate foram incorporados à mesma linha arquitetural para eliminar branches funcionais divergentes.

## O que deliberadamente não foi adotado

- Tool-sprawl: não adicionar Feast, MLflow, Qlib, OpenBB, NautilusTrader e LEAN simultaneamente.
- Framework de terceiros como fonte canônica de dados: B3/CVM/BCB/ANBIMA e demais fontes oficiais continuam canônicas.
- Fill/fee/slippage com números presumidos: parâmetros precisam de evidência de vigência.
- Retry cego de ordem após timeout/erro de transporte.
- Modelo/LLM com acesso a broker credentials.
- Mudança de universo histórico, fundamentos, market cap ou vintages sem point-in-time.

## Condição para `main`

O branch final só deve ser promovido quando:

- o runner do GitHub Actions realmente executar os steps;
- `full-project-gate` estiver verde;
- as integrações oficiais necessárias estiverem verdes;
- nenhum bypass Research -> Broker existir;
- nenhum gate de PIT/security/risk tiver sido neutralizado para obter aprovação.

LIVE continua sendo uma capacidade separada. Código pronto não equivale a autorização para dinheiro real.
