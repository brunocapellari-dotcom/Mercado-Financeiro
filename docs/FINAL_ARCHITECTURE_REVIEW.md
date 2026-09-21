# Revisão arquitetural final — Mercado Financeiro

## Regra de desenvolvimento

O projeto é validado como um sistema único. Alterações relevantes não são promovidas
por módulo: devem terminar no gate canônico
`python scripts/run_full_project_gate.py --mode full`.

GitHub Actions, máquina local, self-hosted runner, Cloud Build ou outro executor
autorizado podem executar o mesmo contrato. O executor não define correção; o
repositório define.

Enquanto o gate não for executado no commit corrente, o commit é classificado como
**não validado**, mesmo quando revisão estática e testes unitários tenham sido escritos.

## Arquitetura financeira

A cadeia obrigatória é:

`DADOS -> INTELIGÊNCIA -> PREVISÃO -> SINAL -> RISCO -> EXECUÇÃO`

Para componentes LLM:

`LLM/RESEARCH -> HIPÓTESE -> VALIDAÇÃO QUANTITATIVA -> SINAL CANDIDATO -> RISK MANAGER -> MOTOR DETERMINÍSTICO`

Nenhum LLM possui credenciais de broker, altera limites, desliga kill switch ou
submete ordens.

## Gate integral

O gate determinístico executa, em todo o projeto:

- compileall de src/scripts/tests/evals;
- scan de secrets e arquivos proibidos;
- Ruff de erros de alta confiança;
- mypy no core;
- pytest completo com cobertura e branch coverage;
- segunda execução completa de pytest com ordem aleatória diferente;
- compatibilidade real da camada Pydantic AI Harness/Pydantic Evals;
- Bandit;
- pip-audit.

O gate de fontes executa todos os audits oficiais B3/CVM/BCB/NEFIN relacionados,
incluindo identidade 2011–2026, shares, eventos, FCA, COTAHIST, EMISSOR/ISIN,
CVM PIT, CVM Fundos, BVBG.028 e macro.

A falta de runner não elimina nenhum desses requisitos.

## Ferramentas e padrões externos

### NautilusTrader

É benchmark/runtime candidato isolado. Foram absorvidos os padrões úteis de event
runtime, replay e accounting, mas Risk Manager, PIT, provenance, idempotência e
reconciliação permanecem internos. Release candidate não recebe capital real.

### LEAN

Permanece segunda implementação independente para paridade de estratégias simples.

### Qlib e skfolio

Qlib é benchmark externo de pesquisa/ML/fatores. skfolio é benchmark externo de
otimização de portfólio. Nenhum contorna Tournament ou Risk Manager.

### Pydantic AI Harness

É camada opcional de agentes atrás de adapter fixado em minor compatível. Planning,
SubAgents, Memory, SpendLimits, TrajectoryJudge e DynamicWorkflow não definem
autoridade financeira.

### OpenTelemetry / Phoenix / Promptfoo

OpenTelemetry + schema `mf.agent.*` é o contrato de observabilidade. Phoenix é
backend opcional. Promptfoo e Pydantic Evals compartilham um corpus canônico de
regressão e cobrem excessive agency, prompt injection, PII e bypass de risco.

### Data quality

Os contratos financeiros internos são a autoridade. Soda, Pandera e Great
Expectations não são adicionados enquanto apenas duplicarem esses contratos.

### Ibis

Ibis 12 é aprovado como **candidato de portabilidade de consulta** para a futura
paridade DuckDB <-> BigQuery. Não entra no core nem substitui o PITSnapshotStore
antes de um benchmark provar igualdade de row sets, timestamps, tipos e resultados.

### dlt e Dagster

São mantidos como referências futuras. Não entram agora: dlt duplicaria parte da
ingestão/provenance e Dagster adicionaria uma segunda camada de orquestração antes
da infraestrutura cloud existir. Reavaliar somente quando reduzirem código total e
passarem o gate integral.

## Dados novos

CVM Fundos Informe Diário foi incorporado com semântica conservadora:
`available_from = data de coleta`. Reapresentações não são retroativamente
tratadas como conhecidas no passado.

CVM CDA foi promovido a próxima fonte institucional prioritária para composição de
carteiras, mas não será implementado sem parser validado contra o dicionário e
política de confidencialidade/reapresentações.

B3 UP2DATA regulatório foi promovido a próxima fonte B3 prioritária para posição e
resumo de empréstimos de ativos. DataWise fica como upgrade licenciado, não como
pré-requisito para iniciar sinais de short/crowding.

## Redundância removida

Os workflows duplicados de CI/security/audits foram removidos. Permanecem apenas:

- `full-project-gate.yml` como orquestração do gate integral;
- `codeql.yml` para análise CodeQL.

## Condição para main

A branch só pode ser promovida quando o commit corrente tiver evidência de:

1. gate determinístico integral verde em Python suportado;
2. audits oficiais integralmente verdes;
3. CodeQL/security verdes;
4. nenhuma regressão PIT;
5. nenhuma autoridade Research -> Broker;
6. nenhum gate enfraquecido para conseguir aprovação.

LIVE permanece separado: merge em main não autoriza capital real.
