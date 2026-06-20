from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict


def _auth():
    password = os.environ.get("A2A_CLIENT_PASSWORD", "").strip()
    return ("ouroboros", password) if password else None


def discover(url: str) -> str:
    import httpx

    base = str(url or "").rstrip("/")
    try:
        response = httpx.get(f"{base}/.well-known/agent-card.json", auth=_auth(), timeout=10)
        response.raise_for_status()
        card = response.json()
    except Exception as exc:
        return json.dumps({"error": f"Failed to fetch agent card: {exc}"})
    return json.dumps({
        "name": card.get("name", ""),
        "description": card.get("description", ""),
        "version": card.get("version", ""),
        "url": card.get("url", base),
        "capabilities": card.get("capabilities", {}),
        "skills": card.get("skills", []),
    }, ensure_ascii=False, indent=2)


def send(url: str, message: str, task_id: str = "", context_id: str = "") -> str:
    import httpx

    base = str(url or "").rstrip("/")
    request_id = uuid.uuid4().hex
    msg: Dict[str, Any] = {
        "messageId": request_id,
        "role": "user",
        "parts": [{"kind": "text", "text": str(message or "")}],
    }
    if task_id:
        msg["taskId"] = task_id
    if context_id:
        msg["contextId"] = context_id
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/send",
        "params": {"message": msg},
    }
    try:
        response = httpx.post(f"{base}/", json=payload, auth=_auth(), timeout=120)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return json.dumps({"error": f"Request failed: {exc}"})
    return json.dumps(data, ensure_ascii=False, indent=2)


def stream(url: str, message: str, task_id: str = "", context_id: str = "") -> str:
    """Send a message via message/stream (SSE) and collect all streamed events."""
    import httpx

    base = str(url or "").rstrip("/")
    request_id = uuid.uuid4().hex
    msg: Dict[str, Any] = {
        "messageId": request_id,
        "role": "user",
        "parts": [{"kind": "text", "text": str(message or "")}],
    }
    if task_id:
        msg["taskId"] = task_id
    if context_id:
        msg["contextId"] = context_id
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "message/stream",
        "params": {"message": msg},
    }
    events: list[dict[str, Any]] = []
    try:
        with httpx.stream("POST", f"{base}/", json=payload, auth=_auth(), timeout=120) as response:
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                current_data: list[str] = []
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        current_data.append(line[len("data:"):].strip())
                    elif line == "" and current_data:
                        raw = "\n".join(current_data)
                        current_data = []
                        try:
                            events.append(json.loads(raw))
                        except json.JSONDecodeError:
                            events.append({"raw": raw})
                # Handle remaining buffered data
                if current_data:
                    raw = "\n".join(current_data)
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        events.append({"raw": raw})
            else:
                # Non-SSE response (some agents may return regular JSON)
                try:
                    events.append(response.json())
                except Exception:
                    events.append({"raw": response.text})
    except Exception as exc:
        return json.dumps({"error": f"Streaming request failed: {exc}"})
    if not events:
        return json.dumps({"error": "No events received from stream"})
    return json.dumps(events, ensure_ascii=False, indent=2)


def status(url: str, task_id: str) -> str:
    import httpx

    base = str(url or "").rstrip("/")
    request_id = uuid.uuid4().hex
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tasks/get",
        "params": {"id": str(task_id or "")},
    }
    try:
        response = httpx.post(f"{base}/", json=payload, auth=_auth(), timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return json.dumps({"error": f"Request failed: {exc}"})
    return json.dumps(data, ensure_ascii=False, indent=2)
