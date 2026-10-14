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
import base64
import bisect
import copy
import hashlib
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
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OVERLAY_DIR = os.path.join(ROOT, "overlay")
STATE_DIR = os.path.join(ROOT, ".elora")
RUNTIME_PATH = os.path.join(STATE_DIR, "dashboard.json")
LEDGER_PATH = os.path.join(STATE_DIR, "akashic.db")
OMNI_KEY_PATH = os.path.join(STATE_DIR, "secrets", "omniroute_api_key")
SELECTED_MODEL_PATH = os.path.join(STATE_DIR, "selected_model.txt")
UPLOADS_DIR = os.path.join(STATE_DIR, "uploads")
_TASKS_CACHE_LOCK = threading.Lock()
_TASKS_CACHE_KEY: tuple[Any, ...] | None = None
_TASKS_CACHE_VALUE: dict[str, Any] | None = None

DEFAULT_PORT = 8765
SERVER_NAME = "elora-dashboard/1.0"

# The header that makes a cross-origin request impossible for a plain webpage.
CLIENT_HEADER = "X-ELORA-Client"
CLIENT_HEADER_VALUE = "dashboard"
RESIDENT_CLIENT = "resident-overlay"
CORE_CLIENT = "core-daemon"
BROWSER_EXTENSION_CLIENT = "browser-extension"

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


def get_selected_model() -> str:
    try:
        if os.path.exists(SELECTED_MODEL_PATH):
            with open(SELECTED_MODEL_PATH, "r", encoding="utf-8") as handle:
                val = handle.read().strip()
                if val:
                    return val
    except OSError:
        pass
    return os.environ.get("OMNIROUTE_MODEL", "")


def set_selected_model(model: str) -> str:
    cleaned = (model or "").strip()
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SELECTED_MODEL_PATH, "w", encoding="utf-8") as handle:
        handle.write(cleaned)
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            AkashicLedger(LEDGER_PATH, load_history=False).append(
                organ="router",
                kind="model_selected",
                message=f"Model switched to {cleaned or 'auto'}",
                payload={"model": cleaned},
            )
        except Exception:
            pass
    return cleaned


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
        "model": get_selected_model(),
    }


