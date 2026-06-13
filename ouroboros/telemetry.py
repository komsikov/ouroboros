"""OpenTelemetry tracing with OpenInference conventions for LLM / tool / skill calls.

Design goals:
 - Optional: imports are guarded so the module loads even when the OTel SDK
   is not installed. Helpers turn into no-op context managers in that case.
 - Stable surface: callers only see ``llm_span``, ``tool_span``,
   ``skill_span`` and ``init_telemetry``. Attribute keys follow the
   OpenInference spec so any compatible backend (Phoenix, Langfuse,
   Honeycomb, etc.) renders calls correctly.
 - Configurable via standard OTel env vars (OTEL_EXPORTER_OTLP_ENDPOINT,
   OTEL_SERVICE_NAME, …). Project-specific knobs use OUROBOROS_TELEMETRY_*.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from typing import Any, Dict, Iterator, List, Mapping, Optional

log = logging.getLogger(__name__)

_FALSE_LIKE = {"", "0", "false", "no", "off"}

# OpenInference semantic-convention attribute names. Hard-coded rather than
# imported from openinference-semantic-conventions so the project does not
# require that package at runtime.
class OISpanKind:
    LLM = "LLM"
    TOOL = "TOOL"
    CHAIN = "CHAIN"
    AGENT = "AGENT"


class OIAttr:
    SPAN_KIND = "openinference.span.kind"

    SESSION_ID = "session.id"
    USER_ID = "user.id"

    INPUT_VALUE = "input.value"
    INPUT_MIME = "input.mime_type"
    OUTPUT_VALUE = "output.value"
    OUTPUT_MIME = "output.mime_type"

    LLM_MODEL = "llm.model_name"
    LLM_PROVIDER = "llm.provider"
    LLM_SYSTEM = "llm.system"
    LLM_INVOCATION_PARAMS = "llm.invocation_parameters"
    LLM_PROMPT_TOKENS = "llm.token_count.prompt"
    LLM_COMPLETION_TOKENS = "llm.token_count.completion"
    LLM_TOTAL_TOKENS = "llm.token_count.total"
    LLM_CACHED_TOKENS = "llm.token_count.prompt_details.cache_read"
    LLM_CACHE_WRITE_TOKENS = "llm.token_count.prompt_details.cache_write"

    TOOL_NAME = "tool.name"
    TOOL_DESC = "tool.description"
    TOOL_PARAMS = "tool.parameters"

    # Per-message keys are templated as
    # ``llm.input_messages.{i}.message.role`` / ``.content``.
    LLM_INPUT_MSG_PREFIX = "llm.input_messages"
    LLM_OUTPUT_MSG_PREFIX = "llm.output_messages"


_init_lock = threading.Lock()
_initialized = False
_enabled = False
_capture_content = False
_tracer = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in _FALSE_LIKE


def is_enabled() -> bool:
    return _enabled


def capture_content() -> bool:
    return _capture_content


def init_telemetry(service_name: str = "ouroboros") -> bool:
    """Initialize the global tracer provider once. Returns True on success.

    Idempotent: safe to call from multiple entry points (server, CLI, tests).
    """
    global _initialized, _enabled, _capture_content, _tracer

    with _init_lock:
        if _initialized:
            return _enabled
        _initialized = True

        if not _env_bool("OUROBOROS_TELEMETRY_ENABLED", True):
            log.info("Telemetry disabled via OUROBOROS_TELEMETRY_ENABLED")
            return False

        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            log.info(
                "opentelemetry SDK not installed; tracing is disabled. "
                "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
            )
            return False

        resource = Resource.create({
            "service.name": os.environ.get("OTEL_SERVICE_NAME", service_name),
            "service.version": _resolve_version(),
        })
        provider = TracerProvider(resource=resource)

        exporter = _build_exporter()
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        else:
            log.info("No OTLP exporter configured; spans will be recorded but not exported")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ouroboros")
        _enabled = True
        _capture_content = _env_bool("OUROBOROS_TELEMETRY_CAPTURE_CONTENT", False)
        log.info(
            "OpenTelemetry initialized (service=%s, capture_content=%s)",
            service_name, _capture_content,
        )
        return True


def _resolve_version() -> str:
    try:
        from ouroboros.version import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def _resolve_otlp_api_key() -> Optional[str]:
    """Return the first non-empty API-key env var for the OTLP endpoint."""
    for name in (
        "OTEL_EXPORTER_OTLP_HEADER_API_KEY",
        "OTEL_API_KEY",
        "OTEL_ENDPOINT_API_KEY",
    ):
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _build_otlp_headers() -> Optional[Dict[str, str]]:
    """Build the Authorization header for the OTLP exporter, if a key is set."""
    api_key = _resolve_otlp_api_key()
    if not api_key:
        return None
    return {"Authorization": f"Api-Key {api_key}"}


def _otlp_endpoint_configured() -> bool:
    """True only when an OTLP endpoint is explicitly configured.

    Without this guard the SDK defaults to ``http://localhost:4318`` and the
    HTTP exporter spams ``Failed to export span batch`` retries when nothing
    is listening — which is the normal case for containers started without a
    tracing backend.
    """
    for name in (
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip():
            return True
    return False


def _build_exporter():
    """Construct an OTLP exporter from env. Prefers HTTP/protobuf (lighter deps).

    Returns ``None`` when no OTLP endpoint is configured, so spans are
    recorded in-process but no network exporter is attached — the runtime
    stays silent instead of retrying against ``localhost:4318``.

    Authorization: when one of ``OTEL_EXPORTER_OTLP_HEADER_API_KEY`` /
    ``OTEL_API_KEY`` / ``OTEL_ENDPOINT_API_KEY`` is set, the value is sent
    as ``Authorization: Api-Key <value>`` on every export request.
    """
    if not _otlp_endpoint_configured():
        log.info(
            "OTLP endpoint not configured (OTEL_EXPORTER_OTLP_ENDPOINT unset); "
            "tracing stays enabled in-process but spans will not be exported"
        )
        return None

    protocol = (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL")
        or os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
        or "http/protobuf"
    ).strip().lower()

    headers = _build_otlp_headers()
    exporter_kwargs: Dict[str, Any] = {}
    if headers:
        exporter_kwargs["headers"] = headers

    try:
        if protocol in ("grpc",):
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            return OTLPSpanExporter(**exporter_kwargs)
        # default + http/protobuf + http/json all use the HTTP exporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        return OTLPSpanExporter(**exporter_kwargs)
    except ImportError:
        log.info(
            "OTLP exporter for protocol %s not installed; spans will not be exported",
            protocol,
        )
        return None


@contextlib.contextmanager
def _noop_span() -> Iterator[Any]:
    yield _NoOpSpan()


class _NoOpSpan:
    def set_attribute(self, *_args, **_kwargs) -> None: ...
    def set_attributes(self, *_args, **_kwargs) -> None: ...
    def record_exception(self, *_args, **_kwargs) -> None: ...
    def set_status(self, *_args, **_kwargs) -> None: ...


def _session_id_from_baggage() -> Optional[str]:
    """Read the active session id from OTel baggage, if set by an upstream span."""
    if not _enabled:
        return None
    try:
        from opentelemetry import baggage as _baggage
        value = _baggage.get_baggage(OIAttr.SESSION_ID)
    except Exception:
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _stamp_session(attrs: Dict[str, Any]) -> None:
    """Inject the active session id into ``attrs`` so every span carries it."""
    if OIAttr.SESSION_ID in attrs:
        return
    sid = _session_id_from_baggage()
    if sid:
        attrs[OIAttr.SESSION_ID] = sid


@contextlib.contextmanager
def _span(name: str, attributes: Optional[Mapping[str, Any]] = None) -> Iterator[Any]:
    if not _enabled or _tracer is None:
        yield _NoOpSpan()
        return
    attrs = dict(attributes or {})
    _stamp_session(attrs)
    with _tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield span
        except Exception as exc:  # pragma: no cover — exercised by upstream callers
            try:
                from opentelemetry.trace import Status, StatusCode
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise


def _truncate(value: Any, limit: int = 4096) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated {len(text) - limit} chars]"


def _set_messages(span: Any, messages: List[Dict[str, Any]], prefix: str) -> None:
    if not _capture_content:
        span.set_attribute(f"{prefix}.count", len(messages))
        return
    for i, msg in enumerate(messages):
        role = str(msg.get("role", "")) or ""
        content = msg.get("content")
        if isinstance(content, list):
            # Flatten OpenAI-style content blocks to text for tracing.
            content = "\n".join(
                str(b.get("text", "")) for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if role:
            span.set_attribute(f"{prefix}.{i}.message.role", role)
        if content is not None:
            span.set_attribute(f"{prefix}.{i}.message.content", _truncate(content))
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for j, tc in enumerate(tool_calls):
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or ""
                if name:
                    span.set_attribute(
                        f"{prefix}.{i}.message.tool_calls.{j}.tool_call.function.name",
                        str(name),
                    )
                if args:
                    span.set_attribute(
                        f"{prefix}.{i}.message.tool_calls.{j}.tool_call.function.arguments",
                        _truncate(args),
                    )


@contextlib.contextmanager
def llm_span(
    *,
    model: str,
    provider: str = "",
    messages: Optional[List[Dict[str, Any]]] = None,
    invocation_params: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Iterator[Any]:
    """Span for a single LLM round-trip. Caller sets output via :func:`record_llm_response`."""
    attrs: Dict[str, Any] = {
        OIAttr.SPAN_KIND: OISpanKind.LLM,
        OIAttr.LLM_MODEL: str(model or ""),
    }
    if provider:
        attrs[OIAttr.LLM_PROVIDER] = str(provider)
        attrs[OIAttr.LLM_SYSTEM] = str(provider)
    if invocation_params:
        attrs[OIAttr.LLM_INVOCATION_PARAMS] = _truncate(invocation_params)
    if tools is not None:
        attrs["llm.tools.count"] = len(tools)

    with _span(f"llm.{model or 'chat'}", attrs) as span:
        if messages:
            _set_messages(span, messages, OIAttr.LLM_INPUT_MSG_PREFIX)
        yield span


def record_llm_response(
    span: Any,
    *,
    message: Optional[Dict[str, Any]] = None,
    usage: Optional[Dict[str, Any]] = None,
) -> None:
    """Stamp output message + token usage on a span returned by :func:`llm_span`."""
    if span is None or isinstance(span, _NoOpSpan):
        return
    if message is not None:
        _set_messages(span, [message], OIAttr.LLM_OUTPUT_MSG_PREFIX)
    if usage:
        if (v := usage.get("prompt_tokens")) is not None:
            span.set_attribute(OIAttr.LLM_PROMPT_TOKENS, int(v))
        if (v := usage.get("completion_tokens")) is not None:
            span.set_attribute(OIAttr.LLM_COMPLETION_TOKENS, int(v))
        if (v := usage.get("total_tokens")) is not None:
            span.set_attribute(OIAttr.LLM_TOTAL_TOKENS, int(v))
        if (v := usage.get("cached_tokens")) is not None:
            span.set_attribute(OIAttr.LLM_CACHED_TOKENS, int(v))
        if (v := usage.get("cache_write_tokens")) is not None:
            span.set_attribute(OIAttr.LLM_CACHE_WRITE_TOKENS, int(v))
        if (v := usage.get("cost")) is not None:
            try:
                span.set_attribute("llm.cost", float(v))
            except (TypeError, ValueError):
                pass


@contextlib.contextmanager
def agent_span(
    *,
    name: str,
    task_id: str = "",
    task_type: str = "",
    session_id: str = "",
    user_id: str = "",
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[Any]:
    """Root span for one user request / agent task.

    Sets the OpenInference ``session.id`` / ``user.id`` attributes (used by
    Phoenix / Arize to group traces into sessions) and writes ``session.id``
    into OTel baggage so every descendant span — LLM, tool, skill, even
    those created in worker threads via :func:`use_otel_context` — inherits
    it without callers having to thread the value through manually.

    If ``session_id`` is empty, ``task_id`` is used as a fallback, matching
    the convention that one task is one session unless told otherwise.
    """
    if not _enabled or _tracer is None:
        yield _NoOpSpan()
        return

    sid = str(session_id or task_id or "").strip()
    uid = str(user_id or "").strip()

    attrs: Dict[str, Any] = {OIAttr.SPAN_KIND: OISpanKind.AGENT}
    if sid:
        attrs[OIAttr.SESSION_ID] = sid
    if uid:
        attrs[OIAttr.USER_ID] = uid
    if task_id:
        attrs["task.id"] = str(task_id)
    if task_type:
        attrs["task.type"] = str(task_type)
    if attributes:
        attrs.update(attributes)

    # Propagate session.id / user.id through OTel baggage so child spans
    # (created here or in worker threads after use_otel_context) can stamp it.
    bag_token = None
    try:
        from opentelemetry import baggage as _baggage, context as _context
        ctx = _context.get_current()
        if sid:
            ctx = _baggage.set_baggage(OIAttr.SESSION_ID, sid, context=ctx)
        if uid:
            ctx = _baggage.set_baggage(OIAttr.USER_ID, uid, context=ctx)
        if sid or uid:
            bag_token = _context.attach(ctx)
    except Exception:
        bag_token = None

    try:
        with _tracer.start_as_current_span(name, attributes=attrs) as span:
            try:
                yield span
            except Exception as exc:
                try:
                    from opentelemetry.trace import Status, StatusCode
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                except Exception:
                    pass
                raise
    finally:
        if bag_token is not None:
            try:
                from opentelemetry import context as _context
                _context.detach(bag_token)
            except Exception:
                pass


@contextlib.contextmanager
def chain_span(
    *,
    name: str,
    attributes: Optional[Mapping[str, Any]] = None,
) -> Iterator[Any]:
    """Span for one logical step of the agent loop (e.g. a single round:
    LLM call + the tool calls it triggers). Nests under :func:`agent_span`."""
    attrs: Dict[str, Any] = {OIAttr.SPAN_KIND: OISpanKind.CHAIN}
    if attributes:
        attrs.update(attributes)
    with _span(name, attrs) as span:
        yield span


def current_otel_context() -> Any:
    """Capture the active OTel context so it can be re-attached in a worker
    thread. Returns None when tracing is disabled."""
    if not _enabled:
        return None
    try:
        from opentelemetry.context import get_current
        return get_current()
    except Exception:
        return None


@contextlib.contextmanager
def use_otel_context(ctx: Any) -> Iterator[None]:
    """Re-attach a context captured via :func:`current_otel_context` inside a
    different thread, so spans created here link to the right parent. OTel
    does not propagate context across threads automatically."""
    if ctx is None or not _enabled:
        yield
        return
    try:
        from opentelemetry.context import attach, detach
        token = attach(ctx)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            detach(token)
        except Exception:
            pass


@contextlib.contextmanager
def tool_span(
    *,
    name: str,
    arguments: Optional[Dict[str, Any]] = None,
    description: str = "",
) -> Iterator[Any]:
    """Span for a single tool invocation (function-calling style)."""
    attrs: Dict[str, Any] = {
        OIAttr.SPAN_KIND: OISpanKind.TOOL,
        OIAttr.TOOL_NAME: str(name or ""),
    }
    if description:
        attrs[OIAttr.TOOL_DESC] = str(description)
    if arguments is not None:
        rendered = _truncate(arguments)
        attrs[OIAttr.TOOL_PARAMS] = rendered
        attrs[OIAttr.INPUT_VALUE] = rendered
        attrs[OIAttr.INPUT_MIME] = "application/json"

    with _span(f"tool.{name}", attrs) as span:
        yield span


def record_tool_result(span: Any, result: Any, *, is_error: bool = False) -> None:
    if span is None or isinstance(span, _NoOpSpan):
        return
    span.set_attribute(OIAttr.OUTPUT_VALUE, _truncate(result))
    span.set_attribute(OIAttr.OUTPUT_MIME, "text/plain")
    if is_error:
        try:
            from opentelemetry.trace import Status, StatusCode
            span.set_status(Status(StatusCode.ERROR, "tool returned error"))
        except Exception:
            pass


@contextlib.contextmanager
def skill_span(
    *,
    skill: str,
    script: str = "",
    runtime: str = "",
    args: Optional[List[Any]] = None,
) -> Iterator[Any]:
    """Span for an external skill (subprocess) invocation."""
    attrs: Dict[str, Any] = {
        OIAttr.SPAN_KIND: OISpanKind.TOOL,
        OIAttr.TOOL_NAME: f"skill:{skill}",
        "skill.name": skill,
    }
    if script:
        attrs["skill.script"] = script
    if runtime:
        attrs["skill.runtime"] = runtime
    if args:
        attrs[OIAttr.INPUT_VALUE] = _truncate(args)
        attrs[OIAttr.INPUT_MIME] = "application/json"

    with _span(f"skill.{skill}", attrs) as span:
        yield span


def record_skill_result(
    span: Any,
    *,
    exit_code: Optional[int] = None,
    output: Any = None,
    is_error: bool = False,
) -> None:
    if span is None or isinstance(span, _NoOpSpan):
        return
    if exit_code is not None:
        span.set_attribute("skill.exit_code", int(exit_code))
    if output is not None:
        span.set_attribute(OIAttr.OUTPUT_VALUE, _truncate(output))
        span.set_attribute(OIAttr.OUTPUT_MIME, "text/plain")
    if is_error:
        try:
            from opentelemetry.trace import Status, StatusCode
            span.set_status(Status(StatusCode.ERROR, f"skill failed (exit={exit_code})"))
        except Exception:
            pass


__all__ = [
    "init_telemetry",
    "is_enabled",
    "capture_content",
    "agent_span",
    "chain_span",
    "current_otel_context",
    "use_otel_context",
    "llm_span",
    "record_llm_response",
    "tool_span",
    "record_tool_result",
    "skill_span",
    "record_skill_result",
    "OISpanKind",
    "OIAttr",
]
