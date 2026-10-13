from mercado_financeiro.observability import (
    AgentTrace,
    InMemoryAgentTraceSink,
    OpenTelemetryAgentTraceSink,
    digest_result,
    otel_attributes,
)


def test_agent_trace_records_required_observability_without_raw_result():
    result = {"hypothesis": "secret financial research text", "score": 0.7}
    digest = digest_result(result)
    trace = AgentTrace(
        trace_id="trace-1",
        span_id="span-1",
        operation="research.factor_review",
        model="model-x",
        tool_name="data.read",
        cost_usd=0.04,
        latency_ms=123.0,
        result_digest=digest,
        regression_dataset="factor-regression-v1",
    )
    attrs = otel_attributes(trace)

    assert attrs["mf.agent.model"] == "model-x"
    assert attrs["mf.agent.tool.name"] == "data.read"
    assert attrs["mf.agent.cost_usd"] == 0.04
    assert attrs["mf.agent.result_sha256"] == digest
    assert "secret financial research text" not in repr(attrs)


def test_trace_sink_preserves_structured_traces():
    sink = InMemoryAgentTraceSink()
    trace = AgentTrace(
        trace_id="t",
        span_id="s",
        operation="research",
        error_type="TimeoutError",
    )
    sink.emit(trace)
    assert sink.traces == (trace,)


def test_result_digest_is_deterministic_for_mapping_order():
    left = digest_result({"a": 1, "b": 2})
    right = digest_result({"b": 2, "a": 1})
    assert left == right


def test_opentelemetry_sink_exports_only_sanitized_attributes():
    captured = {}

    class Span:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_attribute(self, key, value):
            captured[key] = value

    class Tracer:
        def start_as_current_span(self, name):
            captured["span_name"] = name
            return Span()

    trace = AgentTrace(
        trace_id="trace",
        span_id="span",
        operation="research.news",
        model="model-z",
        tool_name="news.search",
        result_digest=digest_result({"result": "sensitive"}),
        regression_dataset="news-v1",
    )
    OpenTelemetryAgentTraceSink(Tracer()).emit(trace)
    assert captured["span_name"] == "research.news"
    assert captured["mf.agent.model"] == "model-z"
    assert "sensitive" not in repr(captured)
