# Mercado Financeiro

Unidade quantitativa de pesquisa, validação e operação sistemática para o mercado brasileiro.

## Mandato

Construir uma mesa quantamental/sistemática auditável para B3, inicialmente ações e
ETFs líquidos com horizonte de dias a semanas, usando dados point-in-time, validação
fora da amostra, risco determinístico e execução segregada.

## Arquitetura obrigatória

`DADOS -> INTELIGÊNCIA -> PREVISÃO -> SINAL -> RISCO -> EXECUÇÃO`

Para agentes:

`LLM/RESEARCH -> HIPÓTESE -> VALIDAÇÃO QUANTITATIVA -> SINAL CANDIDATO -> RISK MANAGER -> MOTOR DETERMINÍSTICO`

IA não possui credenciais de trading, não altera limites em runtime e não bypassa
Risk ou Execution.

## Dados

Fontes canônicas incluem B3, CVM, BCB e demais fontes oficiais/auditadas. NEFIN é
benchmark especializado; vendors e broker feeds são adapters, não substitutos da
evidência oficial.

Raw é imutável. Snapshots guardam hash/proveniência. Derivados carregam
`reference_date`, `available_from`, versão e cutoff.

Além de companhias e macro, o projeto já cobre CVM Fundos com política PIT
conservadora. CVM CDA e B3 UP2DATA de empréstimo de ativos são as próximas fontes
prioritárias para posicionamento/fluxos.

## Pesquisa e validação

Nenhuma estratégia recebe capital real sem universo e fundamentals PIT, corporate
actions/total return reconciliados, walk-forward/OOS, custos/slippage/capacidade,
anti-overfitting, paper, shadow, reconciliação, segurança e risco.

O Tournament inclui validação estatística própria e cross-check independente.

## Motor e execução

Backtest, paper, shadow e live compartilham fronteiras Risk -> Execution. O projeto
possui replay determinístico, accounting em Decimal, idempotência, tratamento de
outcome ambíguo, reconciliação independente e kill switch fora da autoridade de IA.

NautilusTrader permanece benchmark/runtime candidato; LEAN é referência externa de
paridade. Nenhum motor externo substitui automaticamente o core.

## Qualidade

O gate canônico é:

`python scripts/run_full_project_gate.py --mode full`

Ele testa o projeto inteiro: compile, secrets/data scan, Ruff, mypy, duas execuções
completas de pytest em ordens diferentes, coverage, agentes/evals, Bandit, pip-audit
e audits oficiais.

Google Cloud Build é o executor canônico desse contrato. GitHub é somente a fonte
de código e não executa CI/CD neste projeto. O gate Google acrescenta secret scan,
Semgrep com regras locais, Terraform validate, build do container e PAPER smoke.

## Estado atual

Arquitetura integrada em PR, com PIT histórico, Tournament, segurança/risk,
replay/accounting, governança de agentes, observabilidade e runtime Google
PAPER/SHADOW. Brapi v2 é fonte secundária delayed somente para validação PAPER;
B3/CVM/BCB/NEFIN permanecem canônicos. O próximo gate real deve ser executado pelo
Cloud Build após a conexão inicial do repositório ao projeto Google.

> LIVE permanece bloqueado até todos os gates de dados, estatística, segurança,
> reconciliação e risco estarem aprovados.
