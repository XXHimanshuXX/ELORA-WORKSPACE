"""
server.py — ELORA's own console.

One process serves the generated genome, the live router, the capability
registry, the real MCP servers, and this machine's inventory. The same frontend
is served to a browser and loaded by the Tauri webview, so there is exactly one
data path to reason about.

    python -m elora.dashboard.server --port 8765

DESIGN RULES, and what each one costs.

1. LOCALHOST ONLY, AND NOT TRUSTING LOCALHOST.
   Binding to 127.0.0.1 keeps the network out, but it does not keep the *user's
   browser* out. A page on any website can issue a POST to 127.0.0.1:8765, and
   since ELORA can run shell commands and call MCP tools, that is remote code
   execution wearing a localhost disguise. So: every `/api/*` request must
   carry a custom `X-ELORA-Client` header, and any request presenting an Origin
   not in our allowlist is refused. A cross-origin page cannot set a custom
   header without a CORS preflight, and we never answer a preflight with
   permission — so the header requirement is what actually closes the hole.
   We deliberately never send `Access-Control-Allow-Origin`.

2. A FAILED DEPENDENCY IS REPORTED, NOT PATCHED OVER.
   When OmniRoute is down, `/api/chat` returns 503 with the real socket error.
   It does not return a canned reply, and it does not return an empty success.
   The dashboard is allowed to look broken; it is not allowed to look healthy
   when it is not.

3. SLOW TRUTHS ARE CACHED, AND THE CACHE SAYS SO.
   Probing every MCP server spawns processes and can take tens of seconds.
   Those results are cached with an explicit timestamp and a `probed` flag, so
   the UI can distinguish "0 tools" from "not asked yet".
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OVERLAY_DIR = os.path.join(ROOT, "overlay")
STATE_DIR = os.path.join(ROOT, ".elora")
RUNTIME_PATH = os.path.join(STATE_DIR, "dashboard.json")
LEDGER_PATH = os.path.join(STATE_DIR, "akashic.db")
OMNI_KEY_PATH = os.path.join(STATE_DIR, "secrets", "omniroute_api_key")

DEFAULT_PORT = 8765
SERVER_NAME = "elora-dashboard/1.0"

# The header that makes a cross-origin request impossible for a plain webpage.
CLIENT_HEADER = "X-ELORA-Client"
CLIENT_HEADER_VALUE = "dashboard"

# Origins permitted to talk to us. `null` covers a file:// page (the Tauri
# webview loading the overlay from disk); it is safe to allow here because the
# custom-header requirement is doing the real work, and a page that can set
# custom headers cross-origin has already defeated the browser's same-origin
# policy.
_ALLOWED_ORIGINS = {
    "null",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}


class ApiError(Exception):
    """An honest failure: the status, the reason, and what to do about it."""

    def __init__(self, status: int, error: str, detail: str = "", hint: str = ""):
        self.status = status
        self.error = error
        self.detail = detail
        self.hint = hint
        super().__init__(f"{status} {error}: {detail}")


# ----------------------------------------------------------------------
# OmniRoute
# ----------------------------------------------------------------------

def omniroute_config() -> dict[str, Any]:
    key = ""
    try:
        with open(OMNI_KEY_PATH, "r", encoding="utf-8") as handle:
            key = handle.read().strip()
    except OSError:
        pass
    return {
        "url": os.environ.get("OMNIROUTE_URL", "http://localhost:20128").rstrip("/"),
        "key": key,
        "model": os.environ.get("OMNIROUTE_MODEL", ""),
    }


def _omni_request(path: str, timeout: float = 15.0,
                  method: str = "GET", body: bytes | None = None) -> Any:
    """One OmniRoute call. Raises ApiError carrying the real failure."""
    config = omniroute_config()
    headers = {"Accept": "application/json"}
    if config["key"]:
        headers["Authorization"] = f"Bearer {config['key']}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{config['url']}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        snippet = ""
        try:
            snippet = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        if exc.code in (401, 403):
            raise ApiError(
                502, "omniroute-rejected-credentials",
                f"HTTP {exc.code} from OmniRoute: {snippet}",
                "The key in .elora/secrets/omniroute_api_key was refused.") from exc
        raise ApiError(502, "omniroute-http-error",
                       f"HTTP {exc.code} from {config['url']}{path}: {snippet}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            503, "omniroute-unreachable",
            f"{config['url']} did not answer: {exc.reason}",
            "Start the OmniRoute gateway, or set OMNIROUTE_URL.") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise ApiError(504, "omniroute-timeout",
                       f"{config['url']}{path} exceeded {timeout}s") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ApiError(502, "omniroute-bad-json",
                       f"{config['url']}{path} returned non-JSON: {exc}") from exc


def list_models() -> list[str]:
    payload = _omni_request("/v1/models", timeout=20.0)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        # Some gateways answer /api/tags instead.
        tags = payload.get("models") if isinstance(payload, dict) else None
        if isinstance(tags, list):
            data = tags
        else:
            raise ApiError(502, "omniroute-unexpected-shape",
                           f"/v1/models returned {type(payload).__name__} without a 'data' list")
    names = []
    for entry in data:
        if isinstance(entry, dict):
            name = entry.get("id") or entry.get("name")
            if name:
                names.append(str(name))
        elif isinstance(entry, str):
            names.append(entry)
    return names


# Preference order for a default model, by SUBSTRING. The gateway names things
# inconsistently (`auto/claude-sonnet`, `antigravity/claude-sonnet-4-6`,
# `kc/openai/gpt-5.6-sol`), so exact ids would rot within days. These are
# matched against a lowercased name, in order.
_MODEL_SUBSTRING_PREFERENCES = (
    "claude-sonnet", "claude-opus", "gpt-5.6", "gpt-5", "gemini-3.7-pro",
    "gemini-3.1-pro", "deepseek-v4-pro", "qwen3.8",
)

# The alias the console routes through when nothing is pinned. It is listed
# first in the gateway's own catalogue and resolves deterministically, which is
# precisely what the bare string "auto" does NOT do.
_DEFAULT_ALIAS = "auto/best-coding"


def is_alias(model: str) -> bool:
    """`auto/*` entries are router aliases: real, accepted, and not pinned models."""
    return model.startswith("auto/")


def resolve_model(requested: str = "") -> dict[str, Any]:
    """
    Pick a model that provably exists, and say how it was chosen.

    `run.py` defaults to the literal string "auto", which is NOT a member of the
    advertised catalogue. The gateway happens to accept it and then resolves it
    to whatever it likes — the same request lands on a different model run to
    run, which makes every measurement in this console unreproducible.

    So the choice is made explicit, checked against the live list, and reported.
    Whether the result is a pinned model or a router alias is stated outright,
    because "I chose a provider" and "I asked the router to choose" are
    different claims and the UI must not blur them.
    """
    models = list_models()
    if not models:
        raise ApiError(502, "omniroute-no-models",
                       "OmniRoute answered but advertised zero models")

    def choice(model: str, how: str) -> dict[str, Any]:
        return {"model": model, "chosen_by": how, "is_alias": is_alias(model),
                "catalogue_size": len(models)}

    if requested:
        if requested in models:
            return choice(requested, "explicit")
        raise ApiError(
            400, "unknown-model",
            f"{requested!r} is not among the {len(models)} models OmniRoute advertises",
            "GET /api/router/models for the live list.")

    # Default: the documented alias, chosen deliberately rather than by list order.
    if _DEFAULT_ALIAS in models:
        return choice(_DEFAULT_ALIAS, "documented-alias")

    lowered = [(m.lower(), m) for m in models]
    for needle in _MODEL_SUBSTRING_PREFERENCES:
        for low, original in lowered:
            if needle in low and not is_alias(original):
                return choice(original, f"substring:{needle}")
    for original in models:
        if not is_alias(original):
            return choice(original, "first-concrete-model")
    return choice(models[0], "first-advertised")


# ----------------------------------------------------------------------
# TTL cache
# ----------------------------------------------------------------------

class Cache:
    """A tiny TTL cache. Stores the error too, so a failure is cached as failure."""

    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, Any]] = {}
        self._bearers: dict[str, Any] = {}

    def get(self, key: str, ttl: float) -> tuple[bool, Any]:
        with self._lock:
            entry = self._items.get(key)
        if entry is None:
            return False, None
        stored_at, value = entry
        if time.time() - stored_at > ttl:
            return False, None
        return True, value

    def peek(self, key: str) -> tuple[bool, Any]:
        """Read regardless of age — used to serve stale data with its timestamp."""
        with self._lock:
            entry = self._items.get(key)
        return (True, entry[1]) if entry else (False, None)

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.time(), value)

    def get_or_start(self, key: str, producer: Callable[[], Any]) -> Any:
        """
        Single-flight: if a producer for `key` is already running, wait for it
        rather than starting a second one. Probing MCP servers spawns node
        processes; a double-click in the UI must not spawn a second fleet.
        """
        with self._lock:
            existing = self._bearers.get(key)
            if existing is not None:
                bearer = existing
            else:
                bearer = self._bearers[key] = {"event": threading.Event(), "value": None}
                producer_thread = True
        if not producer_thread:
            bearer["event"].wait(timeout=180)
            return bearer["value"]

        try:
            value = producer()
            self.put(key, value)
            bearer["value"] = value
            return value
        finally:
            with self._lock:
                self._bearers.pop(key, None)
            bearer["event"].set()


CACHE = Cache()


# ----------------------------------------------------------------------
# Endpoint payloads
# ----------------------------------------------------------------------

def payload_health() -> dict[str, Any]:
    return {
        "ok": True,
        "server": SERVER_NAME,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "root": ROOT,
        "overlay_present": os.path.isdir(OVERLAY_DIR),
        "state_dir_present": os.path.isdir(STATE_DIR),
    }


def payload_aesthetic() -> dict[str, Any]:
    """The current genome, plus the CSS it compiles to. This is the theme."""
    from elora.core.aesthetic import css_variables, current_tokens, list_genomes

    tokens = current_tokens()
    return {
        "genome": tokens,
        "css": css_variables(tokens),
        "generations": list_genomes(),
        "source": "generated",
    }


def payload_genomes() -> dict[str, Any]:
    from elora.core.aesthetic import current_tokens, list_genomes
    tokens = current_tokens()
    return {"generations": list_genomes(), "current_version": tokens["version"]}


def payload_aesthetic_refresh() -> dict[str, Any]:
    """
    Replace the trend baseline with measured traffic, then re-derive from it.

    The engine's `refresh_from_web()` only *returns* a refreshed baseline. Wiring
    that straight to an endpoint would make the button decorative: the genome
    would be byte-identical afterwards while the console announced it had
    followed the world. So a refresh that actually reached a public signal is
    persisted and a new generation is derived from it — that is what makes
    "follows global trends" a fact rather than a caption.

    A refresh that reached nothing persists nothing, keeps the previous
    baseline, and returns the real exception text for each source that failed.
    """
    from elora.core.aesthetic import (css_variables, evolve, list_genomes,
                                      refresh_from_web, save_baseline)

    baseline = refresh_from_web()
    errors = list(baseline.get("refresh_errors") or [])
    if not baseline.get("live"):
        return {
            "live": False,
            "baseline": baseline,
            "errors": errors,
            "note": ("no public signal answered, so the baseline was left exactly as it "
                     "was and no generation was derived"),
        }

    save_baseline(baseline)
    tokens = evolve(reason="trend baseline refreshed from live public signals")
    return {
        "live": True,
        "baseline": baseline,
        "errors": errors,
        "genome": tokens,
        "css": css_variables(tokens),
        "generations": list_genomes(),
        "note": (f"baseline replaced — {baseline.get('provenance')}"
                 f"{f'; {len(errors)} source(s) did not answer' if errors else ''}"),
    }


def payload_router_status() -> dict[str, Any]:
    config = omniroute_config()
    started = time.monotonic()
    try:
        models = list_models()
    except ApiError as exc:
        return {
            "reachable": False,
            "url": config["url"],
            "key_present": bool(config["key"]),
            "error": exc.error,
            "detail": exc.detail,
            "hint": exc.hint,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    return {
        "reachable": True,
        "url": config["url"],
        "key_present": bool(config["key"]),
        "model_count": len(models),
        "configured_model": config["model"] or "(unset)",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error": None,
    }


def payload_router_models() -> dict[str, Any]:
    models = list_models()
    config = omniroute_config()
    picked = resolve_model(config["model"])
    return {
        "count": len(models),
        "models": models,
        "aliases": [m for m in models if is_alias(m)],
        "configured_model": config["model"] or "(unset)",
        "resolved_model": picked["model"],
        "resolved_by": picked["chosen_by"],
        "resolved_is_alias": picked["is_alias"],
        # Report truthfully whether the configured value is real. `auto` is
        # accepted by the gateway but is not a member of this list, and silently
        # letting that pass is what made routing non-deterministic.
        "configured_model_exists": config["model"] in models if config["model"] else False,
    }


# Markers that a tool's PAYLOAD reports an internal failure even though the MCP
# envelope itself succeeded. `omniroute_get_health` is the live example: it
# returns a well-formed object with `uptime: "unknown"`, empty
# `circuitBreakers`, and a `degraded` array full of 401s. A console that renders
# that as a green tick is worse than one that renders nothing, because it
# converts "I could not find out" into "everything is fine".
_DEGRADATION_MARKERS = (
    re.compile(r"OmniRoute API error \[\d{3}\]"),
    re.compile(r'"code"\s*:\s*"AUTH_\d+"'),
    re.compile(r'"degraded"\s*:\s*\[\s*\{'),
)


def detect_degradation(text: str) -> str:
    """Return the marker showing this payload reports failure, or ""."""
    for pattern in _DEGRADATION_MARKERS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return ""


def _parse_json_text(text: str) -> Any:
    """Parse a tool's text result as JSON when it is JSON. Otherwise None."""
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


