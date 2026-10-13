# Deployment Boundaries — Research x Live

## Objetivo

Implementar separação física e lógica entre pesquisa e execução real. O desenho é independente do provedor de nuvem, mas em GCP a implementação recomendada é usar projetos/contas de serviço distintos.

## Research zone

Pode conter:

- notebooks, jobs de pesquisa e backtest;
- ingestão e datasets point-in-time;
- feature/model artifacts;
- paper/shadow sem credencial de trading real;
- LLMs e agentes de análise.

Não pode conter:

- broker trading secret;
- permissão de submit/cancel de ordens reais;
- segredo de webhook de execução live;
- permissão para alterar limites/kill switch live.

## Live execution zone

Serviços mínimos separados:

1. **Risk Service** — determinístico; recebe OrderIntent e contexto de risco; retorna allow/deny.
2. **Execution Service** — aceita somente intents aprovadas; mantém idempotência e BrokerAdapter.
3. **Reconciliation Service** — compara ledger interno x broker de forma independente.
4. **Kill Switch** — estado independente consultado pelo Risk Service e acionável sem LLM.
5. **Execution Audit Sink** — append-only/tamper-evident.

Somente a zona live possui identidade capaz de ler broker credentials.

## Identidade e IAM

Criar identidades distintas, equivalentes a:

- `mf-research-ingestion`;
- `mf-research-model`;
- `mf-paper-shadow`;
- `mf-live-risk`;
- `mf-live-execution`;
- `mf-live-reconciliation`;
- `mf-live-audit`.

A identidade `mf-live-execution` é a única com acesso ao segredo de trading. `mf-live-risk` não precisa conhecer credenciais de broker. LLMs usam identidade Research sem acesso ao Secret Manager live.

## Rede

Research e Live não compartilham egress irrestrito. Live usa default-deny e allowlist somente para endpoints necessários do broker/vendor, secret manager, logging/audit e serviços internos autorizados.

Quando suportado pelo broker/vendor, restringir acesso por IP estático/allowlist. Webhooks devem entrar por endpoint dedicado com verificação criptográfica, timestamp e anti-replay antes de qualquer mudança de estado.

## Secrets

Broker credentials:

- nunca entram no GitHub repository;
- nunca entram em GitHub Actions de PR/pesquisa;
- nunca entram em prompts/logs;
- são lidas em runtime somente pela identidade live autorizada;
- têm rotação e revogação testáveis.

## Artefatos entre zonas

Research não chama o broker. O único fluxo para Live é um artefato promovido e versionado, contendo no mínimo:

- model/strategy ID e versão;
- commit/run ID;
- universe/data vintage;
- parâmetros aprovados;
- hashes/digests;
- evidência dos gates;
- validade temporal.

Live valida a assinatura/hash e a promoção antes de carregar o artefato.

## Gates de deploy

Deploy live é bloqueado sem evidência válida de:

`backtest -> walk-forward -> paper -> shadow -> reconciliation -> security test -> risk validation`

Mudança de Risk Limits, BrokerAdapter, idempotency, kill switch, reconciliação ou credenciais exige revisão e aprovação humana explícita antes de produção.

## Logs

Logs de execução devem ser separados de logs de Research e preservar:

- OrderIntent;
- decisão de risco e razões;
- client_order_id/idempotency_key hash;
- broker ack/order ID;
- fill/cancel/reject;
- snapshot de limites;
- feed-health usado na decisão;
- reconciliação;
- kill-switch events;
- configuração e identidade do serviço.

O armazenamento deve ser append-only ou tamper-evident e ter retenção definida antes de live.
