# Mercado Financeiro — GO-LIVE STATUS

Data de referência: 2026-10-13

Escopo deste gate: **PAPER/SHADOW em Google Cloud**. Execução LIVE com dinheiro real permanece fora do escopo e desabilitada.

## Arquitetura de execução aprovada

Código e revisão:
GitHub -> Google Cloud Build

Dados históricos/canônicos:
B3 + CVM + BCB + NEFIN -> RAW -> NORMALIZED -> CANONICAL -> DERIVED -> ANALYTICS

Market data do piloto PAPER:
BRAPI v2 delayed polling -> freshness gate -> synthetic PAPER spread -> deterministic risk -> simulated execution -> accounting -> immutable evidence

Execução:
Google Cloud Build -> Artifact Registry -> Terraform -> Cloud Run Job -> Cloud Scheduler

GitHub Actions não faz parte da arquitetura operacional.

## Último baseline integralmente executado

Commit `024ded70b2d28921ba36de1feb9d4bb144edc0c2`:

- whole-project gate: PASS;
- CodeQL: PASS;
- Python 3.11: PASS;
- Python 3.12: PASS;
- identidade B3/CVM 2011–2026: PASS;
- FRE/share history: PASS;
- BVBG: PASS;
- macro/BCB: PASS;
- CVM PIT: PASS;
- eventos corporativos B3: PASS;
- source diagnostics: PASS.

Esse é o último baseline comprovado antes da migração do executor para Google.

## Mudanças posteriores

A branch `architecture/segregated-market-stack` agora contém:

- correção de stale marks em PAPER/SHADOW;
- BRAPI market-data provider seguro e polling-only;
- teste de schema baseado no SDK oficial BRAPI v2;
- PETR4/VALE3/MGLU3/ITUB4 como sandbox zero-cost sem API key;
- quote freshness gate;
- synthetic bid/ask explicitamente classificado como PAPER, nunca como exchange quote;
- PAPER cycle que pula dado stale ou janela fechada em vez de inventar execução;
- runtime Docker non-root;
- Cloud data layers: raw -> normalized -> canonical -> derived -> analytics;
- Google Cloud Build como gate canônico;
- Cloud Build deploy pipeline;
- Artifact Registry image por digest imutável;
- Terraform state isolado em `mercado-financeiro/prod`;
- Cloud Run Job privado `mf-paper-shadow`;
- Cloud Scheduler `mf-paper-shadow-market-hours`;
- evidência append-only no bucket RAW versionado;
- acceptance E2E obrigatório duas vezes sem edição;
- qualquer Terraform plan com delete é rejeitado;
- LIVE continua sem broker secret, broker adapter real ou identidade de execução.

## Market data

### PAPER/SHADOW zero-cost

Provider primário do piloto: **BRAPI v2**.

Regras:

- somente polling delayed;
- sem WebSocket/live feed;
- sandbox sem chave restrito aos tickers documentados no Terraform;
- default: PETR4;
- atualização esperada compatível com ciclo de 30 minutos;
- quote stale é SKIP, não fill;
- synthetic spread default: 20 bps;
- proibido reutilizar esse feed como prova de cotação executável;
- proibido promover o adapter para LIVE.

Yahoo/yfinance não é fonte canônica e não entra no runtime primário.

### Histórico/PIT

B3/CVM/BCB/NEFIN continuam canônicos conforme contratos já auditados. BRAPI não substitui essas fontes.

## Executor Google

`cloudbuild.yaml` é o gate de release:

1. secret scan;
2. Python 3.11 deterministic gate;
3. Python 3.12 deterministic gate;
4. official-source integrations;
5. BRAPI preflight;
6. Terraform fmt/init/validate;
7. Docker build;
8. PAPER smoke;
9. evidence summary.

`cloudbuild.deploy.yaml` é o deploy:

1. full release gate;
2. Terraform validate;
3. build/push image;
4. resolve immutable digest;
5. Terraform plan;
6. reject any delete;
7. Terraform apply;
8. verify private Cloud Run Job;
9. verify scheduler;
10. acceptance cycle #1;
11. acceptance cycle #2;
12. require both Completed=True;
13. persist release evidence in GCS.

## Custo

A implementação foi desenhada para permanecer dentro das faixas gratuitas enquanto o volume for baixo:

- Cloud Build: usar somente builds necessários, sem GitHub Actions;
- Cloud Run Job: 1 vCPU / 512 MiB, execução curta;
- Cloud Scheduler: um job;
- BRAPI sandbox: sem chave/custo para o piloto;
- BigQuery/GCS: volume pequeno e governado.

Não há contratação de ANBIMA Feed, market-data B3 pago ou broker feed nesta release.

## Bloqueio externo atual

O código não possui acesso direto ao projeto Google Cloud nesta conversa. Para executar o primeiro deploy real, o projeto `ai-holding-prod-bc` precisa:

1. conectar o repositório `brunocapellari-dotcom/Mercado-Financeiro` ao Cloud Build;
2. permitir que o service account `github-deployer@ai-holding-prod-bc.iam.gserviceaccount.com` execute a infraestrutura do Mercado Financeiro.

Papéis que não aparecem comprovados na fundação atual e precisam ser verificados/concedidos:

- BigQuery Admin;
- Storage Admin;
- Logs Writer.

Os papéis de Artifact Registry, Cloud Run, Cloud Scheduler, Service Usage e IAM Service Account Admin já constam na fundação da Holding.

## Critério de GO-LIVE PAPER/SHADOW

Somente marcar GO-LIVE depois de:

- Google Cloud Build do head final verde;
- deploy por digest imutável;
- Terraform sem deletes;
- Cloud Run Job privado;
- Cloud Scheduler ativo;
- acceptance #1 verde;
- acceptance #2 verde sem edição intermediária;
- evidências presentes no GCS;
- LIVE ainda bloqueado.

## LIVE

Nenhuma parte desta release autoriza capital real. LIVE exige decisão humana separada, feed adequado, broker adapter, reconciliação independente, kill switch live, credenciais segregadas e novo gate de segurança.
