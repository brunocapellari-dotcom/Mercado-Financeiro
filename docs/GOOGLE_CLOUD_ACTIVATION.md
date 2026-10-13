# Ativação Google Cloud — Mercado Financeiro

Esta é a única etapa que exige interação humana antes de o Google executar os gates reais.

Não usar GitHub Actions. Não criar chave JSON de service account.

## 1. Conectar o repositório ao Cloud Build

No Google Cloud Console:

1. selecionar o projeto `ai-holding-prod-bc`;
2. abrir **Cloud Build -> Repositories**;
3. escolher **2nd gen**;
4. **Create host connection**;
5. provider **GitHub**;
6. região **southamerica-east1**;
7. autorizar/instalar o **Cloud Build GitHub App**;
8. liberar somente o repositório `brunocapellari-dotcom/Mercado-Financeiro`;
9. vincular esse repositório à conexão.

A conexão deve ficar na mesma região do trigger: `southamerica-east1`.

## 2. Verificar o deployer da Holding

Service account existente:

`github-deployer@ai-holding-prod-bc.iam.gserviceaccount.com`

Papéis já documentados na fundação Holding:

- Service Usage Admin;
- Artifact Registry Admin;
- Cloud Run Admin;
- Cloud Scheduler Admin;
- Secret Manager Admin;
- IAM Service Account Admin;
- demais papéis de infraestrutura da Holding.

Antes do deploy do Mercado Financeiro, verificar/conceder também:

- **BigQuery Admin** — `roles/bigquery.admin`;
- **Storage Admin** — `roles/storage.admin`;
- **Logs Writer** — `roles/logging.logWriter`.

Não conceder Project IAM Admin. O Terraform do Mercado Financeiro foi alterado para não precisar desse privilégio.

## 3. Criar o gate de validação

Criar um trigger manual/regional:

- nome: `mf-release-gate`;
- região: `southamerica-east1`;
- evento: **Manual invocation**;
- repositório: `Mercado-Financeiro`;
- configuração: **Cloud Build configuration file**;
- arquivo: `cloudbuild.yaml`;
- source inicial: branch `architecture/segregated-market-stack`;
- não usar o deployer privilegiado para código não promovido; usar uma identidade de build sem permissões administrativas.

Executar esse trigger.

O gate roda:

- secret scan;
- deterministic Python 3.11;
- deterministic Python 3.12;
- official-source integrations;
- BRAPI zero-cost preflight;
- Terraform validate;
- Docker build;
- PAPER smoke.

Nenhuma infraestrutura é aplicada por `cloudbuild.yaml`.

## 4. Depois do gate verde

Somente após o gate ficar verde:

1. mergear PR #20 em `main`;
2. criar trigger manual `mf-paper-deploy`;
3. região `southamerica-east1`;
4. source: `main`;
5. arquivo: `cloudbuild.deploy.yaml`;
6. service account do trigger/build: `github-deployer@ai-holding-prod-bc.iam.gserviceaccount.com`;
7. executar o trigger.

O deploy:

- refaz o full gate;
- builda e publica imagem;
- resolve digest;
- rejeita Terraform com qualquer delete;
- aplica Terraform;
- verifica Cloud Run Job privado;
- verifica Cloud Scheduler;
- executa E2E #1;
- executa E2E #2;
- exige as duas execuções concluídas;
- persiste evidência no GCS.

## 5. Grant pós-criação para o data plane

Depois que o primeiro Terraform apply criar as identidades abaixo, conceder **BigQuery Job User** (`roles/bigquery.jobUser`) individualmente a:

- `mf-ingest@ai-holding-prod-bc.iam.gserviceaccount.com`;
- `mf-transform@ai-holding-prod-bc.iam.gserviceaccount.com`;
- `mf-research@ai-holding-prod-bc.iam.gserviceaccount.com`.

Isso evita dar ao deployer permissão para modificar o IAM de todo o projeto.

Depois desses grants, o data plane pode executar jobs BigQuery com identidades segregadas.

## Regra de segurança

- sem GitHub Actions;
- sem WIF GitHub -> GCP;
- sem service-account key;
- sem Project IAM Admin no deployer;
- sem broker secret;
- sem LIVE trading;
- BRAPI somente PAPER/SHADOW delayed;
- B3/CVM/BCB/NEFIN permanecem fontes canônicas para histórico/PIT.
