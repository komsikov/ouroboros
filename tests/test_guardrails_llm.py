"""Guardrails LLM module backed by NeMo Guardrails (stubbed API in tests)."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest


@pytest.fixture
def fresh_guardrails(monkeypatch):
    for key in (
        "OUROBOROS_GUARDRAILS_ENABLED",
        "OUROBOROS_GUARDRAILS_MODE",
        "OUROBOROS_NEMO_CONFIG_PATH",
        "OUROBOROS_GUARDRAILS_BLOCKED_OUTPUT_TEXT",
    ):
        monkeypatch.delenv(key, raising=False)
    sys.modules.pop("ouroboros.guardrails_llm", None)
    module = importlib.import_module("ouroboros.guardrails_llm")
    yield module
    sys.modules.pop("ouroboros.guardrails_llm", None)


def test_disabled_via_env(monkeypatch, fresh_guardrails):
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_ENABLED", "0")
    assert fresh_guardrails.init_guardrails() is False
    assert fresh_guardrails.is_enabled() is False
    fresh_guardrails.enforce_input([{"role": "user", "content": "hi"}])  # no raise


def test_no_config_path_means_passthrough(fresh_guardrails):
    assert fresh_guardrails.init_guardrails() is False
    result = fresh_guardrails.validate_output({"role": "assistant", "content": "hi"})
    assert result.passed is True


class _FakeRail:
    def __init__(self, *, name: str, rail_type: str, stopped: bool = False):
        self.name = name
        self.type = rail_type
        self.stop = stopped
        self.decisions = ["refuse"] if stopped else ["allow"]


class _FakeLog:
    def __init__(self, rails: List[_FakeRail]):
        self.activated_rails = rails


class _FakeResponse:
    def __init__(self, response: Any, rails: List[_FakeRail]):
        self.response = response
        self.log = _FakeLog(rails)


class _FakeLLMRails:
    """Trigger rule: any message whose text contains ``BAD`` activates a
    stop-rail; the rails category determines whether it's an input or
    output violation. The rewritten response is ``SAFE``.
    """

    def __init__(self, *_args, **_kwargs):
        pass

    def generate(self, *, messages: List[Dict[str, Any]], options: Any):
        rails_filter = getattr(options, "rails", {}) or {}
        text = ""
        if messages:
            text = str(messages[-1].get("content") or "")
        is_bad = "BAD" in text
        rail_type = "input" if rails_filter.get("input") else "output"
        rails = [_FakeRail(name=f"self_check_{rail_type}", rail_type=rail_type, stopped=is_bad)]
        response_msg = {"role": "assistant", "content": "SAFE" if is_bad else text}
        return _FakeResponse([response_msg], rails)


def _install_fake_nemo(monkeypatch):
    class _FakeRailsConfig:
        @classmethod
        def from_path(cls, _path):
            return cls()

    class _FakeGenerationOptions:
        def __init__(self, *, rails=None, log=None):
            self.rails = rails or {}
            self.log = log

    nemo = SimpleNamespace(LLMRails=_FakeLLMRails, RailsConfig=_FakeRailsConfig)
    options_mod = SimpleNamespace(GenerationOptions=_FakeGenerationOptions)
    rails_pkg = SimpleNamespace(llm=SimpleNamespace(options=options_mod))
    monkeypatch.setitem(sys.modules, "nemoguardrails", nemo)
    monkeypatch.setitem(sys.modules, "nemoguardrails.rails", rails_pkg)
    monkeypatch.setitem(sys.modules, "nemoguardrails.rails.llm", rails_pkg.llm)
    monkeypatch.setitem(sys.modules, "nemoguardrails.rails.llm.options", options_mod)


def test_block_mode_raises_on_input(monkeypatch, tmp_path, fresh_guardrails):
    _install_fake_nemo(monkeypatch)
    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "block")
    assert fresh_guardrails.init_guardrails() is True

    with pytest.raises(fresh_guardrails.GuardrailsInputBlocked) as excinfo:
        fresh_guardrails.enforce_input([{"role": "user", "content": "this is BAD input"}])
    assert any("input" in v.lower() for v in excinfo.value.violations)


def test_log_mode_records_but_passes(monkeypatch, tmp_path, fresh_guardrails):
    _install_fake_nemo(monkeypatch)
    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "log")
    fresh_guardrails.init_guardrails()

    # Should not raise even though content fails.
    fresh_guardrails.enforce_input([{"role": "user", "content": "BAD payload"}])


def test_block_mode_rewrites_output(monkeypatch, tmp_path, fresh_guardrails):
    _install_fake_nemo(monkeypatch)
    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "block")
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_BLOCKED_OUTPUT_TEXT", "[blocked]")
    fresh_guardrails.init_guardrails()

    msg = {"role": "assistant", "content": "BAD answer", "tool_calls": [{"id": "1"}]}
    new_msg, new_usage = fresh_guardrails.apply_output(msg, {"prompt_tokens": 5})
    assert new_msg["content"] == "[blocked]"
    assert new_msg["tool_calls"] == []
    assert new_usage["guardrails"]["blocked"] is True
    assert new_usage["guardrails"]["violations"]


def test_fix_mode_uses_validator_output(monkeypatch, tmp_path, fresh_guardrails):
    _install_fake_nemo(monkeypatch)
    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "fix")
    fresh_guardrails.init_guardrails()

    msg = {"role": "assistant", "content": "BAD answer"}
    new_msg, new_usage = fresh_guardrails.apply_output(msg, {})
    # In the fake, blocked responses are rewritten to "SAFE".
    assert new_msg["content"] == "SAFE"
    assert new_usage["guardrails"]["fixed"] is True
    assert new_usage["guardrails"]["blocked"] is False


def test_passthrough_when_text_is_clean(monkeypatch, tmp_path, fresh_guardrails):
    _install_fake_nemo(monkeypatch)
    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "block")
    fresh_guardrails.init_guardrails()

    # No BAD token -> no violation -> no exception, no message rewrite.
    fresh_guardrails.enforce_input([{"role": "user", "content": "ordinary prompt"}])
    msg = {"role": "assistant", "content": "ordinary response"}
    new_msg, new_usage = fresh_guardrails.apply_output(msg, {"prompt_tokens": 5})
    assert new_msg["content"] == "ordinary response"
    assert "guardrails" not in new_usage


def test_rails_crash_does_not_break_call(monkeypatch, tmp_path, fresh_guardrails):
    class _BrokenRails:
        def __init__(self, *_a, **_kw):
            pass

        def generate(self, **_kwargs):
            raise RuntimeError("rails exploded")

    _install_fake_nemo(monkeypatch)
    # Replace LLMRails with the broken one after the fake module is in place.
    import nemoguardrails  # type: ignore
    monkeypatch.setattr(nemoguardrails, "LLMRails", _BrokenRails)

    monkeypatch.setenv("OUROBOROS_NEMO_CONFIG_PATH", str(tmp_path))
    monkeypatch.setenv("OUROBOROS_GUARDRAILS_MODE", "block")
    fresh_guardrails.init_guardrails()

    # Even though rails crash, the call must pass through.
    fresh_guardrails.enforce_input([{"role": "user", "content": "BAD"}])
    msg = {"role": "assistant", "content": "BAD"}
    new_msg, new_usage = fresh_guardrails.apply_output(msg, {})
    assert new_msg["content"] == "BAD"
    assert "guardrails" not in new_usage
