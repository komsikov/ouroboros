import asyncio
import importlib.util
import os
import sys
import pytest
from pathlib import Path


def _load_daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("OUROBOROS_SKILL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("HOST_SERVICE_TOKEN", "token")
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "a2a_daemon.py"
    spec = importlib.util.spec_from_file_location(f"a2a_daemon_test_{id(tmp_path)}", module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dispatch_rejects_owner_slash_commands(tmp_path, monkeypatch):
    daemon = _load_daemon(tmp_path, monkeypatch)

    async def run():
        try:
            await daemon._dispatch_to_host("/panic")
        except ValueError as exc:
            assert "slash commands" in str(exc)
        else:
            raise AssertionError("slash command was not rejected")

    asyncio.run(run())


def test_dispatch_adds_transport_metadata_and_timeout(tmp_path, monkeypatch):
    daemon = _load_daemon(tmp_path, monkeypatch)
    calls = []

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/chat/allocate-internal"):
            return Response({"chat_id": -123})
        return Response({"response": "ok"})

    monkeypatch.setattr(daemon.httpx, "post", fake_post)

    async def run():
        assert await daemon._dispatch_to_host("hello") == "ok"

    asyncio.run(run())

    inject_url, inject_kwargs = calls[-1]
    assert inject_url.endswith("/chat/inject")
    payload = inject_kwargs["json"]
    assert payload["timeout_sec"] == daemon.A2A_RESPONSE_TIMEOUT_SEC
    assert payload["transport"] == {
        "kind": "a2a",
        "conversation_id": "-123",
        "sender_label": "A2A",
    }


def test_dispatch_applies_backpressure(tmp_path, monkeypatch):
    daemon = _load_daemon(tmp_path, monkeypatch)

    async def run():
        daemon._A2A_SEMAPHORE = asyncio.Semaphore(1)
        await daemon._A2A_SEMAPHORE.acquire()
        try:
            try:
                await daemon._dispatch_to_host("hello")
            except RuntimeError as exc:
                assert "busy" in str(exc)
            else:
                raise AssertionError("busy dispatch was not rejected")
        finally:
            daemon._A2A_SEMAPHORE.release()

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8767",
        "http://localhost:8767",
        "http://[::1]:8767",
    ],
)
def test_host_service_loopback_urls_are_allowed(tmp_path, monkeypatch, url):
    monkeypatch.setenv("HOST_SERVICE_URL", url)
    daemon = _load_daemon(tmp_path, monkeypatch)
    assert daemon._is_loopback(daemon._host_service_hostname(url)) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8767@evil.example",
        "http://evil.example:8767",
    ],
)
def test_host_service_url_rejects_non_loopback_and_userinfo(tmp_path, monkeypatch, url):
    monkeypatch.setenv("HOST_SERVICE_URL", url)
    with pytest.raises(RuntimeError):
        _load_daemon(tmp_path, monkeypatch)


def test_disable_auth_flag_skips_password_requirement(tmp_path, monkeypatch):
    """A2A_DISABLE_AUTH=1 must allow non-loopback bind without a password."""
    monkeypatch.setenv("A2A_HOST", "0.0.0.0")
    monkeypatch.delenv("A2A_SERVER_PASSWORD", raising=False)
    monkeypatch.setenv("A2A_DISABLE_AUTH", "1")
    daemon = _load_daemon(tmp_path, monkeypatch)
    assert daemon.A2A_DISABLE_AUTH is True
    # _build_app() must not raise even with no password on a non-loopback host.
    daemon._build_app()


def test_disable_auth_flag_off_still_requires_password_on_non_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("A2A_HOST", "0.0.0.0")
    monkeypatch.delenv("A2A_SERVER_PASSWORD", raising=False)
    monkeypatch.delenv("A2A_DISABLE_AUTH", raising=False)
    with pytest.raises(RuntimeError, match="A2A_SERVER_PASSWORD"):
        _load_daemon(tmp_path, monkeypatch)._build_app()


def test_disable_auth_flag_bypasses_middleware(tmp_path, monkeypatch):
    """When the flag is on, the auth middleware lets unauthenticated requests through."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setenv("A2A_HOST", "0.0.0.0")
    monkeypatch.setenv("A2A_DISABLE_AUTH", "1")
    daemon = _load_daemon(tmp_path, monkeypatch)

    async def ok(_req):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/", ok)],
        middleware=[Middleware(daemon._A2AAuthMiddleware)],
    )
    with TestClient(app) as client:
        # No Authorization header — flag-off would 401; flag-on must pass.
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


def test_middleware_still_blocks_when_flag_off(tmp_path, monkeypatch):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setenv("A2A_HOST", "0.0.0.0")
    monkeypatch.setenv("A2A_SERVER_PASSWORD", "secret")
    monkeypatch.delenv("A2A_DISABLE_AUTH", raising=False)
    daemon = _load_daemon(tmp_path, monkeypatch)

    async def ok(_req):
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/", ok)],
        middleware=[Middleware(daemon._A2AAuthMiddleware)],
    )
    with TestClient(app) as client:
        assert client.get("/").status_code == 401