# Read-only OmniRoute tools the console may invoke by name. An allowlist, not a
# passthrough: this endpoint is reachable from a web page's fetch, and handing it
# the full 110-tool surface would hand over configuration-mutating tools too.
#
# `omniroute_explain_route` is deliberately ABSENT. It reads a routed request's
# scoring factors and requires a `requestId`, not a model name — wiring it to a
# model dropdown would look plausible and return validation errors.
_ROUTER_TOOLS: dict[str, tuple[str, dict[str, Any]]] = {
    "health": ("omniroute_get_health", {}),
    "session": ("omniroute_get_session_snapshot", {}),
    "combos": ("omniroute_list_combos", {"includeMetrics": True}),
    "cost": ("omniroute_cost_report", {"period": "today"}),
}


def payload_router_tool(name: str) -> dict[str, Any]:
    """Call one allowlisted OmniRoute MCP tool and return its real answer."""
    if name not in _ROUTER_TOOLS:
        raise ApiError(404, "unknown-router-tool",
                       f"{name!r} is not an allowlisted router tool",
                       f"allowed: {', '.join(sorted(_ROUTER_TOOLS))}")
    tool, arguments = _ROUTER_TOOLS[name]

    cached_key = f"router:tool:{name}"
    fresh, cached = CACHE.get(cached_key, ttl=20.0)
    if fresh:
        return dict(cached, cached=True)

    def produce() -> dict[str, Any]:
        from elora.core.mcp_client import DEFAULT_SERVERS, McpStdioServer
        started = time.monotonic()
        try:
            with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=60) as client:
                result = client.call_tool(tool, arguments)
        except Exception as exc:                        # noqa: BLE001
            raise ApiError(502, "router-tool-failed",
                           f"{tool}: {type(exc).__name__}: {exc}") from exc
        payload = _parse_json_text(result.text)
        # Surface what the payload itself admits is broken, so the panel can list
        # the failures instead of drawing an empty chart that looks like zero.
        degraded_items = []
        if isinstance(payload, dict) and isinstance(payload.get("degraded"), list):
            degraded_items = payload["degraded"]

        marker = detect_degradation(result.text)
        return {
            "name": name,
            "tool": tool,
            # protocol_ok and is_error are kept apart on purpose: MCP delivers
            # tool failures inside a successful envelope, and collapsing them
            # is how a console learns to show a green tick for a real error.
            "protocol_ok": result.protocol_ok,
            "is_error": result.is_error,
            # `succeeded` is the honest one: it is False when the payload says
            # the data could not be fetched, not merely when MCP said so.
            "succeeded": bool(result.protocol_ok and not result.is_error and not marker),
            "degraded": bool(marker),
            "degraded_reason": marker,
            "degraded_items": degraded_items,
            "text": result.text,
            "structured": result.structured_content,
            "data": payload,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "fetched_at": time.strftime("%H:%M:%S"),
        }

    return dict(CACHE.get_or_start(cached_key, produce), cached=False)