def payload_select_model(model: str) -> dict[str, Any]:
    cleaned = (model or "").strip()
    if not cleaned:
        raise ApiError(400, "empty-model", "model name cannot be empty")
    saved = set_selected_model(cleaned)
    try:
        picked = resolve_model(saved)
        resolved = picked["model"]
        chosen_by = picked["chosen_by"]
        is_al = picked["is_alias"]
    except Exception:
        resolved = saved
        chosen_by = "user-pinned"
        is_al = is_alias(saved)
    return {
        "ok": True,
        "configured_model": saved,
        "resolved_model": resolved,
        "resolved_by": chosen_by,
        "is_alias": is_al,
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
    payload = _omni_request("/v1/models", timeout=5.0)
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


# Router telemetry may be read from status/model endpoints, but executing an MCP
# tool from the browser bypasses the Resident inbox → CORE daemon → broker path.
def payload_router_tool(name: str) -> dict[str, Any]:
    raise ApiError(
        410,
        "direct-tool-calls-disabled",
        "Router tool calls are disabled in the console; submit a will through the Resident inbox.",
        "Tool execution is owned by CORE and the capability broker.",
    )

_REASONING_PATTERNS: frozenset[str] = frozenset({
    "who am i", "who are you", "what am i", "who i am",
    "what patterns", "what do you see", "what do you know about me",
    "what can you tell", "what can you infer",
    "summarize", "summary", "recent activity",
    "based on my memories", "based on the memories",
    "tell me about me", "tell me about my",
    "describe me", "my activity", "my work", "my habits",
    "my profile", "my history", "what have i been",
    "what am i building", "active projects", "what should i work on",
    "work on next", "what should i focus", "what are my projects",
    "status", "tasks", "what are you doing", "what is happening",
})


def _is_reasoning_query(message: str) -> bool:
    m = message.lower()
    return any(p in m for p in _REASONING_PATTERNS)


def payload_chat(message: str, model: str = "", history: list | None = None) -> dict[str, Any]:
    """
    A real completion enriched with Eidolon OS temporal memory, OpenDAN persona routing,
    and NAVA-style action proposals. Nothing here is simulated.
    """
    if not message.strip():
        raise ApiError(400, "empty-message", "the message was empty after stripping whitespace")

    config = omniroute_config()
    picked = resolve_model(model or config["model"])
    chosen = picked["model"]

    # 1. OpenDAN persona extraction
    raw_message = message.strip()
    persona = "maid"
    persona_system = (
        "You are ELORA, an assistant in a local application. Respond concisely and accurately. "
        "Do not claim that you inspected files, used a capability, measured the host, or verified "
        "an invariant unless the supplied context or a recorded tool result proves it. "
        "When the requested evidence is absent, say so plainly."
    )
    for p_tag in ["@thinker", "@coder", "@verifier", "@terminal", "@maid"]:
        if raw_message.lower().startswith(p_tag):
            persona = p_tag[1:]
            raw_message = raw_message[len(p_tag):].strip()
            break

    if persona == "thinker":
        persona_system += " Persona: Thinker — Multi-step cognitive reasoning, system design, and architectural deliberation."
    elif persona == "coder":
        persona_system += " Persona: Coder — High-precision systems programming, AST safety, and patch correctness."
    elif persona == "verifier":
        persona_system += " Persona: Verifier — Adversarial invariant verification, security contracts, and proof auditing."
    elif persona == "terminal":
        persona_system += " Persona: Terminal — DevOps commands, build logs, and test harness execution."

    # 2. Eidolon OS Memory & Temporal Enrichment
    sources: list[dict[str, Any]] = []
    enriched = False
    context_lines = []

    if _is_reasoning_query(raw_message):
        enriched = True
        try:
            vault_res = payload_vault_search(raw_message, limit=3)
            for item in vault_res.get("results", []):
                sources.append({
                    "title": item.get("id", "Vault Skill"),
                    "source": item.get("path", "vault/skills"),
                    "snippet": item.get("snippet", "")[:180],
                })
                context_lines.append(f"- Vault [{item.get('id')}]: {item.get('snippet','')[:140]}")
        except Exception:
            pass

        try:
            from elora.organs.akashic import AkashicLedger
            if os.path.exists(LEDGER_PATH):
                for ev in AkashicLedger.read_recent_events(LEDGER_PATH, n=5):
                    h_short = ev.get("hash", "")[:8]
                    sources.append({
                        "title": f"Ledger #{h_short}",
                        "source": ev.get("organ", "broker"),
                        "snippet": f"{ev.get('kind')}: {ev.get('message', '')}",
                    })
                    context_lines.append(f"- Ledger [{ev.get('organ')}]: {ev.get('kind')} - {ev.get('message', '')}")
        except Exception:
            pass

    # 3. Action intent detection (NAVA)
    action_proposal = None
    lower_msg = raw_message.lower()
    if "pytest" in lower_msg or "run test" in lower_msg:
        action_proposal = {"command": "/task run pytest", "label": "Run Pytest Suite", "tier": "CORE"}
    elif "git status" in lower_msg or "git diff" in lower_msg:
        action_proposal = {"command": "/task git status", "label": "Check Git Status", "tier": "CORE"}
    elif "briefing" in lower_msg or "daily briefing" in lower_msg:
        action_proposal = {"command": "/briefing", "label": "View Daily Briefing", "tier": "TRUSTED"}
    elif "adopt" in lower_msg:
        action_proposal = {"command": "/adopt", "label": "Adopt Skill Repo", "tier": "TRUSTED"}

    system_text = persona_system
    if context_lines:
        system_text += "\n\nRetrieved Context & Recent Activity:\n" + "\n".join(context_lines)

    messages = [{"role": "system", "content": system_text}]
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
        "persona": persona,
        "sources": sources,
        "reasoning_enriched": enriched,
        "action_proposal": action_proposal,
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
    """Return the closed organ catalogue; never spawn a server from the dashboard."""
    return payload_mcp_servers()


def payload_mcp_servers(refresh: bool = False) -> dict[str, Any]:
    """Expose only the closed first-party marketplace, without probing processes."""
    from elora.slime.sandbox import marketplace

    catalogue = marketplace()
    return {
        "servers": catalogue["servers"],
        "allowed": catalogue["allowed"],
        "no_npx": True,
        "probed": False,
        "cached": False,
        "probed_at": None,
        "note": catalogue["note"],
    }


def payload_mcp_tools(server: str, refresh: bool = False) -> dict[str, Any]:
    from elora.slime.sandbox import marketplace

    allowed = marketplace()["allowed"]
    if server not in allowed:
        raise ApiError(404, "unknown-mcp-server", f"{server!r} is not in the closed marketplace")
    raise ApiError(
        410,
        "direct-mcp-tools-disabled",
        f"{server} is a first-party organ namespace, not a browser-launched MCP process.",
        "Use the Resident inbox so CORE can dispatch and record the tool through the broker.",
    )


def payload_mcp_call(server: str, tool: str, arguments: dict) -> dict[str, Any]:
    raise ApiError(
        410,
        "direct-mcp-call-disabled",
        "Direct MCP calls are disabled; tools must enter through the Resident inbox.",
        "CORE routes the will through the broker and records the organ result in Akashic.",
    )

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


def payload_ledger(limit: int = 60, before_seq: int | None = None) -> dict[str, Any]:
    from elora.organs.akashic import AkashicLedger

    if not os.path.exists(LEDGER_PATH):
        return {"available": False, "events": [], "count": 0,
                "note": f"no ledger at {LEDGER_PATH}"}
    try:
        page_size = max(1, min(int(limit), 500))
        events = AkashicLedger.read_recent_events(
            LEDGER_PATH, n=page_size, before_seq=before_seq)
    except Exception as exc:                            # noqa: BLE001
        raise ApiError(500, "ledger-unreadable", f"{type(exc).__name__}: {exc}") from exc
    oldest_seq = events[0]["seq"] if events else None
    return {
        "available": True,
        "count": len(events),
        "events": events,
        "oldest_seq": oldest_seq,
        "has_older": bool(oldest_seq is not None and oldest_seq > 1),
    }


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
# Organism & Resident
# ----------------------------------------------------------------------


_STATE_INDEX = {
    "CRYPTOBIOSIS": 0, "ALIVE": 1, "AWAKE": 2,
    "ALERT": 3, "ARMED": 4, "DIGESTING": 5
}


def payload_perception(state_file: Optional[str] = None) -> dict[str, Any]:
    """Last real house still. Missing, synthetic, or jailed-out frames are absent."""
    target_file = state_file or os.path.join(STATE_DIR, "state.json")
    if not target_file or not os.path.exists(target_file):
        return {"available": False, "reason": "state.json absent"}
    resolved_state = os.path.realpath(target_file)
    if state_file is None:
        workspace = os.path.realpath(ROOT)
        try:
            if os.path.commonpath((workspace, resolved_state)) != workspace:
                return {"available": False, "reason": "state.json outside workspace"}
        except ValueError:
            return {"available": False, "reason": "state.json outside workspace"}
    try:
        with open(resolved_state, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError) as e:
        return {"available": False, "reason": f"state.json unreadable: {e}"}
    perc = state.get("last_perception")
    if not isinstance(perc, dict):
        return {"available": False, "reason": "no still yet"}
    if perc.get("synthetic"):
        return {**perc, "available": False,
                "reason": perc.get("reason") or "synthetic frame is not sight"}
    if perc.get("available") is False:
        return perc
    path = perc.get("path")
    if not path:
        return {"available": False, "reason": "no still yet"}
    state_dir = os.path.dirname(resolved_state)
    jail = os.path.realpath(os.path.join(state_dir, "screenshots"))
    candidate = path if os.path.isabs(str(path)) else os.path.join(state_dir, str(path))
    resolved = os.path.realpath(candidate)
    try:
        if os.path.commonpath((jail, resolved)) != jail:
            return {"available": False, "reason": "no still yet"}
    except ValueError:
        return {"available": False, "reason": "no still yet"}
    if not os.path.isfile(resolved):
        return {"available": False, "reason": "no still yet"}
    try:
        from PIL import Image
        with Image.open(resolved) as image:
            image.verify()
    except Exception:
        return {"available": False, "reason": "no still yet"}
    return {**perc, "path": resolved, "available": True}

def perception_still_path(state_file: Optional[str] = None) -> Optional[str]:
    perc = payload_perception(state_file)
    if not perc.get("available"):
        return None
    path = perc.get("path")
    if not path:
        return None
    jail = os.path.realpath(os.path.join(STATE_DIR, "screenshots"))
    resolved = os.path.realpath(path)
    try:
        if os.path.commonpath((jail, resolved)) != jail:
            return None
    except ValueError:
        return None
    if not os.path.isfile(resolved):
        return None
    return resolved


def payload_organism_state(state_file: Optional[str] = None) -> dict[str, Any]:
    """
    Deterministic seed from vault identity, live metabolism, ripple count.
    Absence reported as absence.
    """
    target_file = state_file or os.path.join(STATE_DIR, "state.json")
    if not target_file or not os.path.exists(target_file):
        return {"available": False, "reason": "state.json absent"}
    try:
        with open(target_file, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError) as e:
        return {"available": False, "reason": f"state.json unreadable: {e}"}

    # Seed: hashed from the ledger genesis + skill count -> SAME SEED, SAME FACE
    seed_src = f"{state.get('ledger_genesis','')}:{state.get('skills_count', state.get('skill_count', 0))}"
    seed = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF

    vm = state.get("metabolism", state.get("state_name", "ALIVE"))
    from elora.core.system_metrics import memory_snapshot
    memory = memory_snapshot()
    return {
        "available": True,
        "metabolism_index": _STATE_INDEX.get(vm, 1),
        "seed": round(seed, 6),
        "ram_headroom": memory["ram_headroom"],
        "ram_available_mb": memory["ram_available_mb"],
        "ram_total_mb": memory["ram_total_mb"],
        "ram_metric_available": memory["ram_metric_available"],
        "ripple_events": state.get("ripple_events_recent"),
        "data": {
            "current_task": state.get("current_task") or "Idle",
            "current_capability": state.get("current_capability") or "none",
            "execution_tier": state.get("execution_tier") or "CORE",
            "brain_backend": state.get("brain_backend"),
            "status": state.get("status") or "IDLE",
            "last_action": state.get("last_action") or "none",
            "state_name": state.get("state_name") or vm,
        },
    }


def payload_resident_briefing() -> dict[str, Any]:
    """Daily Briefing synthesized directly from Akashic Ledger."""
    from elora.core.briefing import generate_daily_briefing
    ledger = None
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            class RecentLedgerView:
                @staticmethod
                def recent_events(n=1000):
                    return AkashicLedger.read_recent_events(LEDGER_PATH, n=n)

            ledger = RecentLedgerView()
        except Exception:
            ledger = None
    return generate_daily_briefing(ledger=ledger)


def payload_chat_history() -> dict[str, Any]:
    """Read .elora/chat.json conversation history."""
    chat_path = os.path.join(STATE_DIR, "chat.json")
    if not os.path.exists(chat_path):
        return {"available": False, "reason": "chat.json absent", "messages": []}
    try:
        with open(chat_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {"available": True, "messages": data if isinstance(data, list) else []}
    except Exception as exc:
        return {"available": False, "reason": f"unreadable: {exc}", "messages": []}


def payload_browser_session() -> dict[str, Any]:
    """Current browser handoff, or the explicit uncontrolled state."""
    from elora.slime.browser import read_session_context
    return read_session_context()


def payload_browser_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept only bounded, whitelisted context from the browser extension."""
    from elora.slime.browser import handoff_session
    result = handoff_session(payload)
    if not result.get("ok"):
        raise ApiError(400, "browser-handoff-refused", str(result.get("error", "invalid handoff")))
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            AkashicLedger(LEDGER_PATH, load_history=False).append(
                organ="browser", kind="session_handoff",
                message="browser extension session handed off",
                payload={"captured_at": result.get("captured_at"),
                         "fields": sorted(k for k in payload if k in ("current_page", "current_pages", "bookmarks", "quick_links"))},
            )
        except Exception:
            pass
    return result


def payload_upload(body: dict[str, Any]) -> dict[str, Any]:
    """Saves uploaded media (image, video, document) into .elora/uploads."""
    filename = str(body.get("filename", body.get("name", "upload.bin"))).strip()
    filename = os.path.basename(filename)
    clean_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    if not clean_name:
        clean_name = "upload.bin"
    mime_type = str(body.get("type", "application/octet-stream")).strip()
    data_b64 = str(body.get("data_base64", body.get("data", "")))
    if not data_b64:
        raise ApiError(400, "empty-upload-data", "upload data_base64 is empty")

    if "," in data_b64 and data_b64.startswith("data:"):
        data_b64 = data_b64.split(",", 1)[1]

    try:
        raw_bytes = base64.b64decode(data_b64)
    except Exception as exc:
        raise ApiError(400, "invalid-base64", f"Could not decode base64 data: {exc}")

    if len(raw_bytes) > 50 * 1024 * 1024:
        raise ApiError(413, "upload-too-large", "Uploaded file exceeds 50MB limit")

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    ts = int(time.time() * 1000)
    stored_name = f"{ts}_{clean_name}"
    target_path = os.path.join(UPLOADS_DIR, stored_name)
    with open(target_path, "wb") as f:
        f.write(raw_bytes)

    rel_path = os.path.relpath(target_path, ROOT).replace("\\", "/")
    url_path = f"/api/uploads/{stored_name}"

    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            AkashicLedger(LEDGER_PATH, load_history=False).append(
                organ="uploads",
                kind="file_received",
                message=f"Received upload: {stored_name} ({len(raw_bytes)} bytes)",
                payload={"filename": stored_name, "original": filename, "size": len(raw_bytes), "type": mime_type},
            )
        except Exception:
            pass

    return {
        "ok": True,
        "filename": stored_name,
        "original_name": filename,
        "path": rel_path,
        "url": url_path,
        "size": len(raw_bytes),
        "type": mime_type,
    }


def payload_inbox_task(prompt: str, attachments: list | None = None, client: str = RESIDENT_CLIENT) -> dict[str, Any]:
    """Enqueues a spoken will into .elora/inbox and records its client identity and attachments."""
    clean = (prompt or "").strip()
    if not clean and not attachments:
        raise ApiError(400, "empty-task", "prompt cannot be empty")
    if not clean and attachments:
        clean = "Inspect attached media / file"
    inbox_dir = os.path.join(STATE_DIR, "inbox")
    os.makedirs(inbox_dir, exist_ok=True)
    ts = int(time.time() * 1000)
    filename = f"chat_{ts}.txt"
    target = os.path.join(inbox_dir, filename)
    if not os.path.isfile(LEDGER_PATH):
        raise ApiError(503, "ledger-unavailable", "Akashic ledger is unavailable; will was not queued")

    task_body = clean
    if attachments:
        att_lines = []
        for att in attachments:
            name = att.get("name") or att.get("filename") or "file"
            path = att.get("path") or att.get("url") or ""
            mime = att.get("type") or "file"
            att_lines.append(f"[Attached: {name} ({mime}) -> {path}]")
        task_body += "\n\n" + "\n".join(att_lines)

    with open(target, "w", encoding="utf-8") as handle:
        handle.write(task_body)

    try:
        from elora.organs.akashic import AkashicLedger
        ledger = AkashicLedger(LEDGER_PATH, load_history=False)
        ledger.append(
            organ="inbox",
            kind="task_queued",
            message=f"task queued: {clean[:60]}",
            payload={"filename": filename, "task": clean, "attachments": attachments or [], "client": client},
        )
    except Exception:
        try:
            os.remove(target)
        except OSError:
            pass
        raise ApiError(503, "ledger-write-failed", "Akashic could not record the will; it was not queued")

    chat_path = os.path.join(STATE_DIR, "chat.json")
    messages = []
    if os.path.exists(chat_path):
        try:
            with open(chat_path, "r", encoding="utf-8") as handle:
                messages = json.load(handle)
        except Exception:
            messages = []
    msg_entry = {
        "sender": "user",
        "text": clean,
        "task_id": filename,
        "ts": time.time(),
        "status": "queued",
        "client": client,
    }
    if attachments:
        msg_entry["attachments"] = attachments
    messages.append(msg_entry)
    try:
        with open(chat_path, "w", encoding="utf-8") as handle:
            json.dump(messages, handle, indent=2)
    except Exception:
        pass

    return {"ok": True, "task_id": filename}


def payload_specialists() -> dict[str, Any]:
    from elora.slime.specialists import list_specialists
    return {"specialists": list_specialists()}


def payload_task_detail(task_id: str) -> dict[str, Any]:
    tasks = payload_tasks(limit=1000).get("tasks", [])
    found = next((t for t in tasks if t.get("id") == task_id
                  or task_id in t.get("related_ids", [])), None)
    if not found:
        raise ApiError(404, "task-not-found", f"Task {task_id!r} not found")

    events = []
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            events = _linked_task_events(
                found, AkashicLedger.read_recent_events(LEDGER_PATH, n=2000))
        except Exception:
            pass

    verification = _task_receipt(events)
    return {
        "task": found,
        "events": events,
        "audit_receipt": {
            "task_id": task_id,
            **verification,
            "stages_recorded": len(found.get("stages", [])),
        }
    }


def _task_event_index(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build lookup tables once so each task does not rescan the ledger."""
    by_identity: dict[str, list[dict[str, Any]]] = {}
    by_goal: dict[str, list[dict[str, Any]]] = {}
    by_kind_message: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ordered = sorted(events, key=lambda event: event.get("seq", 0))
    for event in ordered:
        payload = event.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        identity_values = (event.get("message"), payload.get("task_id"),
                           payload.get("filename"), payload.get("task"))
        for value in identity_values:
            if isinstance(value, str) and value:
                by_identity.setdefault(value, []).append(event)
        for value in (payload.get("text"), payload.get("task")):
            if isinstance(value, str) and value:
                by_goal.setdefault(value, []).append(event)
        kind, message = event.get("kind"), event.get("message")
        if isinstance(kind, str) and isinstance(message, str) and message:
            by_kind_message.setdefault((kind, message), []).append(event)
    return {
        "events": ordered,
        "seqs": [event.get("seq", 0) for event in ordered],
        "by_identity": by_identity,
        "by_goal": by_goal,
        "by_kind_message": by_kind_message,
    }


def _linked_task_events(
    task: dict[str, Any],
    events: list[dict[str, Any]],
    event_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return events linked by exact task identity or a matched daemon run window."""
    index = event_index or _task_event_index(events)
    task_id = str(task.get("id", ""))
    goal = str(task.get("goal", "")).strip()
    direct_by_seq = {
        event.get("seq"): event
        for event in (
            list(index["by_identity"].get(task_id, []))
            + list(index["by_goal"].get(goal, []))
        )
    }
    direct = list(direct_by_seq.values())

    # Daemon task_started carries the submitted text; pair its runtime id with
    # task_finished, then include Broker records inside that exact run window.
    linked = {event.get("seq"): event for event in direct}
    runtime_ids = {
        str(event.get("message", "")) for event in direct
        if event.get("kind") == "task_started" and event.get("message")
    }
    for runtime_id in runtime_ids:
        finished = index["by_kind_message"].get(("task_finished", runtime_id), [])
        for event in finished:
            linked[event.get("seq")] = event
        started = [event for event in direct
                   if event.get("kind") == "task_started"
                   and str(event.get("message", "")) == runtime_id]
        for begin in started:
            end = next((event for event in finished
                        if event.get("seq", 0) > begin.get("seq", 0)), None)
            upper = end.get("seq", 0) if end else float("inf")
            left = bisect.bisect_left(index["seqs"], begin.get("seq", 0))
            right = bisect.bisect_right(index["seqs"], upper)
            for event in index["events"][left:right]:
                if event.get("kind") in (
                    "capability_intent", "capability_result"
                ):
                    linked[event.get("seq")] = event

    return sorted(linked.values(), key=lambda event: event.get("seq", 0))


def _task_receipt(events: list[dict[str, Any]]) -> dict[str, Any]:
    results = [event for event in events if event.get("kind") == "capability_result"]
    passing = [event for event in results
               if isinstance(event.get("payload"), dict)
               and event["payload"].get("rc") == 0
               and event["payload"].get("verified") is True]
    result = passing[-1] if passing else (results[-1] if results else None)
    return {
        "verified": bool(passing),
        "status": ("BROKER REPORTED RC=0" if passing else
                   "BROKER REPORTED FAILURE" if result else "NOT RECORDED"),
        "invariants_audited": False,
        "hash": result.get("hash") if result else None,
        "capability_results": len(results),
    }


def _task_source_fingerprint(limit: int) -> tuple[Any, ...]:
    """Cheap invalidation key for the files and ledger used by the task view."""
    fixed_paths = (
        os.path.join(STATE_DIR, "chores.json"),
        os.path.join(STATE_DIR, "household.json"),
        os.path.join(STATE_DIR, "chat.json"),
        LEDGER_PATH,
        LEDGER_PATH + "-wal",
        os.path.join(STATE_DIR, "inbox"),
    )
    parts: list[Any] = [limit]
    for path in fixed_paths:
        try:
            stat = os.stat(path)
            parts.append((path, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
        except OSError:
            parts.append((path, None))
    inbox_dir = os.path.join(STATE_DIR, "inbox")
    try:
        inbox_files = []
        for name in os.listdir(inbox_dir):
            if name.endswith(".txt"):
                path = os.path.join(inbox_dir, name)
                try:
                    stat = os.stat(path)
                    inbox_files.append((name, stat.st_mtime_ns, stat.st_size))
                except OSError:
                    continue
        parts.append(tuple(sorted(inbox_files)))
    except OSError:
        parts.append(())
    return tuple(parts)


def payload_tasks(limit: int = 50) -> dict[str, Any]:
    """Return a cached, evidence-linked task view, invalidated by source changes."""
    global _TASKS_CACHE_KEY, _TASKS_CACHE_VALUE
    key = _task_source_fingerprint(limit)
    with _TASKS_CACHE_LOCK:
        if _TASKS_CACHE_KEY == key and _TASKS_CACHE_VALUE is not None:
            return copy.deepcopy(_TASKS_CACHE_VALUE)
        result = _payload_tasks_uncached(limit)
        if _task_source_fingerprint(limit) == key:
            _TASKS_CACHE_KEY = key
            _TASKS_CACHE_VALUE = copy.deepcopy(result)
        return result


def _payload_tasks_uncached(limit: int = 50) -> dict[str, Any]:
    """
    Read task records from chores, inbox, chat, and linked Akashic events.
    Inferred routing is labeled as a suggestion; execution status requires evidence.
    """
    tasks = []
    seen_ids = set()

    # 1. Active / recent chores from household chore book
    chores_path = os.path.join(STATE_DIR, "chores.json")
    if not os.path.exists(chores_path):
        chores_path = os.path.join(STATE_DIR, "household.json")
    if os.path.exists(chores_path):
        try:
            with open(chores_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
                items = raw if isinstance(raw, list) else raw.get("chores", [])
                for c in items:
                    if isinstance(c, dict) and c.get("id"):
                        cid = c["id"]
                        seen_ids.add(cid)
                        c_status = c.get("status", "open")
                        tasks.append({
                            "id": cid,
                            "goal": c.get("goal", ""),
                            "status": c_status,
                            "source": c.get("source", "household"),
                            "attempts": c.get("attempts", 0),
                            "created": c.get("created", time.time()),
                            "notes": c.get("notes", []),
                            "stages": [],
                            "trace": [],
                        })
        except Exception:
            pass

    # 2. Queued tasks in .elora/inbox
    inbox_dir = os.path.join(STATE_DIR, "inbox")
    if os.path.isdir(inbox_dir):
        try:
            for fname in os.listdir(inbox_dir):
                if fname.endswith(".txt"):
                    fpath = os.path.join(inbox_dir, fname)
                    mtime = os.path.getmtime(fpath)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                    except Exception:
                        content = ""
                    tid = fname
                    if tid not in seen_ids:
                        seen_ids.add(tid)
                        tasks.append({
                            "id": tid,
                            "goal": content,
                            "status": "queued",
                            "source": "inbox",
                            "attempts": 0,
                            "created": mtime,
                            "notes": ["Queued in .elora/inbox waiting for reactor tick"],
                            "stages": [],
                            "trace": [],
                        })
        except Exception:
            pass

    # 3. Tasks recorded in .elora/chat.json
    chat_path = os.path.join(STATE_DIR, "chat.json")
    if os.path.exists(chat_path):
        try:
            with open(chat_path, "r", encoding="utf-8") as f:
                chat_msgs = json.load(f)
                if isinstance(chat_msgs, list):
                    for m in chat_msgs:
                        if not isinstance(m, dict) or m.get("sender") != "user":
                            continue
                        if isinstance(m, dict) and m.get("proactive") is True:
                            continue
                        tid = m.get("task_id")
                        if tid and tid not in seen_ids:
                            seen_ids.add(tid)
                            st = m.get("status", "unknown")
                            tasks.append({
                                "id": tid,
                                "goal": m.get("text", ""),
                                "status": st,
                                "source": m.get("client", "chat"),
                                "attempts": 1,
                                "created": m.get("ts", time.time()),
                                "notes": [],
                                "stages": [],
                                "trace": [],
                            })
        except Exception:
            pass

    # 4. Attach only records that can be linked to the individual task.
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            recent_events = AkashicLedger.read_recent_events(LEDGER_PATH, n=2000)
            event_index = _task_event_index(recent_events)
            for task in tasks:
                linked = _linked_task_events(task, recent_events, event_index)
                task["trace"] = [{
                    "seq": e.get("seq"),
                    "organ": e.get("organ", "unknown"),
                    "kind": e.get("kind", "unknown"),
                    "message": e.get("message", ""),
                    "payload": e.get("payload", {}),
                    "hash": str(e.get("hash", ""))[:12],
                    "ts": e.get("ts", 0),
                } for e in linked]
                task["stages"] = _stages_from_events(linked)
                finished = next((event for event in reversed(linked)
                                 if event.get("kind") == "task_finished"), None)
                if finished and isinstance(finished.get("payload"), dict):
                    recorded_status = str(finished["payload"].get("status", "")).strip().lower()
                    if recorded_status:
                        task["status"] = recorded_status
                task["terminal_log"] = [
                    f"[#{e.get('seq')}] {e.get('organ', 'unknown')}.{e.get('kind', 'unknown')}: {e.get('message', '')}"
                    for e in linked
                ]
                task["verification"] = _task_receipt(linked)
        except Exception:
            pass

    from elora.slime.specialists import route_will_to_specialist
    for t in tasks:
        spec = route_will_to_specialist(t.get("goal", ""))
        t["suggested_specialist"] = spec.name
        t["specialist_id"] = spec.specialist_id
        t["specialist_icon"] = spec.icon
        t["risk_tier"] = spec.tier.name
        t.setdefault("verification", _task_receipt(t.get("trace", [])))
        t.setdefault("terminal_log", [])

    # Chores, inbox rows, and user chat messages can describe the same will.
    # Merge only when they resolve to the identical non-empty ledger sequence;
    # matching text alone is not enough to collapse two separate requests.
    deduplicated = []
    by_evidence = {}
    for task in tasks:
        seqs = tuple(trace.get("seq") for trace in task.get("trace", [])
                     if trace.get("seq") is not None)
        if not seqs:
            deduplicated.append(task)
            continue
        normalized_goal = " ".join(str(task.get("goal", "")).lower().split())
        evidence_key = (normalized_goal, seqs)
        existing = by_evidence.get(evidence_key)
        if existing is None:
            task["related_ids"] = [task.get("id")]
            by_evidence[evidence_key] = task
            deduplicated.append(task)
            continue
        related_ids = list(existing.get("related_ids", [])) + [task.get("id")]
        if len(task.get("trace", [])) > len(existing.get("trace", [])):
            existing.update(task)
        existing["related_ids"] = list(dict.fromkeys(related_ids))

    tasks = deduplicated
    tasks.sort(key=lambda t: t.get("created", 0), reverse=True)
    return {
        "available": True,
        "count": len(tasks),
        "tasks": tasks[:limit],
    }


def _stages_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display only lifecycle milestones present in linked ledger records."""
    names = {
        "task_queued": "Will queued",
        "task_started": "Daemon started",
        "capability_intent": "Broker intent recorded",
        "capability_result": "Broker result recorded",
        "task_finished": "Daemon finished",
    }
    return [
        {"name": names[event["kind"]], "key": event["kind"], "state": "done"}
        for event in events if event.get("kind") in names
    ]


def payload_vault_search(query: str = "", limit: int = 20) -> dict[str, Any]:
    """
    Hybrid RAG Memory Search across Vault & Skills (Eidetic OS & EIDOLON style).
    Searches markdown notes, skills specs, and memory episodes.
    """
    clean = (query or "").strip().lower()
    vault_dir = os.path.join(ROOT, "vault")
    results = []
    if os.path.isdir(vault_dir):
        for root_dir, _, files in os.walk(vault_dir):
            for file in files:
                if file.endswith((".md", ".txt", ".json")):
                    fpath = os.path.join(root_dir, file)
                    relpath = os.path.relpath(fpath, ROOT).replace("\\", "/")
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            text = f.read()
                        if clean and clean in text.lower():
                            idx = text.lower().find(clean)
                            start = max(0, idx - 80)
                            end = min(len(text), idx + 160)
                            snippet = ("..." if start > 0 else "") + text[start:end].replace("\n", " ") + ("..." if end < len(text) else "")
                            results.append({
                                "path": relpath,
                                "filename": file,
                                "snippet": snippet,
                                "size": len(text),
                            })
                        elif not clean:
                            results.append({
                                "path": relpath,
                                "filename": file,
                                "snippet": text[:180].replace("\n", " "),
                                "size": len(text),
                            })
                    except Exception:
                        pass
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
    return {
        "available": True,
        "query": query,
        "count": len(results),
        "results": results,
    }


def payload_task_consent(token: str, approved: bool) -> dict[str, Any]:
    """Handles interactive dual-key consent approvals for Risk-5 capabilities."""
    clean_token = (token or "").strip()
    if not clean_token:
        raise ApiError(400, "empty-token", "consent token cannot be empty")
    consent_dir = os.path.join(STATE_DIR, "consent")
    os.makedirs(consent_dir, exist_ok=True)
    target = os.path.join(consent_dir, f"{clean_token}.json")
    record = {
        "token": clean_token,
        "approved": approved,
        "ts": time.time(),
        "signer": "Master",
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    if os.path.exists(LEDGER_PATH):
        try:
            from elora.organs.akashic import AkashicLedger
            AkashicLedger(LEDGER_PATH, load_history=False).append(
                organ="broker",
                kind="consent_granted" if approved else "consent_refused",
                message=f"Dual-key consent {'granted' if approved else 'refused'} for token {clean_token}",
                payload={"token": clean_token, "approved": approved},
            )
        except Exception:
            pass
    return {"ok": True, "token": clean_token, "approved": approved}


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
        if origin.startswith(("chrome-extension://", "moz-extension://")):
            return self.headers.get(CLIENT_HEADER) == BROWSER_EXTENSION_CLIENT
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def _guard(self, mutating: bool, path: str = "") -> None:
        """
        The whole localhost-CSRF defence, in one place.

        Order matters: reject a bad Origin before looking at the header, so a
        request that fails both is reported as the cross-origin attempt it is.
        """
        if not self._origin_allowed():
            raise ApiError(403, "origin-refused",
                           f"Origin {self.headers.get('Origin')!r} is not allowed")
        # Media asset requests from <img>, <video>, <a> tags cannot supply custom headers.
        if not mutating and (path.startswith("/api/uploads/") or path == "/api/perception/still"):
            return
        client = self.headers.get(CLIENT_HEADER, "")
        if mutating and path == "/api/inbox/task":
            allowed = {RESIDENT_CLIENT, CORE_CLIENT}
        elif mutating and path == "/api/browser/session":
            allowed = {BROWSER_EXTENSION_CLIENT}
        else:
            allowed = {CLIENT_HEADER_VALUE, RESIDENT_CLIENT, CORE_CLIENT}
        if client not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ApiError(
                403, "client-header-required",
                f"{CLIENT_HEADER} must be one of: {expected}",
                "The client identity is checked before an organ can receive the request.")

    def _read_json(self, max_size: int = 1_000_000) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad-content-length", "Content-Length is not a number")
        if length <= 0:
            return {}
        if length > max_size:
            raise ApiError(413, "body-too-large", f"{length} bytes exceeds the {max_size} bytes limit")
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
        if os.path.isdir(candidate):
            index_candidate = os.path.join(candidate, "index.html")
            if os.path.isfile(index_candidate):
                candidate = index_candidate
        if not os.path.isfile(candidate):
            raise ApiError(404, "not-found", f"no such file: {normalised}")

        with open(candidate, "rb") as handle:
            body = handle.read()
        ext = os.path.splitext(candidate)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", _STATIC_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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

            self._guard(mutating=False, path=path)

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
                raw_before = query.get("before", [None])[0]
                try:
                    before_seq = int(raw_before) if raw_before is not None else None
                except (TypeError, ValueError) as exc:
                    raise ApiError(400, "bad-ledger-cursor", "before must be an integer sequence") from exc
                self._send_json(payload_ledger(limit, before_seq=before_seq))
            elif path == "/api/plugins":
                self._send_json(payload_plugins())
            elif path == "/api/organism_state":
                self._send_json(payload_organism_state())
            elif path == "/api/perception":
                self._send_json(payload_perception())
            elif path == "/api/perception/still":
                still = perception_still_path()
                if not still:
                    self._send_json({"available": False, "reason": "no still"}, status=404)
                else:
                    with open(still, "rb") as handle:
                        body = handle.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
            elif path == "/api/resident/briefing":
                self._send_json(payload_resident_briefing())
            elif path == "/api/chat/history":
                self._send_json(payload_chat_history())
            elif path == "/api/tasks":
                limit = int(query.get("limit", ["50"])[0])
                self._send_json(payload_tasks(limit=limit))
            elif path == "/api/vault/search":
                q = query.get("q", query.get("query", [""]))[0]
                self._send_json(payload_vault_search(query=q))
            elif path == "/api/specialists":
                self._send_json(payload_specialists())
            elif path == "/api/tasks/detail":
                tid = query.get("id", [""])[0]
                self._send_json(payload_task_detail(tid))
            elif path == "/api/resident/thought":
                from elora.core.proactive import get_consciousness
                c = get_consciousness()
                self._send_json({"thought": c.get_current_thought(), "state": c.get_state_info().get("state_name", "AWAKE")})
            elif path == "/api/browser/session":
                self._send_json(payload_browser_session())
            elif path == "/api/dashboards":
                self._send_json({
                    "dashboards": [
                        {"id": "console", "name": "Resident Console", "file": "index.html", "url": "/"},
                        {"id": "chronos", "name": "Chronos-Void 4D Spacetime HUD", "file": "chronos.html", "url": "/chronos.html"},
                        {"id": "omega", "name": "Omega Singularity OS", "file": "omega.html", "url": "/omega.html"},
                        {"id": "cinema", "name": "Living Multiverse Cinema OS", "file": "cinema.html", "url": "/cinema.html"},
                        {"id": "chronos_modular", "name": "Chronos 8-Module Stack", "file": "chronos/index.html", "url": "/chronos/index.html"}
                    ]
                })
            elif path == "/api/awakened/status":
                if "_AWAKENED_RESIDENT" in globals() and _AWAKENED_RESIDENT is not None:
                    self._send_json(_AWAKENED_RESIDENT.sync_overlay_organism(last_event="api_query"))
                else:
                    self._send_json({"awakened": False, "reason": "not initialized"})
            elif path.startswith("/api/uploads/"):
                fname = os.path.basename(path[len("/api/uploads/"):])
                safe_path = os.path.realpath(os.path.join(UPLOADS_DIR, fname))
                uploads_jail = os.path.realpath(UPLOADS_DIR)
                try:
                    if os.path.commonpath((uploads_jail, safe_path)) != uploads_jail:
                        raise ApiError(403, "path-forbidden", "path outside uploads jail")
                except ValueError:
                    raise ApiError(403, "path-forbidden", "invalid path")
                if not os.path.isfile(safe_path):
                    raise ApiError(404, "file-not-found", f"Upload {fname!r} not found")

                ext = os.path.splitext(fname)[1].lower()
                mime = _STATIC_TYPES.get(ext, "application/octet-stream")
                if ext in (".mp4", ".m4v"):
                    mime = "video/mp4"
                elif ext in (".webm",):
                    mime = "video/webm"
                elif ext in (".mov",):
                    mime = "video/quicktime"
                elif ext in (".jpg", ".jpeg"):
                    mime = "image/jpeg"
                elif ext in (".webp",):
                    mime = "image/webp"
                elif ext in (".gif",):
                    mime = "image/gif"
                elif ext in (".pdf",):
                    mime = "application/pdf"

                with open(safe_path, "rb") as handle:
                    body = handle.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
            else:
                raise ApiError(404, "unknown-endpoint", f"no route for {path}")
        except ApiError as exc:
            self._send_error_json(exc)
        except ConnectionError:
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
            self._guard(mutating=True, path=path)

            if path == "/api/chat":
                body = self._read_json()
                self._send_json(payload_chat(
                    str(body.get("message", "")),
                    str(body.get("model", "")),
                    body.get("history") if isinstance(body.get("history"), list) else [],
                ))
            elif path == "/api/inbox/task":
                body = self._read_json()
                client = self.headers.get(CLIENT_HEADER, "")
                self._send_json(payload_inbox_task(
                    str(body.get("prompt", body.get("task", body.get("will", "")))),
                    attachments=body.get("attachments") if isinstance(body.get("attachments"), list) else None,
                    client=client))
            elif path == "/api/router/model":
                body = self._read_json()
                self._send_json(payload_select_model(str(body.get("model", ""))))
            elif path == "/api/upload":
                body = self._read_json(max_size=60_000_000)
                self._send_json(payload_upload(body))
            elif path == "/api/tasks/consent":
                body = self._read_json()
                self._send_json(payload_task_consent(
                    str(body.get("token", "")),
                    bool(body.get("approved", False)),
                ))
            elif path == "/api/vault/search":
                body = self._read_json()
                self._send_json(payload_vault_search(
                    query=str(body.get("query", body.get("q", ""))),
                    limit=int(body.get("limit", 20)),
                ))
            elif path == "/api/resident/wake":
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
                self._send_json(payload_browser_handoff(self._read_json()))
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


def _start_autonomous_presence_thread():
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


# [ELORA-AWAKENING-BRIDGE-WIRED]
try:
    from elora.core.awakening import AwakenedEloraResidentDaemon as _AwakenedDaemon
    _AWAKENED_RESIDENT = _AwakenedDaemon()
except Exception:
    _AWAKENED_RESIDENT = None
