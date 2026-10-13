# Mercado Financeiro — GO-LIVE STATUS

Data de referência: 2026-10-13  
Escopo deste gate: **PAPER/SHADOW somente**. Execução LIVE com dinheiro real permanece fora do escopo e desabilitada.

## Estado objetivo

A release somente pode ser considerada GO-LIVE PAPER/SHADOW quando, simultaneamente:

1. gate completo de código, segurança, fontes e infraestrutura estiver verde no mesmo commit;
2. imagem de runtime estiver publicada por digest imutável;
3. Terraform estiver validado e aplicado sem ações destrutivas;
4. fonte de preço atual estiver legalmente/autorizadamente disponível ao runtime;
5. Secret Manager possuir a versão do segredo de acesso, sem segredo em Git/log;
6. Cloud Run Job `mf-paper-shadow` estiver privado e invocável apenas pelas identidades autorizadas;
7. duas execuções E2E consecutivas ocorrerem sem edição de código/configuração;
8. evidência de cada execução estiver preservada no bucket RAW versionado;
9. LIVE continuar sem identidade, segredo de broker ou caminho de submit de ordens reais.

## Evidência já comprovada

Commit **024ded70b2d28921ba36de1feb9d4bb144edc0c2**:

- `full-project-gate`: PASS;
- CodeQL: PASS;
- deterministic Python 3.11: PASS;
- deterministic Python 3.12: PASS;
- identidade histórica B3/CVM: PASS;
- histórico de ações/FRE: PASS;
- BVBG: PASS;
- macro/BCB: PASS;
- CVM PIT: PASS;
- eventos corporativos B3: PASS;
- regressões/diagnósticos de fontes: PASS.

Esse commit é a última evidência completa verde antes da camada operacional/deploy adicionada depois.

## Alterações operacionais posteriores ao último gate verde

Na branch `architecture/segregated-market-stack` foram adicionados:

- correção de marcação stale em PAPER/SHADOW, com regressão dedicada;
- `scripts/run_operational_cycle.py` com source audit + PAPER smoke + market-data preflight;
- fail-closed quando não existe fonte de preço autorizada;
- imagem Docker non-root e base pinada por digest;
- Terraform no projeto compartilhado `ai-holding-prod-bc`;
- datasets `raw -> normalized -> canonical -> derived -> analytics`, com `research` isolado;
- Cloud Run Job `mf-paper-shadow` com identidade própria;
- Secret Manager metadata `mf-authorized-price-report-url`, sem versão/segredo no repositório;
- evidência operacional append-only no bucket RAW versionado;
- deploy somente por imagem Artifact Registry imutável `@sha256`;
- workflow manual `deploy-paper-shadow.yml`;
- validação de Terraform, imagem e PAPER smoke adicionada ao gate final;
- PR de segurança da Holding #67 preparando WIF dedicado `mf-deploy-main`.

## Estado atual dos gates

### DONE com evidência executada

- núcleo determinístico;
- testes Python 3.11/3.12 no commit verde;
- segurança CodeQL no commit verde;
- integração das fontes prioritárias cobertas pelo gate atual;
- controles PIT e anti-lookahead;
- risk/execution/accounting simulados;
- PAPER/SHADOW sem BrokerAdapter real;
- fail-closed de dados inconsistentes;
- LIVE bloqueado por arquitetura.

### READY / aguardando nova execução do CI

- Terraform final;
- Docker runtime;
- novo operational cycle;
- persistência de evidência;
- cloud layer contract final;
- gate `infra-validation`.

Em 13/10/2026, os workflows GitHub Actions do Mercado Financeiro e da AI-Holding passaram a falhar antes de qualquer step ser iniciado. Os jobs apresentam zero etapas executadas, inclusive CodeQL. Isso caracteriza indisponibilidade/alocação externa do executor e não fornece evidência de regressão do código.

## BLOCKERS HUMANOS

### H1 — Aprovar a nova fronteira WIF

PR da Holding: **AI-Holding #67** — `security: authorize Mercado Financeiro keyless PAPER/SHADOW deploy`.

A PR cria um provider dedicado e estreito:

- repositório exato: `brunocapellari-dotcom/Mercado-Financeiro`;
- branch exata: `main`;
- workflow exato: `.github/workflows/deploy-paper-shadow.yml`;
- sem chave JSON;
- somente impersonação do deployer existente;
- nenhuma permissão de broker/LIVE.

**Ação humana:** revisar e aprovar/mergear a PR #67 somente após o CI voltar a executar e ficar verde. Não ampliar o provider existente `ai-holding-main`.

### H2 — Fornecer uma fonte de market data autorizada para automação

O runtime deliberadamente não raspa páginas B3 nem adivinha endpoint. O segredo esperado é:

`mf-authorized-price-report-url`

Ele deve apontar para um acesso autorizado/licenciado compatível com `BVBG.086.01` ou `BVBG.186.01`, ou o adapter deverá ser trocado por outro distribuidor autorizado antes do deploy.

**Ação humana:** contratar/habilitar ou indicar um acesso autorizado de market data. Não colar token/segredo em GitHub, chat, issue ou arquivo.

## Sequência após os blockers

1. CI da Holding #67 verde;
2. aprovação/merge da Holding #67;
3. CI do Mercado Financeiro verde no head final;
4. merge do PR #20 em `main`;
5. criar/adicionar versão do segredo `mf-authorized-price-report-url`;
6. disparar manualmente `deploy-paper-shadow`;
7. workflow constrói imagem, resolve digest, valida segredo, planeja Terraform e rejeita qualquer delete;
8. aplica infraestrutura;
9. confirma job privado;
10. executa acceptance #1;
11. executa acceptance #2 sem edição;
12. exige duas execuções concluídas;
13. preserva evidências no RAW;
14. somente então marcar PAPER/SHADOW como GO-LIVE.

## Regra LIVE

Nenhuma parte deste release gate autoriza negociação com dinheiro real. LIVE exige aprovação humana separada, credenciais segregadas, risk/reconciliation/kill-switch live e gates adicionais.
