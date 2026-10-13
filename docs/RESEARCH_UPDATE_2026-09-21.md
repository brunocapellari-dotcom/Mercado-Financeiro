# Atualização de pesquisa e arquitetura — 2026-09-21

## Objetivo

Revisar NautilusTrader, Pydantic AI Harness, Phoenix, Promptfoo e Soda Core
contra o estado real do Mercado Financeiro, fazer uma segunda rodada de
alternativas e incorporar somente capacidades que aumentem correção,
auditabilidade ou segurança sem criar verdades paralelas.

## Resultado executivo

A decisão desta rodada é **composição seletiva**, não substituição em bloco.

- NautilusTrader: benchmark/runtime candidato isolado; não vira autoridade de
  risco nem fonte PIT.
- Pydantic AI Harness: adotado somente na camada opcional de agentes, atrás de
  adapter próprio e pin de minor.
- Phoenix: backend opcional; o contrato canônico de tracing é OpenTelemetry com
  atributos próprios do Mercado Financeiro.
- Promptfoo: adotado como ferramenta externa de regression/red-team.
- Soda Core v4: rejeitado como dependência; seus conceitos de data contracts são
  implementados no core.
- Pydantic Evals: adotado como extra opcional para regressão Python e consome o
  mesmo corpus de casos do Promptfoo.
- OpenInference: referência de semântica LLM/tool sobre OpenTelemetry; não é
  necessário tornar Phoenix obrigatório.
- Opik, Langfuse e DeepEval: não adicionados por sobreposição.
- Zipline Reloaded e demais backtest engines genéricos: não adicionados; LEAN já
  cumpre o papel de segunda implementação independente e Nautilus cobre o
  benchmark event-driven.
- Pandera/GX: não adicionados enquanto os contratos internos permanecerem menores
  e mais específicos ao domínio financeiro brasileiro.

## 1. NautilusTrader — benchmark aprofundado

### Estado upstream observado

Em 2026-09-21, o release v2 mais recente publicado é **2.0.0rc5**, lançado em
2026-09-15. A linha v2 está em release candidate, requer Python 3.12–3.14 e o
próprio upstream não recomenda RC/development wheels para live trading com
capital real.

Consequência: **Nautilus v2 RC é proibido para dinheiro real no Mercado
Financeiro**. Esta regra permanece mesmo que testes locais passem.

### Comparação por capacidade

| Capacidade | Mercado Financeiro atual | Nautilus v2 RC | Decisão |
| --- | --- | --- | --- |
| Event-driven engine | kernel tipado e simples, mesmo caminho de execução por modo | runtime Rust maduro, message bus e engines especializados | manter kernel; absorver invariantes e benchmark |
| Replay determinístico | novo replay canônico com ordenação total e hash do stream | replay/backtest nativo e muito mais profundo | comparar por snapshot normalizado |
| Research/backtest/live parity | BACKTEST/PAPER/SHADOW/LIVE compartilham Risk/Execution, mas simulação ainda é menor | mesma arquitetura event-driven do backtest ao live | Nautilus é referência; não importar sua autoridade |
| Portfolio/accounting | antes havia risk snapshot e reconciliação, sem ledger completo | portfolio/accounting maduros | criado ledger próprio determinístico com Decimal |
| Risk engine | fail-closed, B3-aware, allowlist, drawdown, loss, ADV, stale data, kill switch | motor amplo e integrado ao runtime | Risk Manager interno continua autoridade |
| Execution engine | idempotência, ambiguous outcome, reconciliação e broker boundary explícitos | lifecycle/order types/adapters muito mais amplos | benchmark e possível runtime isolado no futuro |
| Data catalog | DuckDB PIT + raw evidence + provenance + future BigQuery | catálogo de dados/replay orientado ao motor | complementares; PIT brasileiro não é substituído |
| Multi-asset | escopo inicial B3 ações/ETFs | multi-asset/multi-venue | expansão futura por adapters, não por migração cega |

### Contrato de benchmark criado

`EngineParitySnapshot` normaliza:

- hash do stream de eventos;
- posições;
- caixa;
- P&L realizado;
- taxas;
- número de execuções;
- rejeições de risco.

`compare_engine_snapshots` aplica tolerâncias explícitas. Um futuro adapter
Nautilus só poderá ser promovido se reproduzir cenários canônicos do Mercado
Financeiro sem alterar a decisão do Risk Manager.

### Gates antes de considerar Nautilus para runtime live

1. release v2 final estável, não RC;
2. compatibilidade aprovada em ambiente Python 3.12+ isolado;
3. replay determinístico reproduzível;
4. posições, caixa, P&L e taxas reconciliados;
5. paridade de decisões de risco onde aplicável;
6. idempotência e ambiguous-submit semantics preservados;
7. reconciliação com broker permanece independente;
8. nenhum acesso de LLM a credenciais/live;
9. security/red-team e recovery tests;
10. shadow trading aprovado.

## 2. Portfolio/accounting próprio

A maior lacuna prática identificada no benchmark foi accounting. Em vez de
importar todo o Nautilus, foi criado um ledger próprio:

- Decimal em toda a fronteira contábil;
- posição assinada;
- custo médio;
- P&L realizado em redução/zeragem/cross-through;
- caixa;
- taxas cumulativas;
- fill_id exactly-once;
- mark-to-market, equity, exposição bruta e P&L não realizado.

