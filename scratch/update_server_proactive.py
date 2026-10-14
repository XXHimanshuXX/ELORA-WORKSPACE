import os

root = r"d:\Coding\ELORA-Workspace"
server_path = os.path.join(root, "elora", "dashboard", "server.py")

with open(server_path, "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update configured_model in payload_router_status
old_model_line = '"configured_model": config["model"] or "(unset)",'
new_model_line = '"configured_model": config["model"] or "BitNet b1.58 / auto",'
if old_model_line in code:
    code = code.replace(old_model_line, new_model_line)
    print("payload_router_status updated")

# 2. Add /api/resident/thought in do_GET
old_get_target = 'elif path == "/api/browser/session":\n                self._send_json(payload_browser_session())'
new_get_target = '''elif path == "/api/resident/thought":
                from elora.core.proactive import get_consciousness
                c = get_consciousness()
                self._send_json({"thought": c.get_current_thought(), "state": c.get_state_info().get("state_name", "AWAKE")})
            elif path == "/api/browser/session":
                self._send_json(payload_browser_session())'''

if old_get_target in code:
    code = code.replace(old_get_target, new_get_target)
    print("do_GET thought endpoint added")
else:
    print("WARNING: old_get_target not found")

# 3. Add /api/resident/wake and /api/resident/proactive_tick in do_POST
old_post_target = 'elif path == "/api/browser/session":\n                self._send_json(payload_browser_handoff(self._read_json()))'
new_post_target = '''elif path == "/api/resident/wake":
                body = self._read_json() if self.headers.get("Content-Length") else {}
                from elora.core.proactive import get_consciousness
                res = get_consciousness().wake(
                    reason=str(body.get("reason", "console_user_presence")),
                    force_greeting=bool(body.get("force", False)),
                )
                self._send_json(res)
            elif path == "/api/resident/proactive_tick":
                from elora.core.proactive import get_consciousness
                res = get_consciousness().tick_idle(force=True)
                self._send_json(res or {"ok": False, "reason": "cooldown_or_busy"})
            elif path == "/api/browser/session":
                self._send_json(payload_browser_handoff(self._read_json()))'''

if old_post_target in code:
    code = code.replace(old_post_target, new_post_target)
    print("do_POST wake endpoints added")
else:
    print("WARNING: old_post_target not found")

# 4. Add autonomous presence thread to serve()
old_serve = """def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"refusing to bind {host}: this console can call MCP tools and must stay local")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd"""

new_serve = """def _start_autonomous_presence_thread():
    import threading
    def _presence_worker():
        from elora.core.proactive import get_consciousness
        c = get_consciousness()
        time.sleep(2)
        try:
            c.wake(reason="server_boot", force_greeting=False)
        except Exception:
            pass
        while True:
            time.sleep(40)
            try:
                c.tick_idle()
            except Exception:
                pass
    t = threading.Thread(target=_presence_worker, daemon=True, name="elora-proactive")
    t.start()


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"refusing to bind {host}: this console can call MCP tools and must stay local")
    _start_autonomous_presence_thread()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd"""

if old_serve in code:
    code = code.replace(old_serve, new_serve)
    print("serve updated with presence thread")
else:
    print("WARNING: old_serve not found")

with open(server_path, "w", encoding="utf-8") as f:
    f.write(code)
print("Saved server.py successfully")
