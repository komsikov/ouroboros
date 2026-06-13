"""Telemetry module smoke tests: helpers must no-op cleanly without OTel SDK."""

from __future__ import annotations

import importlib
import os
import sys

import pytest


@pytest.fixture
def fresh_telemetry(monkeypatch):
    """Import a fresh copy of the telemetry module per test so init state resets."""
    monkeypatch.delenv("OUROBOROS_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("OUROBOROS_TELEMETRY_CAPTURE_CONTENT", raising=False)
    sys.modules.pop("ouroboros.telemetry", None)
    module = importlib.import_module("ouroboros.telemetry")
    yield module
    sys.modules.pop("ouroboros.telemetry", None)


def test_helpers_are_no_op_until_initialized(fresh_telemetry):
    telemetry = fresh_telemetry
    assert telemetry.is_enabled() is False

    with telemetry.llm_span(model="gpt-x", provider="openai", messages=[{"role": "user", "content": "hi"}]) as span:
        telemetry.record_llm_response(span, message={"role": "assistant", "content": "hello"}, usage={"prompt_tokens": 3})

    with telemetry.tool_span(name="shell_run", arguments={"cmd": "ls"}) as span:
        telemetry.record_tool_result(span, "ok")

    with telemetry.skill_span(skill="weather", script="scripts/run.py", runtime="python", args=["NYC"]) as span:
        telemetry.record_skill_result(span, exit_code=0, output="sunny")


def test_disabled_flag_keeps_initialization_off(monkeypatch, fresh_telemetry):
    monkeypatch.setenv("OUROBOROS_TELEMETRY_ENABLED", "0")
    assert fresh_telemetry.init_telemetry() is False
    assert fresh_telemetry.is_enabled() is False


def test_init_telemetry_succeeds_if_sdk_present(monkeypatch, fresh_telemetry):
    pytest.importorskip("opentelemetry.sdk.trace")
    monkeypatch.delenv("OUROBOROS_TELEMETRY_ENABLED", raising=False)
    # No exporter env to avoid network calls; processor still receives spans in-memory.
    ok = fresh_telemetry.init_telemetry(service_name="ouroboros-tests")
    assert ok is True
    assert fresh_telemetry.is_enabled() is True

    with fresh_telemetry.tool_span(name="noop", arguments={"a": 1}) as span:
        fresh_telemetry.record_tool_result(span, "done")


def test_capture_content_toggle(monkeypatch, fresh_telemetry):
    pytest.importorskip("opentelemetry.sdk.trace")
    monkeypatch.setenv("OUROBOROS_TELEMETRY_CAPTURE_CONTENT", "1")
    fresh_telemetry.init_telemetry(service_name="ouroboros-tests")
    assert fresh_telemetry.capture_content() is True


def test_no_otlp_endpoint_skips_exporter(monkeypatch, fresh_telemetry):
    """Without OTEL_EXPORTER_OTLP_ENDPOINT, _build_exporter() must return None
    so the SDK does not retry against the default localhost:4318."""
    for name in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    assert fresh_telemetry._build_exporter() is None
    assert fresh_telemetry._otlp_endpoint_configured() is False


def test_otlp_endpoint_env_builds_exporter(monkeypatch, fresh_telemetry):
    pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.example.com:4318")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    assert fresh_telemetry._otlp_endpoint_configured() is True
    assert fresh_telemetry._build_exporter() is not None


def test_otlp_api_key_builds_authorization_header(monkeypatch, fresh_telemetry):
    """API-key env var must become an ``Authorization: Api-Key ...`` header."""
    for name in (
        "OTEL_EXPORTER_OTLP_HEADER_API_KEY",
        "OTEL_API_KEY",
        "OTEL_ENDPOINT_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    t = fresh_telemetry
    assert t._build_otlp_headers() is None  # no key → no header

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADER_API_KEY", "  secret-123  ")
    assert t._build_otlp_headers() == {"Authorization": "Api-Key secret-123"}

    # Precedence: header-specific name wins over the generic ones.
    monkeypatch.setenv("OTEL_API_KEY", "fallback")
    assert t._resolve_otlp_api_key() == "secret-123"

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_HEADER_API_KEY")
    assert t._resolve_otlp_api_key() == "fallback"


def test_spans_form_single_trace_with_thread_propagation(fresh_telemetry):
    """agent → chain → {llm, tool-in-worker-thread} must share one trace and
    nest correctly, proving the orphaned-span bug is fixed."""
    pytest.importorskip("opentelemetry.sdk.trace")
    import threading

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    t = fresh_telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Wire the module to our in-memory provider without network exporters.
    t._enabled = True
    t._tracer = provider.get_tracer("test")

    with t.agent_span(name="agent.task", task_id="T1"):
        with t.chain_span(name="round.1"):
            with t.llm_span(model="m", provider="openai"):
                pass
            captured = t.current_otel_context()

            def work():
                with t.use_otel_context(captured):
                    with t.tool_span(name="shell", arguments={"cmd": "ls"}):
                        pass

            th = threading.Thread(target=work)
            th.start()
            th.join()

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    agent = by_name["agent.task"]
    chain = by_name["round.1"]
    llm = by_name["llm.m"]
    tool = by_name["tool.shell"]

    trace_id = agent.context.trace_id
    assert chain.context.trace_id == trace_id
    assert llm.context.trace_id == trace_id
    assert tool.context.trace_id == trace_id  # worker-thread span joined the trace

    assert agent.parent is None
    assert chain.parent.span_id == agent.context.span_id
    assert llm.parent.span_id == chain.context.span_id
    assert tool.parent.span_id == chain.context.span_id


def test_session_id_stamped_on_every_span_including_worker_thread(fresh_telemetry):
    """session.id (OpenInference) must appear on agent, chain, llm and tool
    spans — even the tool span created in a worker thread."""
    pytest.importorskip("opentelemetry.sdk.trace")
    import threading

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    t = fresh_telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    t._enabled = True
    t._tracer = provider.get_tracer("test")

    with t.agent_span(name="agent.task", task_id="T1", session_id="sess-42", user_id="alice"):
        with t.chain_span(name="round.1"):
            with t.llm_span(model="m", provider="openai"):
                pass
            captured = t.current_otel_context()

            def work():
                with t.use_otel_context(captured):
                    with t.tool_span(name="shell", arguments={"cmd": "ls"}):
                        pass

            th = threading.Thread(target=work)
            th.start()
            th.join()

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    for name in ("agent.task", "round.1", "llm.m", "tool.shell"):
        attrs = by_name[name].attributes
        assert attrs.get("session.id") == "sess-42", f"{name} missing session.id"

    assert by_name["agent.task"].attributes.get("user.id") == "alice"


def test_session_id_defaults_to_task_id_when_not_provided(fresh_telemetry):
    """Fallback: if no session_id is passed, task_id stands in so traces still group."""
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    t = fresh_telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    t._enabled = True
    t._tracer = provider.get_tracer("test")

    with t.agent_span(name="agent.task", task_id="task-99"):
        with t.tool_span(name="shell"):
            pass

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    assert by_name["agent.task"].attributes.get("session.id") == "task-99"
    assert by_name["tool.shell"].attributes.get("session.id") == "task-99"


def test_sibling_chains_nest_under_agent_not_each_other(fresh_telemetry):
    """Sequential rounds must be siblings under the agent span, not nested."""
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    t = fresh_telemetry
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    t._enabled = True
    t._tracer = provider.get_tracer("test")

    with t.agent_span(name="agent.task"):
        # Mimic the loop's manual enter/exit of per-round chain spans.
        cm1 = t.chain_span(name="round.1")
        cm1.__enter__()
        cm1.__exit__(None, None, None)
        cm2 = t.chain_span(name="round.2")
        cm2.__enter__()
        cm2.__exit__(None, None, None)

    by_name = {s.name: s for s in exporter.get_finished_spans()}
    agent = by_name["agent.task"]
    r1 = by_name["round.1"]
    r2 = by_name["round.2"]
    assert r1.parent.span_id == agent.context.span_id
    assert r2.parent.span_id == agent.context.span_id
    assert r1.context.trace_id == agent.context.trace_id == r2.context.trace_id
