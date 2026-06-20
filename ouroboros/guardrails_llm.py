"""NeMo Guardrails integration for LLM input/output validation.

Wraps NVIDIA's ``nemoguardrails`` so callers can run input rails before
sending messages to a model and output rails after receiving the response.
Failures are reported either as raised exceptions, validator-fixed
replacements, or plain log records depending on the configured mode.

The module degrades to no-ops when ``nemoguardrails`` is not installed or
when no rails config path is configured, so the import is always safe.

Configuration (env vars, all optional):
 - ``OUROBOROS_GUARDRAILS_ENABLED`` — master switch (default: 1).
 - ``OUROBOROS_NEMO_CONFIG_PATH`` — directory with a NeMo Guardrails config
   (``config.yml``, ``*.co`` Colang flows). Without it, the module is a no-op.
 - ``OUROBOROS_GUARDRAILS_MODE`` — ``block`` (raise on input / replace on
   output), ``fix`` (use the rail's modified output), ``log`` (record only).
   Default: ``log``.
 - ``OUROBOROS_GUARDRAILS_BLOCKED_OUTPUT_TEXT`` — replacement text when the
   response is blocked in ``block`` mode.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_FALSE_LIKE = {"", "0", "false", "no", "off"}

MODE_BLOCK = "block"
MODE_FIX = "fix"
MODE_LOG = "log"
_VALID_MODES = {MODE_BLOCK, MODE_FIX, MODE_LOG}

_DEFAULT_BLOCKED_OUTPUT = (
    "[Output blocked by guardrails: response failed safety validation.]"
)

# Decisions that NeMo emits when a rail refuses / blocks a turn.
_BLOCKING_DECISIONS = {"refuse", "stop", "abort", "block", "self_check_failed"}


class GuardrailsInputBlocked(RuntimeError):
    """Raised when an input message fails validation in ``block`` mode."""

    def __init__(self, violations: List[str]):
        super().__init__("guardrails blocked LLM input: " + "; ".join(violations))
        self.violations = list(violations)


@dataclass
class GuardrailResult:
    passed: bool
    violations: List[str] = field(default_factory=list)
    fixed_text: Optional[str] = None


_init_lock = threading.Lock()
_initialized = False
_enabled = False
_mode = MODE_LOG
_rails: Any = None  # nemoguardrails.LLMRails
_blocked_output_text = _DEFAULT_BLOCKED_OUTPUT


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in _FALSE_LIKE


def is_enabled() -> bool:
    return _enabled


def get_mode() -> str:
    return _mode


def init_guardrails() -> bool:
    """Load the configured NeMo Guardrails rail set once. Idempotent."""
    global _initialized, _enabled, _mode, _rails, _blocked_output_text

    with _init_lock:
        if _initialized:
            return _enabled
        _initialized = True

        if not _env_bool("OUROBOROS_GUARDRAILS_ENABLED", True):
            log.info("Guardrails disabled via OUROBOROS_GUARDRAILS_ENABLED")
            return False

        config_path = (os.environ.get("OUROBOROS_NEMO_CONFIG_PATH") or "").strip()
        if not config_path:
            log.info(
                "Guardrails disabled: OUROBOROS_NEMO_CONFIG_PATH not set "
                "(point it at a NeMo Guardrails config directory to enable)"
            )
            return False

        try:
            from nemoguardrails import LLMRails, RailsConfig  # type: ignore
        except ImportError:
            log.info(
                "nemoguardrails not installed; LLM guardrails are disabled. "
                "Run: pip install nemoguardrails"
            )
            return False

        try:
            config = RailsConfig.from_path(config_path)
            _rails = LLMRails(config)
        except Exception:
            log.warning(
                "Failed to load NeMo Guardrails config from %s", config_path,
                exc_info=True,
            )
            return False

        mode = (os.environ.get("OUROBOROS_GUARDRAILS_MODE") or MODE_LOG).strip().lower()
        if mode not in _VALID_MODES:
            log.warning(
                "Invalid OUROBOROS_GUARDRAILS_MODE=%r; falling back to 'log'", mode
            )
            mode = MODE_LOG
        _mode = mode
        _blocked_output_text = (
            os.environ.get("OUROBOROS_GUARDRAILS_BLOCKED_OUTPUT_TEXT")
            or _DEFAULT_BLOCKED_OUTPUT
        )

        _enabled = True
        log.info(
            "NeMo Guardrails initialized (mode=%s, config=%s)", _mode, config_path,
        )
        return True


def _extract_input_text(messages: List[Dict[str, Any]]) -> str:
    """Concatenate user/system text content for a single rails check."""
    parts: List[str] = []
    for msg in messages or []:
        role = str(msg.get("role", ""))
        if role not in ("user", "system"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
    return "\n\n".join(p for p in parts if p)


def _extract_output_text(message: Dict[str, Any]) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            str(b.get("text", "")) for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _build_options(rails_filter: Dict[str, bool]) -> Any:
    """Construct a ``GenerationOptions`` object that scopes rails execution."""
    from nemoguardrails.rails.llm.options import GenerationOptions  # type: ignore
    # ``log`` enables capture of activated_rails so we can inspect decisions.
    return GenerationOptions(rails=rails_filter, log={"activated_rails": True})


def _parse_rails_outcome(result: Any, original_text: str) -> GuardrailResult:
    """Translate a NeMo ``GenerationResponse`` into our ``GuardrailResult``."""
    response = getattr(result, "response", result)
    if isinstance(response, list) and response:
        response = response[0]
    response_text = ""
    if isinstance(response, dict):
        response_text = str(response.get("content") or "")
    elif isinstance(response, str):
        response_text = response

    violations: List[str] = []
    log_obj = getattr(result, "log", None)
    activated = getattr(log_obj, "activated_rails", None) or []
    for rail in activated:
        rail_type = str(getattr(rail, "type", "") or "")
        rail_name = str(getattr(rail, "name", "") or "")
        stopped = bool(getattr(rail, "stop", False))
        decisions = list(getattr(rail, "decisions", []) or [])
        if stopped or any(str(d).lower() in _BLOCKING_DECISIONS for d in decisions):
            violations.append(f"{rail_type}:{rail_name}" if rail_type or rail_name else "rail_block")

    passed = not violations
    fixed_text: Optional[str] = None
    if not passed and response_text and response_text != original_text:
        fixed_text = response_text
    return GuardrailResult(passed=passed, violations=violations, fixed_text=fixed_text)


def _run_rails(
    rails_messages: List[Dict[str, Any]],
    rails_filter: Dict[str, bool],
    original_text: str,
) -> GuardrailResult:
    if not _enabled or _rails is None:
        return GuardrailResult(passed=True)
    try:
        options = _build_options(rails_filter)
        # Pass a fresh ``state`` dict on every call so NeMo's dialog engine
        # starts from a clean slate.  Without this, a prior blocking decision
        # (refuse / stop / abort) "sticks" inside the LLMRails object and
        # every subsequent call inherits the blocked state — even when the
        # new input is harmless.  This is the root cause of the GLM-4.7 +
        # guardrails "permanent stop after first block" bug.
        result = _rails.generate(messages=rails_messages, options=options, state={})
    except Exception as exc:
        # A rails crash must never break the LLM call itself.
        log.warning("NeMo Guardrails raised %r; treating as passthrough", exc)
        return GuardrailResult(passed=True, violations=[f"rails_error:{exc}"])
    return _parse_rails_outcome(result, original_text)


def _emit_event(event: str, attributes: Dict[str, Any]) -> None:
    """Attach a telemetry event to the current span if OTel is active."""
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span is None:
            return
        span.add_event(event, attributes=attributes)
    except Exception:
        pass


def validate_input(messages: List[Dict[str, Any]]) -> GuardrailResult:
    """Run only the input rails against the combined user/system text."""
    if not _enabled or _rails is None:
        return GuardrailResult(passed=True)
    text = _extract_input_text(messages)
    if not text:
        return GuardrailResult(passed=True)
    result = _run_rails(
        [{"role": "user", "content": text}],
        {"input": True, "dialog": False, "output": False, "retrieval": False},
        original_text=text,
    )
    if not result.passed:
        _emit_event("guardrails.input.violation", {
            "guardrails.mode": _mode,
            "guardrails.violations": ", ".join(result.violations) or "unspecified",
        })
        log.warning(
            "Guardrails input validation failed (mode=%s): %s",
            _mode, result.violations,
        )
    return result


def validate_output(message: Dict[str, Any]) -> GuardrailResult:
    """Run only the output rails against the assistant message content."""
    if not _enabled or _rails is None:
        return GuardrailResult(passed=True)
    text = _extract_output_text(message)
    if not text:
        return GuardrailResult(passed=True)
    # Output rails in NeMo expect a prior user turn for context; we supply a
    # neutral placeholder so the rails focus on the assistant content.
    result = _run_rails(
        [
            {"role": "user", "content": "[upstream prompt elided]"},
            {"role": "assistant", "content": text},
        ],
        {"input": False, "dialog": False, "output": True, "retrieval": False},
        original_text=text,
    )
    if not result.passed:
        _emit_event("guardrails.output.violation", {
            "guardrails.mode": _mode,
            "guardrails.violations": ", ".join(result.violations) or "unspecified",
        })
        log.warning(
            "Guardrails output validation failed (mode=%s): %s",
            _mode, result.violations,
        )
    return result


def enforce_input(messages: List[Dict[str, Any]]) -> None:
    """Raise :class:`GuardrailsInputBlocked` if input fails in ``block`` mode."""
    result = validate_input(messages)
    if result.passed:
        return
    if _mode == MODE_BLOCK:
        raise GuardrailsInputBlocked(result.violations)


def apply_output(
    message: Dict[str, Any], usage: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validate the response and, depending on mode, rewrite ``message`` in place.

    Returns the (possibly modified) ``message`` and ``usage`` so callers can
    chain the return. ``usage['guardrails']`` is populated on violation.
    """
    result = validate_output(message)
    if result.passed:
        return message, usage

    usage = dict(usage or {})
    usage["guardrails"] = {
        "violations": result.violations,
        "mode": _mode,
        "blocked": _mode == MODE_BLOCK,
        "fixed": _mode == MODE_FIX and result.fixed_text is not None,
    }

    if _mode == MODE_FIX and result.fixed_text is not None:
        message["content"] = result.fixed_text
    elif _mode == MODE_BLOCK:
        message["content"] = _blocked_output_text
        # Drop tool calls so the loop does not act on potentially unsafe output.
        if "tool_calls" in message:
            message["tool_calls"] = []
        # Strip provider-private reasoning metadata that is incompatible with
        # the replacement content.  Thinking/reasoning blocks and signatures
        # belong to the original (blocked) model output and cause 400 errors
        # when replayed to the same or a different provider in a subsequent
        # round.
        message.pop("reasoning", None)
        message.pop("reasoning_details", None)
        message.pop("response_id", None)
        _content = message.get("content")
        if isinstance(_content, list):
            _kept: List[Any] = []
            for _block in _content:
                if isinstance(_block, dict):
                    _btype = str(_block.get("type") or "").strip().lower()
                    if _btype in ("thinking", "reasoning", "redacted_thinking"):
                        continue
                    _block.pop("signature", None)
                _kept.append(_block)
            message["content"] = _kept
    return message, usage


__all__ = [
    "GuardrailResult",
    "GuardrailsInputBlocked",
    "MODE_BLOCK",
    "MODE_FIX",
    "MODE_LOG",
    "apply_output",
    "enforce_input",
    "get_mode",
    "init_guardrails",
    "is_enabled",
    "validate_input",
    "validate_output",
]