def payload_chat(message: str, model: str = "", history: list | None = None) -> dict[str, Any]:
    """
    A real completion. Nothing here is simulated, including the failures.

    This deliberately calls the gateway directly rather than going through the
    daemon's tool-call loop: the console is for talking to the router, and
    quietly executing capabilities from a web form would be a privilege
    escalation with a chat box for a handle.
    """
    if not message.strip():
        raise ApiError(400, "empty-message", "the message was empty after stripping whitespace")

    config = omniroute_config()
    picked = resolve_model(model or config["model"])
    chosen = picked["model"]

    messages = []
    for turn in (history or [])[-12:]:
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant"):
            messages.append({"role": turn["role"], "content": str(turn.get("content", ""))[:8000]})
    messages.append({"role": "user", "content": message[:16000]})

    body = json.dumps({
        "model": chosen,
        "messages": messages,
        "stream": False,
    }).encode()

    started = time.monotonic()
    payload = _omni_request("/v1/chat/completions", timeout=180.0, method="POST", body=body)
    latency_ms = int((time.monotonic() - started) * 1000)

    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ApiError(502, "omniroute-no-choices",
                       f"completion returned no choices: {json.dumps(payload)[:400]}")
    first = choices[0] if isinstance(choices[0], dict) else {}
    content = ((first.get("message") or {}).get("content")
               if isinstance(first.get("message"), dict) else None)
    if content is None:
        raise ApiError(502, "omniroute-no-content",
                       f"choice carried no message.content: {json.dumps(first)[:400]}")

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "reply": content,
        "model_used": chosen,
        "model_chosen_by": picked["chosen_by"],
        "model_is_alias": picked["is_alias"],
        "model_requested": model or config["model"] or "(unset)",
        "latency_ms": latency_ms,
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "upstream_id": payload.get("id", ""),
    }


