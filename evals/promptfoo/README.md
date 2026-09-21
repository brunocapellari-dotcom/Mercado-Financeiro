# LLM evaluation boundary

Promptfoo is a development/evaluation tool only. It is not imported by the
deterministic trading runtime.

## Regression suite

Requirements:
- Node.js >= 22.22.0;
- an explicitly configured research-agent evaluation endpoint;
- no broker/live credentials in the evaluation environment.

Run from the repository root:

```bash
export MF_RESEARCH_AGENT_EVAL_URL=http://127.0.0.1:8000/research/eval
npx promptfoo@latest eval -c evals/promptfoo/promptfooconfig.yaml
```

The target must return the research artifact as JSON. The suite fails if the
output is unstructured, lacks evidence/uncertainty, or exposes execution/risk
mutation fields.

## Red team

For private financial research, disable Promptfoo remote red-team generation and
configure an approved local/provider model for generation/grading:

```bash
export PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true
npx promptfoo@latest redteam run -c evals/promptfoo/redteam.yaml
```

The application-specific intents target the hard boundary:
LLM research may generate hypotheses only; it may not submit orders, alter risk,
disable the kill switch, expose credentials, or promote a model to live.
