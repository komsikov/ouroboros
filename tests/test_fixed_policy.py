"""Regression tests for OUROBOROS_FIXED_INFRA_MODELS policy flag."""

from __future__ import annotations

import json

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def _base_settings(srv):
    data = dict(srv._SETTINGS_DEFAULTS)
    data.update(
        {
            "OPENAI_API_KEY": "sk-live-fixed-provider",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OUROBOROS_MODEL": "openai/gpt-5.5",
            "OUROBOROS_MODEL_CODE": "openai/gpt-5.5-mini",
            "OUROBOROS_MODEL_LIGHT": "openai/gpt-5.5-mini",
            "OUROBOROS_MODEL_FALLBACK": "anthropic/claude-sonnet-4.6",
            "OUROBOROS_REVIEW_MODELS": "openai/gpt-5.5,google/gemini-3.5-flash,anthropic/claude-opus-4.6",
        }
    )
    return data


def test_api_settings_get_exposes_fixed_infra_flag_without_hiding_provider_fields(monkeypatch, tmp_path):
    import server as srv

    current = _base_settings(srv)
    monkeypatch.setenv("OUROBOROS_FIXED_INFRA_MODELS", "1")
    monkeypatch.setattr(srv, "load_settings", lambda: dict(current))
    monkeypatch.setattr(srv, "apply_runtime_provider_defaults", lambda settings: (dict(settings), False, []))

    app = Starlette(routes=[Route("/api/settings", endpoint=srv.api_settings_get, methods=["GET"])])
    app.state.drive_root = tmp_path / "drive"
    client = TestClient(app)

    response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["_meta"]["fixed_infra_models"] is True
    assert data["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert data["OPENAI_API_KEY"] != ""


def test_api_settings_post_rejects_core_model_slot_changes_when_fixed(monkeypatch, tmp_path):
    import server as srv
    import ouroboros.gateway.settings as gw_settings

    current = _base_settings(srv)

    monkeypatch.setenv("OUROBOROS_FIXED_INFRA_MODELS", "1")
    monkeypatch.setattr(srv, "load_settings", lambda: dict(current))
    monkeypatch.setattr(srv, "_apply_settings_to_env", lambda *_a, **_k: None)
    monkeypatch.setattr(srv, "_start_supervisor_if_needed", lambda *_a, **_k: False)
    monkeypatch.setattr(srv, "apply_runtime_provider_defaults", lambda settings: (dict(settings), False, []))
    monkeypatch.setattr(gw_settings, "_owner_write_settings", lambda *_a, **_k: None)
    monkeypatch.setattr(gw_settings, "_owner_read_settings_raw", lambda: dict(current))
    monkeypatch.setattr(gw_settings, "_start_supervisor_if_needed_for_request", lambda *_a, **_k: False)

    app = Starlette(routes=[Route("/api/settings", endpoint=srv.api_settings_post, methods=["POST"])])
    app.state.drive_root = tmp_path / "drive"
    app.state.repo_dir = tmp_path / "repo"
    client = TestClient(app)

    response = client.post("/api/settings", json={"OUROBOROS_MODEL": "google/gemini-3.5-flash"})
    assert response.status_code == 400, response.text
    assert "OUROBOROS_FIXED_INFRA_MODELS" in response.text


def test_api_settings_post_allows_review_models_when_fixed(monkeypatch, tmp_path):
    import server as srv
    import ouroboros.gateway.settings as gw_settings

    current = _base_settings(srv)

    monkeypatch.setenv("OUROBOROS_FIXED_INFRA_MODELS", "1")
    monkeypatch.setattr(srv, "load_settings", lambda: dict(current))
    monkeypatch.setattr(srv, "_apply_settings_to_env", lambda *_a, **_k: None)
    monkeypatch.setattr(srv, "_start_supervisor_if_needed", lambda *_a, **_k: False)
    monkeypatch.setattr(srv, "apply_runtime_provider_defaults", lambda settings: (dict(settings), False, []))
    monkeypatch.setattr(gw_settings, "_owner_write_settings", lambda *_a, **_k: None)
    monkeypatch.setattr(gw_settings, "_owner_read_settings_raw", lambda: dict(current))
    monkeypatch.setattr(gw_settings, "_start_supervisor_if_needed_for_request", lambda *_a, **_k: False)

    app = Starlette(routes=[Route("/api/settings", endpoint=srv.api_settings_post, methods=["POST"])])
    app.state.drive_root = tmp_path / "drive"
    app.state.repo_dir = tmp_path / "repo"
    client = TestClient(app)

    response = client.post("/api/settings", json={"OUROBOROS_REVIEW_MODELS": "openai/gpt-5.5,openai/gpt-5.5"})
    assert response.status_code == 200, response.text


def test_fixed_infra_model_env_forces_all_four_core_slots(monkeypatch, tmp_path):
    import ouroboros.config as cfg

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "OUROBOROS_MODEL": "openai/gpt-5.5",
                "OUROBOROS_MODEL_CODE": "openai/gpt-5.5-mini",
                "OUROBOROS_MODEL_LIGHT": "google/gemini-3.5-flash",
                "OUROBOROS_MODEL_FALLBACK": "anthropic/claude-sonnet-4.6",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "SETTINGS_PATH", settings_path, raising=True)
    monkeypatch.setenv("OUROBOROS_FIXED_INFRA_MODELS", "1")
    monkeypatch.setenv("OUROBOROS_FIX_INFRA_MODEL", "openai-compatible::zai-org-glm-51-fp8-vllm")

    loaded = cfg.load_settings()
    assert loaded["OUROBOROS_MODEL"] == "openai-compatible::zai-org-glm-51-fp8-vllm"
    assert loaded["OUROBOROS_MODEL_CODE"] == "openai-compatible::zai-org-glm-51-fp8-vllm"
    assert loaded["OUROBOROS_MODEL_LIGHT"] == "openai-compatible::zai-org-glm-51-fp8-vllm"
    assert loaded["OUROBOROS_MODEL_FALLBACK"] == "openai-compatible::zai-org-glm-51-fp8-vllm"


def test_fixed_infra_compatible_env_forces_openai_compatible_settings(monkeypatch, tmp_path):
    import ouroboros.config as cfg

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "OPENAI_COMPATIBLE_BASE_URL": "https://old-compatible.example/v1",
                "OPENAI_COMPATIBLE_API_KEY": "old-compatible-key",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "SETTINGS_PATH", settings_path, raising=True)
    monkeypatch.setenv("OUROBOROS_FIXED_INFRA_MODELS", "1")
    monkeypatch.setenv("OUROBOROS_FIX_INFRA_BASEURL", "https://new-compatible.example/v1")
    monkeypatch.setenv("OUROBOROS_FIX_INFRA_APIKEY", "new-compatible-key")

    loaded = cfg.load_settings()
    assert loaded["OPENAI_COMPATIBLE_BASE_URL"] == "https://new-compatible.example/v1"
    assert loaded["OPENAI_COMPATIBLE_API_KEY"] == "new-compatible-key"
