"""Throwaway: drive the dashboard API end to end, including its refusals."""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elora.dashboard.server import CLIENT_HEADER, CLIENT_HEADER_VALUE, serve  # noqa: E402

PORT = 8791
httpd = serve("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)
BASE = f"http://127.0.0.1:{PORT}"

failures = []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def call(path, method="GET", body=None, headers=None, origin=None):
    hdrs = dict(headers or {})
    if origin:
        hdrs["Origin"] = origin
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:200]}


OK = {CLIENT_HEADER: CLIENT_HEADER_VALUE}

def raw_get(raw_path, with_header=True, origin=None):
    """Send a LITERAL request line, bypassing urllib's dot-segment collapsing.

    urllib normalises `/../x` to `/x` before it leaves the client, so a
    urllib-based test can never actually exercise the server's traversal guard.
    """
    import socket as _socket
    lines = [f"GET {raw_path} HTTP/1.1", f"Host: 127.0.0.1:{PORT}"]
    if with_header:
        lines.append(f"{CLIENT_HEADER}: {CLIENT_HEADER_VALUE}")
    if origin:
        lines.append(f"Origin: {origin}")
    lines += ["Connection: close", "", ""]
    sock = _socket.create_connection(("127.0.0.1", PORT), timeout=15)
    sock.sendall("\r\n".join(lines).encode())
    chunks = []
    while True:
        block = sock.recv(65536)
        if not block:
            break
        chunks.append(block)
    sock.close()
    raw = b"".join(chunks).decode("utf-8", "replace")
    try:
        status = int(raw.split(" ", 2)[1])
    except (IndexError, ValueError):
        status = 0
    return status, raw


print("=== SECURITY BOUNDARY ===")
status, _ = call("/api/health")
check("health answers without the client header (liveness probe)", status == 200, f"got {status}")

status, body = call("/api/capabilities")
check("state endpoint refuses without the client header", status == 403, f"got {status}")
check("  ...and says why", body.get("error") == "client-header-required", str(body.get("error")))

status, body = call("/api/capabilities", headers=OK, origin="https://evil.example.com")
check("foreign Origin is refused even WITH a valid client header", status == 403, f"got {status}")
check("  ...classified as origin-refused", body.get("error") == "origin-refused", str(body.get("error")))

status, _ = call("/api/capabilities", method="OPTIONS", headers=OK)
check("CORS preflight is refused (no header can ever be set cross-origin)", status == 403,
      f"got {status}")

status, body = call("/api/chat", method="POST", body={"message": "hi"})
check("chat POST refuses without the client header", status == 403, f"got {status}")

# Traversal, two ways: through urllib (which collapses dots first) and via a raw
# socket (which does not). The second is the one that actually tests the guard.
print("\n=== PATH TRAVERSAL ===")
for probe in ("/../run.py", "/%2e%2e/run.py", "/..%2f..%2frun.py", "/....//run.py"):
    status, body = call(probe)
    check(f"urllib {probe!r} never serves the file", status != 200, f"got {status}")

SENTINELS = ("def main", "import os", "#!/usr/bin/env")
for probe in ("/C:/Windows/win.ini", "/../run.py", "/..%2frun.py", "/%2e%2e%2frun.py",
              "/..\\run.py"):
    status, raw = raw_get(probe)
    leaked = any(s in raw for s in SENTINELS) or "[fonts]" in raw
    check(f"raw {probe!r} refused (status {status}, no file body)",
          status in (400, 403, 404) and not leaked, f"got {status}")

print("\n=== GENOME ===")
status, body = call("/api/aesthetic", headers=OK)
check("aesthetic payload served", status == 200, f"got {status}")
genome = body.get("genome", {})
css = body.get("css", "")
check("genome has a version/direction/seed",
      all(k in genome for k in ("version", "direction", "seed")),
      f"v{genome.get('version')} {genome.get('direction')!r}")
check("CSS variables emitted", "--el-canvas:" in css and "--el-accent:" in css,
      f"{len(css.splitlines())} lines")
check("contrast audit is measured, not asserted",
      genome.get("contrast_audit", {}).get("ink_on_canvas", 0) >= 7.0,
      f"ink_on_canvas={genome.get('contrast_audit', {}).get('ink_on_canvas')}")

print("\n=== CAPABILITIES ===")
status, body = call("/api/capabilities", headers=OK)
from elora.core.capabilities import REGISTRY  # noqa: E402
check("every registered capability is exposed",
      status == 200 and body.get("count") == len(REGISTRY),
      f"{body.get('count')} vs REGISTRY {len(REGISTRY)}")
risky = [c for c in body.get("capabilities", []) if c["risk"] >= 4]
check("high-risk capabilities are present and flagged",
      len(risky) >= 2, f"{len(risky)} at risk>=4, e.g. {[c['name'] for c in risky][:3]}")

print("\n=== ROUTER (live) ===")
status, body = call("/api/router/status", headers=OK)
check("router status served", status == 200, f"got {status}")
if body.get("reachable"):
    check("OmniRoute reachable with a live model list", body.get("model_count", 0) > 100,
          f"{body.get('model_count')} models, key_present={body.get('key_present')}")
else:
    check("OmniRoute reachable", False, f"error={body.get('error')} {body.get('detail')}")