O ledger é inicialmente single-currency/BRL, coerente com o primeiro escopo B3.
Multi-currency só entra quando houver caso real e contrato cambial explícito.

## 3. Pydantic AI Harness

### Decisão

Adotado apenas na camada Research/Intelligence. A extra `agents` fixa
`pydantic-ai-harness>=0.32,<0.33` porque o upstream usa versionamento 0.x e
admite mudanças de API entre minor releases.

O adapter do projeto valida a presença de:

- Planning;
- SubAgents;
- Memory;
- SpendLimits;
- TrajectoryJudge;
- DynamicWorkflow.

Tool approval permanece subordinado à política própria do Mercado Financeiro.

### Autoridade

O agente pode pesquisar, planejar, delegar, memorizar, usar ferramentas
permitidas, controlar orçamento e revisar trajetória. Ele não pode:

- enviar ordem;
- acessar credencial de broker;
- alterar limite de risco;
- desligar kill switch;
- modificar estado live;
- promover estratégia.

`ResearchToolPolicy` é fail-closed: ferramentas desconhecidas são negadas.

## 4. Observabilidade: OpenTelemetry primeiro, Phoenix opcional

Phoenix é funcionalmente forte e permanece candidato de UI/backend
self-hosted, mas está sob Elastic License 2.0. Não será dependência estrutural.

Foi criado schema estável do projeto para traces:

- modelo;
- ferramenta;
- custo;
- latência;
- erro;
- hash do resultado;
- dataset de regressão;
- operação.

Resultados/payloads brutos não entram automaticamente na telemetria. Um
`OpenTelemetryAgentTraceSink` aceita qualquer tracer OTel configurado. Phoenix,
Opik, Langfuse ou outro collector compatível podem ser trocados sem mudar a
lógica financeira.

## 5. Promptfoo + Pydantic Evals

Promptfoo é MIT e entra como ferramenta de desenvolvimento, não de runtime.

Foi criado:

- provider Python para endpoint de avaliação;
- assertions de artefato hypothesis-only;
- regression suite;
- intents específicos de mercado financeiro;
- red-team para excessive agency, hijacking, overreliance e PII;
- OWASP LLM/Agentic + NIST AI Measure;
- corpus canônico compartilhado.

Pydantic Evals usa o mesmo `evals/research_cases.json`; não existe segundo
dataset duplicado.

O red-team deve operar sem credenciais de broker/live. Para pesquisa privada,
remote red-team generation deve permanecer desabilitada salvo aprovação
explícita de dados e provedor.

## 6. Soda Core e contratos de dados

Soda Core v4 não é adotado. O workspace atual declara licença proprietária e,
mais importante, duplicaria uma camada que o projeto já possui.

Foram criados contratos próprios para:

- COTAHIST;
- BVBG.028;
- CVM fundamentals;
- BCB;
- NEFIN;
- dados corporativos;
- séries de mercado.

Os contratos reaproveitam `DataQualityContract` existente e acrescentam:

- campos obrigatórios;
- not-null;
- chaves únicas;
- faixas numéricas;
- relação `available_from >= reference_date`;
- bloqueio de informação futura em um `as_of`.

## 7. Segunda rodada — redundâncias removidas

### Observabilidade

- Phoenix: backend opcional.
- Opik: não adicionado; duplicaria tracing/evals.
- Langfuse: não adicionado; duplicaria tracing/evals.
- padrão canônico: OpenTelemetry + schema próprio; OpenInference é referência
  semântica para LLM/tool spans.

### LLM evaluation

- Pydantic Evals: Python/trajectory/regression.
- Promptfoo: red-team/declarative/security.
- DeepEval: não adicionado porque cobre grande parte das mesmas funções.

### Data quality

- contratos internos: autoridade.
- Soda v4: rejeitado.
- Pandera: benchmark apenas.
- Great Expectations: não adicionado por peso/duplicação.

### Backtest/runtime

- motor interno: autoridade determinística.
- Nautilus: benchmark/runtime candidato isolado.
- LEAN: paridade externa independente para estratégias simples.
- Zipline/Backtrader/QSTrader/vectorbt como motor canônico: rejeitados para não
  criar terceira/quarta verdade.

### B3/CVM

Projetos como `filings-b3`/`filings-cvm` permanecem referências de
implementação para tipagem explícita, Decimal, provenance e schema drift. O
projeto não depende deles e B3/CVM oficiais continuam fontes canônicas.

## 8. Firewall de decisão

A cadeia final é:

`LLM/Research -> hipótese -> validação quantitativa -> sinal candidato -> Risk Manager -> motor determinístico`

Nunca:

`LLM -> ordem`

O Quant Research/Forecast pode rejeitar a hipótese. O Risk Manager pode vetar um
sinal quantitativamente válido. O motor executa somente uma intenção que tenha
passado por todos os contratos anteriores.

## 9. Estado de validação desta mudança

Código, testes e artefatos foram adicionados à branch da PR #20. Como o
repositório continua privado e não há runners disponíveis, **não há evidência de
execução do whole-project gate para estes novos commits**. Portanto:

- não marcar como green;
- não fazer merge;
- não promover live;
- não tratar o benchmark Nautilus como runtime benchmark concluído.

O benchmark arquitetural/comparativo foi concluído; o benchmark runtime fica
objetivamente definido pelo novo parity contract e deve ser executado quando
houver um executor disponível.