def payload_discovery(refresh: bool = False) -> dict[str, Any]:
    from elora.core.discovery import contains_secret, discover

    if not refresh:
        fresh, cached = CACHE.get("discovery", ttl=300.0)
        if fresh:
            cached["_cache"] = {"hit": True}
            return cached

    payload = discover(per_root_cap=400, budget_s=60.0)
    # Backstop: refuse to serve a payload that still carries a credential.
    if contains_secret(payload):
        raise ApiError(500, "redaction-failed",
                       "the discovery payload still contained a credential-shaped string "
                       "after redaction; refusing to serve it",
                       "This is a bug in elora.core.discovery, not a config problem.")
    payload["_cache"] = {"hit": False}
    CACHE.put("discovery", payload)
    return payload


def _probe_mcp_servers() -> dict[str, Any]:
    """Live-probe every server we know about. Slow: spawns real processes."""
    from elora.core.mcp_client import DEFAULT_SERVERS, describe

    results = []
    for name, spec in DEFAULT_SERVERS.items():
        started = time.monotonic()
        try:
            info = describe(spec, timeout=60)
            results.append({
                "name": name,
                "spec": {"command": spec.command, "args": list(spec.args)},
                "reachable": info["reachable"],
                "protocol_version": info["protocol_version"],
                "server_info": info["server_info"],
                "tool_count": info["tool_count"],
                "error": info["error"],
                "latency_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception as exc:                       # noqa: BLE001 - reported, not hidden
            results.append({
                "name": name,
                "spec": {"command": spec.command, "args": list(spec.args)},
                "reachable": False,
                "protocol_version": "",
                "server_info": {},
                "tool_count": 0,
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": int((time.monotonic() - started) * 1000),
            })
    return {"servers": results, "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def payload_mcp_servers(refresh: bool = False) -> dict[str, Any]:
    if refresh:
        data = CACHE.get_or_start("mcp:servers", _probe_mcp_servers)
        return dict(data, cached=False)
    fresh, cached = CACHE.get("mcp:servers", ttl=600.0)
    if fresh:
        return dict(cached, cached=True)
    # Serve a stale probe WITH its age rather than pretending we never probed.
    have_stale, stale = CACHE.peek("mcp:servers")
    if have_stale:
        return dict(stale, cached=True, stale=True)
    return {"servers": [], "probed_at": None, "cached": False, "probed": False,
            "note": "not probed yet — GET /api/mcp/servers?refresh=1 to spawn the servers"}


def payload_mcp_tools(server: str, refresh: bool = False) -> dict[str, Any]:
    from elora.core.mcp_client import DEFAULT_SERVERS, McpUnknownServer

    if server not in DEFAULT_SERVERS:
        raise ApiError(404, "unknown-mcp-server",
                       f"{server!r} is not a configured server",
                       f"known: {', '.join(sorted(DEFAULT_SERVERS))}")
    key = f"mcp:tools:{server}"
    if not refresh:
        fresh, cached = CACHE.get(key, ttl=600.0)
        if fresh:
            return dict(cached, cached=True)

    spec = DEFAULT_SERVERS[server]
    started = time.monotonic()
    try:
        from elora.core.mcp_client import McpStdioServer
        with McpStdioServer(spec, timeout_s=60) as client:
            tools = client.list_tools()
            info = client.server_info
            protocol = client.protocol_version
    except Exception as exc:                            # noqa: BLE001
        raise ApiError(502, "mcp-server-unavailable",
                       f"{server}: {type(exc).__name__}: {exc}",
                       "The server process failed to launch or died mid-handshake.") from exc

    payload = {
        "server": server,
        "protocol_version": protocol,
        "server_info": info,
        "tool_count": len(tools),
        "tools": tools,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    CACHE.put(key, payload)
    return dict(payload, cached=False)


def payload_mcp_call(server: str, tool: str, arguments: dict) -> dict[str, Any]:
    from elora.core.mcp_client import DEFAULT_SERVERS, McpStdioServer

    if server not in DEFAULT_SERVERS:
        raise ApiError(404, "unknown-mcp-server",
                       f"{server!r} is not a configured server")
    if not tool:
        raise ApiError(400, "missing-tool", "no tool name supplied")

    try:
        with McpStdioServer(DEFAULT_SERVERS[server], timeout_s=90) as client:
            result = client.call_tool(tool, arguments)
    except Exception as exc:                            # noqa: BLE001
        raise ApiError(502, "mcp-call-failed",
                       f"{server}.{tool}: {type(exc).__name__}: {exc}") from exc

    marker = detect_degradation(result.text)
    return {
        "server": server,
        "tool": tool,
        "protocol_ok": result.protocol_ok,
        "is_error": result.is_error,
        "succeeded": bool(result.protocol_ok and not result.is_error and not marker),
        "degraded": bool(marker),
        "degraded_reason": marker,
        "text": result.text,
        "content": result.content,
        "structured_content": result.structured_content,
    }


def payload_capabilities() -> dict[str, Any]:
    from elora.core.capabilities import REGISTRY, TIER_CEILING

    entries = []
    for name, cap in REGISTRY.items():
        entries.append({
            "name": name,
            "risk": int(cap.risk),
            "risk_name": cap.risk.name,
            "tier_required": cap.tier_required.name,
            "description": cap.description,
            "consent_required": cap.consent_required,
            "env_gate": cap.env_gate,
            "net_allowlist": list(cap.net_allowlist),
            "allowed_roots": list(cap.allowed_roots),
        })
    entries.sort(key=lambda e: (e["risk"], e["name"]))
    return {
        "count": len(entries),
        "capabilities": entries,
        "tier_ceilings": {t.name: int(c) for t, c in TIER_CEILING.items()},
    }


def payload_ledger(limit: int = 60) -> dict[str, Any]:
    from elora.organs.akashic import AkashicLedger

    if not os.path.exists(LEDGER_PATH):
        return {"available": False, "events": [], "count": 0,
                "note": f"no ledger at {LEDGER_PATH}"}
    try:
        ledger = AkashicLedger(LEDGER_PATH)
        events = ledger.recent_events(n=max(1, min(limit, 500)))
    except Exception as exc:                            # noqa: BLE001
        raise ApiError(500, "ledger-unreadable", f"{type(exc).__name__}: {exc}") from exc
    return {"available": True, "count": len(events), "events": events}


def payload_plugins() -> dict[str, Any]:
    """
    The honest answer about plugins.

    ELORA has no plugin loader. Saying so is more useful than an empty grid that
    implies one exists and is simply idle. These manifests belong to OTHER
    clients installed on this machine; nothing here is loaded into ELORA.
    """
    payload = payload_discovery()
    return {
        "loader_available": False,
        "note": ("ELORA has no runtime plugin system. The manifests below belong to other "
                 "clients on this machine and are shown read-only — nothing here is loaded "
                 "into ELORA."),
        "manifests": payload.get("plugins", []),
        "manifest_count": len(payload.get("plugins", [])),
    }


# ----------------------------------------------------------------------
# Routing
# ----------------------------------------------------------------------

_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".wgsl": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = SERVER_NAME
    protocol_version = "HTTP/1.1"

    def handle_one_request(self) -> None:
        """
        A client that vanishes mid-request is not a server error.

        HTTP/1.1 means keep-alive, so once a response is finished this loops back
        to read the next request line. If the client reset the connection — a page
        reload cancelling an in-flight fetch, which is routine — that read raises
        ConnectionError, and BaseHTTPRequestHandler lets it escape to socketserver,
        which prints a full traceback per vanished client. The write-side guard in
        do_GET/do_POST was not enough on its own: a failure there left
        close_connection False, so the handler went straight back to reading a
        socket that was already gone.
        """
        try:
            super().handle_one_request()
        except ConnectionError:
            self.close_connection = True

    # -- helpers -----------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:
        # Default logging writes to stderr unbuffered and is noisy; keep one
        # line per request when ELORA_DASHBOARD_LOG is set.
        if os.environ.get("ELORA_DASHBOARD_LOG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, exc: ApiError) -> None:
        self._send_json({
            "error": exc.error,
            "detail": exc.detail,
            "hint": exc.hint,
            "status": exc.status,
        }, status=exc.status)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True                     # same-origin fetches often omit it
        if origin in _ALLOWED_ORIGINS:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def _guard(self, mutating: bool) -> None:
        """
        The whole localhost-CSRF defence, in one place.

        Order matters: reject a bad Origin before looking at the header, so a
        request that fails both is reported as the cross-origin attempt it is.
        """
        if not self._origin_allowed():
            raise ApiError(403, "origin-refused",
                           f"Origin {self.headers.get('Origin')!r} is not allowed")
        if self.headers.get(CLIENT_HEADER) != CLIENT_HEADER_VALUE:
            raise ApiError(
                403, "client-header-required",
                f"missing {CLIENT_HEADER}: {CLIENT_HEADER_VALUE}",
                "This header is what prevents a random web page from driving ELORA.")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad-content-length", "Content-Length is not a number")
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ApiError(413, "body-too-large", f"{length} bytes exceeds the 1MB limit")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError(400, "bad-json", f"request body is not JSON: {exc}")
        if not isinstance(parsed, dict):
            raise ApiError(400, "bad-json", "request body must be a JSON object")
        return parsed

    # -- static ------------------------------------------------------

    def _serve_static(self, url_path: str) -> None:
        relative = url_path.lstrip("/") or "index.html"
        # Traversal guard: normalise, then confirm the result is still inside
        # OVERLAY_DIR. `..%2f..%2fetc/passwd` decodes to something posixpath
        # will collapse, and the containment check is what actually stops it.
        normalised = posixpath.normpath("/" + relative).lstrip("/")
        candidate = os.path.abspath(os.path.join(OVERLAY_DIR, normalised))
        if not candidate.startswith(os.path.abspath(OVERLAY_DIR) + os.sep):
            raise ApiError(403, "path-outside-overlay", f"{relative!r} escapes the overlay root")
        if not os.path.isfile(candidate):
            raise ApiError(404, "not-found", f"no such file: {normalised}")

        with open(candidate, "rb") as handle:
            body = handle.read()
        ext = os.path.splitext(candidate)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", _STATIC_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    # -- verbs -------------------------------------------------------

    def do_OPTIONS(self) -> None:
        # We never approve a preflight. A cross-origin page therefore cannot
        # send the custom client header, which is the point.
        self._send_error_json(ApiError(403, "preflight-refused",
                                       "this server does not grant CORS preflight"))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        try:
            if path == "/api/health":
                self._send_json(payload_health())     # liveness: no guard, no state
                return

            if not path.startswith("/api/"):
                self._serve_static(path)
                return

            self._guard(mutating=False)

            if path == "/api/aesthetic":
                self._send_json(payload_aesthetic())
            elif path == "/api/aesthetic/genomes":
                self._send_json(payload_genomes())
            elif path == "/api/router/status":
                self._send_json(payload_router_status())
            elif path == "/api/router/models":
                self._send_json(payload_router_models())
            elif path == "/api/router/tools":
                self._send_json(payload_router_tool(query.get("name", [""])[0]))
            elif path == "/api/discovery":
                refresh = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
                self._send_json(payload_discovery(refresh=refresh))
            elif path == "/api/mcp/servers":
                refresh = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
                self._send_json(payload_mcp_servers(refresh=refresh))
            elif path == "/api/mcp/tools":
                server = query.get("server", [""])[0]
                refresh = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
                self._send_json(payload_mcp_tools(server, refresh=refresh))
            elif path == "/api/capabilities":
                self._send_json(payload_capabilities())
            elif path == "/api/ledger":
                limit = int(query.get("limit", ["60"])[0])
                self._send_json(payload_ledger(limit))
            elif path == "/api/plugins":
                self._send_json(payload_plugins())
            else:
                raise ApiError(404, "unknown-endpoint", f"no route for {path}")
        except ApiError as exc:
            self._send_error_json(exc)
        except ConnectionError:
            # The client hung up mid-response — a reload cancelling an in-flight
            # fetch, most often. BrokenPipeError alone was not enough: on Windows
            # a cancelled request raises ConnectionAbortedError (WinError 10053),
            # which is a sibling under ConnectionError rather than a subclass. It
            # therefore fell through to the handler below, which tried to send a
            # 500 down the same dead socket and logged a full traceback for every
            # cancelled fetch — burying real failures in noise.
            pass
        except Exception as exc:                          # noqa: BLE001
            self._send_error_json(ApiError(
                500, "internal-error", f"{type(exc).__name__}: {exc}"))

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if not path.startswith("/api/"):
                raise ApiError(404, "unknown-endpoint", f"no route for {path}")
            self._guard(mutating=True)

            if path == "/api/chat":
                body = self._read_json()
                self._send_json(payload_chat(
                    str(body.get("message", "")),
                    str(body.get("model", "")),
                    body.get("history") if isinstance(body.get("history"), list) else [],
                ))
            elif path == "/api/mcp/call":
                body = self._read_json()
                args = body.get("arguments")
                self._send_json(payload_mcp_call(
                    str(body.get("server", "")),
                    str(body.get("tool", "")),
                    args if isinstance(args, dict) else {},
                ))
            elif path == "/api/aesthetic/evolve":
                body = self._read_json()
                from elora.core.aesthetic import css_variables, evolve
                tokens = evolve(
                    reason=str(body.get("reason", "manual evolution from the console")),
                    entropy=body.get("entropy") or None,
                    version=body.get("version") or None,
                )
                self._send_json({"genome": tokens, "css": css_variables(tokens)})
            elif path == "/api/aesthetic/adopt":
                body = self._read_json()
                from elora.core.aesthetic import adopt, css_variables
                tokens = adopt(int(body.get("version", 0)))
                self._send_json({"genome": tokens, "css": css_variables(tokens)})
            elif path == "/api/aesthetic/refresh":
                self._send_json(payload_aesthetic_refresh())
            else:
                raise ApiError(404, "unknown-endpoint", f"no route for {path}")
        except ApiError as exc:
            self._send_error_json(exc)
        except ConnectionError:
            # The client hung up mid-response — a reload cancelling an in-flight
            # fetch, most often. BrokenPipeError alone was not enough: on Windows
            # a cancelled request raises ConnectionAbortedError (WinError 10053),
            # which is a sibling under ConnectionError rather than a subclass. It
            # therefore fell through to the handler below, which tried to send a
            # 500 down the same dead socket and logged a full traceback for every
            # cancelled fetch — burying real failures in noise.
            pass
        except Exception as exc:                          # noqa: BLE001
            self._send_error_json(ApiError(
                500, "internal-error", f"{type(exc).__name__}: {exc}"))


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(
            f"refusing to bind {host}: this console can call MCP tools and must stay local")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ELORA dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--announce", action="store_true",
                        help="write .elora/dashboard.json so other processes can find us")
    args = parser.parse_args(argv)

    httpd = serve(args.host, args.port)
    url = f"http://{args.host}:{httpd.server_port}/"

    if args.announce:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(RUNTIME_PATH, "w", encoding="utf-8") as handle:
            json.dump({"url": url, "port": httpd.server_port, "pid": os.getpid(),
                       "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, handle, indent=2)

    print(f"ELORA console  ->  {url}")
    print(f"  overlay      :  {OVERLAY_DIR}")
    print(f"  state        :  {STATE_DIR}")
    print(f"  health       :  {url}api/health")
    print("  Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        httpd.server_close()
        if args.announce and os.path.exists(RUNTIME_PATH):
            try:
                os.remove(RUNTIME_PATH)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
