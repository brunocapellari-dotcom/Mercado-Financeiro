from __future__ import annotations

import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def call_api(prompt, options, context):
    """Promptfoo provider for the research-only agent evaluation endpoint.

    The endpoint is deliberately external to this file. Tests fail closed when no
    explicit evaluation target is configured.
    """

    url = os.environ.get("MF_RESEARCH_AGENT_EVAL_URL", "").strip()
    if not url:
        raise RuntimeError("MF_RESEARCH_AGENT_EVAL_URL is required")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("evaluation URL must use http or https")

    config = (options or {}).get("config", {})
    timeout = float(config.get("timeout_seconds", 60))
    body = json.dumps(
        {
            "prompt": prompt,
            "mode": "research_eval",
            "metadata": (context or {}).get("vars", {}),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        headers = response.headers

    cost_text = headers.get("X-MF-Cost-USD")
    prompt_tokens = headers.get("X-MF-Prompt-Tokens")
    completion_tokens = headers.get("X-MF-Completion-Tokens")

    result = {"output": raw}
    if cost_text is not None:
        result["cost"] = float(cost_text)
    if prompt_tokens is not None or completion_tokens is not None:
        prompt_count = int(prompt_tokens or 0)
        completion_count = int(completion_tokens or 0)
        result["tokenUsage"] = {
            "prompt": prompt_count,
            "completion": completion_count,
            "total": prompt_count + completion_count,
        }
    return result