status, body = call("/api/router/models", headers=OK)
if status == 200:
    resolved = body.get("resolved_model")
    check("a REAL model was resolved (not the bare 'auto' keyword)",
          resolved and resolved in body.get("models", []),
          f"resolved={resolved} via {body.get('resolved_by')}")
    check("the report says whether it is a router alias or a pinned model",
          "resolved_is_alias" in body,
          f"is_alias={body.get('resolved_is_alias')}")
    check("the report admits whether the configured model exists",
          "configured_model_exists" in body,
          f"configured={body.get('configured_model')!r} exists={body.get('configured_model_exists')}")
    check("aliases are separated from concrete models",
          len(body.get("aliases", [])) > 0 and len(body.get("aliases", [])) < len(body.get("models", [])),
          f"{len(body.get('aliases', []))} aliases of {len(body.get('models', []))} entries")

print("\n=== MCP (live subprocess) ===")
status, body = call("/api/mcp/tools?server=omniroute", headers=OK)
if status == 200:
    check("omniroute MCP server lists tools over real JSON-RPC",
          body.get("tool_count", 0) > 0,
          f"{body.get('tool_count')} tools, protocol {body.get('protocol_version')}")
else:
    check("omniroute MCP server reachable", False, f"{status} {body}")

status, body = call("/api/mcp/servers?refresh=1", headers=OK)
if status == 200:
    servers = body.get("servers", [])
    check("server probe returned real per-server results", len(servers) >= 1,
          "; ".join(f"{s['name']}={'up' if s['reachable'] else 'down'}({s['tool_count']})"
                    for s in servers))

print("\n=== ROUTER MCP TOOLS (live) ===")
for tool_name in ("health", "session", "combos"):
    status, body = call(f"/api/router/tools?name={tool_name}", headers=OK)
    if status == 200:
        check(f"router tool {tool_name!r} answered over real MCP",
              body.get("protocol_ok") and not body.get("is_error"),
              f"{body.get('latency_ms')}ms, {len(body.get('text') or '')} chars")
    else:
        check(f"router tool {tool_name!r} answered", False, f"{status} {body}")
status, body = call("/api/router/tools?name=explain_route", headers=OK)
check("a non-allowlisted router tool is a 404", status == 404, f"got {status}")

# The guard itself, exercised against the EXACT payload this machine produced
# before the API key was forwarded: a successful envelope carrying auth errors
# and "unknown" for every metric. If this ever stops detecting, the console goes
# back to drawing a green tick over a router that cannot be reached.
from elora.dashboard.server import detect_degradation  # noqa: E402
_BEFORE = ('{\n  "uptime": "unknown",\n  "version": "unknown",\n'
           "  \"degraded\": [ { \"source\": \"resilience\", \"error\": "
           '\"OmniRoute API error [401]: {\\\"code\\\":\\\"AUTH_001\\\"}\" } ]\n}')
check("degradation guard catches the real pre-fix 401 payload",
      detect_degradation(_BEFORE) != "", f"marker={detect_degradation(_BEFORE)!r}")
check("degradation guard leaves a clean payload alone",
      detect_degradation('{"uptime": "5192.3", "version": "3.8.50"}') == "")

print("\n=== DISCOVERY ===")
status, body = call("/api/discovery", headers=OK)
check("discovery served", status == 200, f"got {status}")
if status == 200:
    check("real skill total measured", body.get("skills_total_on_disk", 0) > 100,
          f"{body.get('skills_total_on_disk')} counted, "
          f"{body.get('skills_uncounted_duplicates')} duplicates excluded")
    check("agent definitions found", len(body.get("agents", [])) > 0,
          f"{len(body.get('agents', []))} agents")
    check("plugin manifests reported", len(body.get("plugins", [])) >= 0,
          f"{len(body.get('plugins', []))} plugin manifests")
    check("mcp servers from real configs", len(body.get("mcp_servers", [])) > 0,
          f"{len(body.get('mcp_servers', []))} configured")

print("\n=== PLUGINS (honesty) ===")
status, body = call("/api/plugins", headers=OK)
check("plugin loader is reported as unavailable", body.get("loader_available") is False,
      str(body.get("note", ""))[:80])

print("\n=== LEDGER ===")
status, body = call("/api/ledger", headers=OK)
check("ledger endpoint served", status == 200, f"got {status}")
if status == 200 and body.get("available"):
    check("ledger returns real events", body.get("count", 0) > 0, f"{body.get('count')} events")

print("\n=== CHAT (real completion) ===")
status, body = call("/api/chat", method="POST", headers=OK,
                    body={"message": "Reply with exactly: ELORA_CONSOLE_OK"})
if status == 200:
    check("real completion returned", bool(body.get("reply")),
          f"model={body.get('model_used')} ({body.get('model_chosen_by')}) "
          f"{body.get('latency_ms')}ms tokens={body.get('usage', {}).get('total_tokens')}")
    print(f"      reply: {body.get('reply', '')[:160]!r}")
else:
    check("real completion returned", False, f"{status} {body}")

print("\n=== FAILURE HONESTY ===")
status, body = call("/api/chat", method="POST", headers=OK, body={"message": "   "})
check("empty message is a 400, not a fake reply", status == 400, f"got {status}")
status, body = call("/api/mcp/tools?server=nope", headers=OK)
check("unknown MCP server is a 404 naming the known ones", status == 404,
      str(body.get("detail", ""))[:70])
status, body = call("/api/chat", method="POST", headers=OK,
                    body={"message": "hi", "model": "definitely-not-a-real-model-xyz"})
check("unknown model is refused rather than silently substituted", status == 400,
      str(body.get("error")))

httpd.shutdown()
print("\n" + "=" * 52)
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
