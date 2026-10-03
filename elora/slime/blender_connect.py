"""
blender_connect.py — runs INSIDE Blender (blender.run --python).

Binds 127.0.0.1:9876 and executes bpy on the main thread.
This is the live half of elora.core.blender_mcp.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading

try:
    import bpy
except ImportError as exc:
    raise SystemExit("blender_connect.py must run inside Blender") from exc

HOST = "127.0.0.1"
PORT = int(os.environ.get("ELORA_BLENDER_MCP_PORT", "9876"))
_PENDING: queue.Queue = queue.Queue()


def _handle(req: dict) -> dict:
    op = str(req.get("op") or "")
    if op == "ping":
        return {"ok": True, "op": "ping", "objects": len(bpy.data.objects)}
    if op == "scene":
        names = [obj.name for obj in bpy.data.objects]
        return {"ok": True, "objects": names, "count": len(names)}
    if op == "exec":
        code = str(req.get("code") or "")
        loc = {"bpy": bpy, "__name__": "__blender_mcp__"}
        exec(compile(code, "<elora-blender-mcp>", "exec"), loc, loc)  # noqa: S102
        return {"ok": True, "op": "exec"}
    return {"ok": False, "error": f"unknown op {op!r}"}


def _pump() -> float:
    try:
        req, conn = _PENDING.get_nowait()
    except queue.Empty:
        return 0.15
    try:
        result = _handle(req)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        conn.sendall((json.dumps(result) + "\n").encode("utf-8"))
    except OSError:
        pass
    try:
        conn.close()
    except OSError:
        pass
    return 0.05


def _listen() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(4)
    while True:
        conn, _addr = server.accept()
        try:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            req = json.loads(buf.decode("utf-8") or "{}")
            _PENDING.put((req, conn))
        except Exception:
            try:
                conn.close()
            except OSError:
                pass


def start() -> None:
    thread = threading.Thread(target=_listen, name="elora-blender-mcp", daemon=True)
    thread.start()
    bpy.app.timers.register(_pump, persistent=True)
    print(f"ELORA blender MCP listening on {HOST}:{PORT}")


start()
