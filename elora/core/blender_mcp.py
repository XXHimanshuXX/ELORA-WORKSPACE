"""
blender_mcp.py — ELORA's Blender MCP server (stdio JSON-RPC).

Talks to a Blender instance that is running elora/slime/blender_connect.py
on 127.0.0.1 only. Absence of the socket is reported as absence.
execute_code refuses subprocess / secrets / arbitrary binds.
"""

from __future__ import annotations

import json
import os
import socket
import sys

PROTOCOL_VERSION = "2024-11-05"
HOST = "127.0.0.1"
PORT = int(os.environ.get("ELORA_BLENDER_MCP_PORT", "9876"))
TIMEOUT_S = float(os.environ.get("ELORA_BLENDER_MCP_TIMEOUT", "4"))
MAX_CODE = 8000
_DENY = (
    "subprocess",
    "os.system",
    "os.popen",
    "os.remove",
    "shutil.rmtree",
    "ctypes",
    "socket.bind",
    ".elora/secrets",
    "github_token",
)

TOOLS = [
    {
        "name": "ping",
        "description": "Probe the live Blender socket. Failure means the connect script is not listening.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_scene_info",
        "description": "List objects in the live Blender scene.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "execute_code",
        "description": "Run a short bpy snippet in the live Blender. Jailed: no subprocess, no secrets.",
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "run_script",
        "description": "Read one workspace .py and execute it in the live Blender.",
        "inputSchema": {
            "type": "object",
            "properties": {"script": {"type": "string"}},
            "required": ["script"],
        },
    },
]


def _ok(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _jail_code(code: str) -> str | None:
    if not code or not str(code).strip():
        return "empty code"
    if len(code) > MAX_CODE:
        return f"code exceeds {MAX_CODE} characters"
    lower = code.lower()
    for needle in _DENY:
        if needle.lower() in lower:
            return f"refused: {needle}"
    return None


def _jail_script(path: str) -> tuple[str | None, str | None]:
    root = os.path.abspath(os.getcwd())
    raw = (path or "").strip()
    if not raw:
        return None, "script path empty"
    resolved = os.path.abspath(os.path.join(root, raw) if not os.path.isabs(raw) else raw)
    if resolved != root and not resolved.startswith(root + os.sep):
        return None, "script is outside the workspace jail"
    norm = resolved.replace("/", os.sep).lower()
    if f"{os.sep}.elora{os.sep}secrets{os.sep}" in norm:
        return None, "script is outside the workspace jail"
    if not os.path.isfile(resolved):
        return None, f"script not found: {resolved}"
    with open(resolved, encoding="utf-8") as handle:
        return handle.read(), None


def blender_rpc(op: str, **extra) -> dict:
    payload = {"id": 1, "op": op, **extra}
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT_S) as sock:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    if not buf.strip():
        return {"ok": False, "error": "blender closed the socket with no reply"}
    return json.loads(buf.decode("utf-8"))


def dispatch(name: str, arguments: dict) -> dict:
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name == "ping":
            res = blender_rpc("ping")
            return _ok(json.dumps(res), is_error=not res.get("ok", True))
        if name == "get_scene_info":
            res = blender_rpc("scene")
            return _ok(json.dumps(res), is_error=not res.get("ok", True))
        if name == "execute_code":
            code = str(args.get("code", ""))
            reason = _jail_code(code)
            if reason:
                return _ok(reason, is_error=True)
            res = blender_rpc("exec", code=code)
            return _ok(json.dumps(res), is_error=not res.get("ok", True))
        if name == "run_script":
            body, err = _jail_script(str(args.get("script", args.get("path", ""))))
            if err:
                return _ok(err, is_error=True)
            reason = _jail_code(body or "")
            if reason:
                return _ok(reason, is_error=True)
            res = blender_rpc("exec", code=body)
            return _ok(json.dumps(res), is_error=not res.get("ok", True))
        return _ok(f"unknown tool {name!r}", is_error=True)
    except OSError as exc:
        return _ok(
            f"blender MCP socket {HOST}:{PORT} is dark: {type(exc).__name__}: {exc}. "
            "Run blender.run on elora/slime/blender_connect.py while Blender is the house.",
            is_error=True,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return _ok(f"blender reply was not JSON: {exc}", is_error=True)


def _reply(msg_id, result=None, error=None) -> None:
    payload: dict = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result if result is not None else {}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        msg_id = message.get("id")
        if method is None or msg_id is None:
            continue
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            _reply(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "elora-blender", "version": "1.0"},
            })
        elif method == "tools/list":
            _reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = str(params.get("name", ""))
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            _reply(msg_id, dispatch(name, arguments))
        else:
            _reply(msg_id, error={"code": -32601, "message": f"unknown method {method!r}"})


if __name__ == "__main__":
    serve()
