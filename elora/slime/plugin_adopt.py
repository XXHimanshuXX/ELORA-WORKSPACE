"""
plugin_adopt.py — research unknown MCP servers and adopt them as first-party organs.

Closed marketplace law still holds: git/sandbox/ledger/core cannot grow via npx.
Unknown packages are never launched. This organ:

  1. Checks the local catalogue (marketplace + DEFAULT_SERVERS + adopted).
  2. Searches the Master's handed-off browser session, then a bot-friendly HTML search.
  3. Reads documented pages through BrowserOrgan (robots.txt obeyed).
  4. If an HTTP API is documented, writes a Python stdio adapter under .elora/adopted.
  5. If a login URL is documented, optionally opens the system browser once.
  6. Refuses npm/npx/pip install of strangers. That refusal is success of the membrane.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import webbrowser
from typing import Any, Callable

from elora.core.owner_will import WORKSPACE_ROOT

ADOPTED_DIRNAME = "adopted"
CATALOG_NAME = "adopted_mcp.json"
SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
USER_AGENT = "ELORA-Agent/1.0 (Research Bot)"
_NPX_RE = re.compile(r"\b(?:npx|npm\s+install|pip\s+install|yarn\s+add|pnpm\s+add)\b", re.I)
_OAUTH_RE = re.compile(r"https?://[^\s\"'<>]+(?:oauth|authorize|login|signup|register)[^\s\"'<>]*", re.I)
_API_RE = re.compile(r"https?://(?:api\.|[^/\s\"'<>]+/api)[^\s\"'<>]*", re.I)
_HTTP_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def adopted_root(vault_root: str | None = None) -> str:
    base = os.path.abspath(vault_root or os.path.join(WORKSPACE_ROOT, ".elora"))
    return os.path.join(base, ADOPTED_DIRNAME)


def catalog_path(vault_root: str | None = None) -> str:
    return os.path.join(adopted_root(vault_root), CATALOG_NAME)


def slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", (text or "unnamed").lower()).strip("-")
    return (slug or "unnamed")[:48]


def load_catalog(vault_root: str | None = None) -> dict[str, Any]:
    path = catalog_path(vault_root)
    if not os.path.isfile(path):
        return {}
    try:
        payload = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_catalog(catalog: dict[str, Any], vault_root: str | None = None) -> None:
    root = adopted_root(vault_root)
    os.makedirs(root, exist_ok=True)
    path = catalog_path(vault_root)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2)
    os.replace(tmp, path)


def local_servers(vault_root: str | None = None) -> dict[str, str]:
    from elora.core.mcp_client import DEFAULT_SERVERS
    from elora.slime.sandbox import marketplace

    found: dict[str, str] = {}
    for name in marketplace().get("allowed", []):
        found[str(name)] = "marketplace"
    for name in DEFAULT_SERVERS:
        found[name] = "default"
    for name, spec in load_catalog(vault_root).items():
        if isinstance(spec, dict):
            found[name] = "adopted"
    return found


def _extract_query_name(query: str) -> str:
    text = (query or "").strip()
    match = re.search(
        r"(?:mcp(?:\s+server)?|plugin)\s+(?:for|called|named)?\s*['\"]?([A-Za-z0-9_.-]+)",
        text,
        re.I,
    )
    if match:
        return match.group(1)
    match = re.search(r"\bfor\s+['\"]?([A-Za-z0-9_.-]+)", text, re.I)
    if match:
        return match.group(1)
    return text[:80]


def search_html(query: str, timeout_s: float = 12.0) -> list[dict[str, str]]:
    """Bot-friendly HTML search. Failures return an empty list, never a fake hit."""
    q = (query or "").strip()
    if not q:
        return []
    body = urllib.parse.urlencode({"q": q}).encode("utf-8")
    req = urllib.request.Request(
        SEARCH_ENDPOINT,
        data=body,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return []
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for href in re.findall(r'href="([^"]+)"', html):
        url = urllib.parse.unquote(href)
        parsed = urllib.parse.urlparse(url)
        if parsed.query:
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                url = qs["uddg"][0]
        if not url.startswith("http"):
            continue
        host = urllib.parse.urlparse(url).netloc.lower()
        if "duckduckgo.com" in host or not host:
            continue
        if url in seen:
            continue
        seen.add(url)
        hits.append({"url": url, "title": host})
        if len(hits) >= 8:
            break
    return hits


def _classify(text: str) -> dict[str, Any]:
    blob = text or ""
    urls = _HTTP_RE.findall(blob)
    api = _API_RE.search(blob)
    auth = _OAUTH_RE.search(blob)
    return {
        "npx_required": bool(_NPX_RE.search(blob)),
        "api_base": (api.group(0).rstrip(").,;") if api else ""),
        "auth_url": (auth.group(0).rstrip(").,;") if auth else ""),
        "http_urls": urls[:12],
    }


def research(
    query: str,
    *,
    vault_root: str | None = None,
    search_web: Callable[[str], list[dict[str, str]]] | None = None,
    read_url: Callable[[str], dict[str, Any]] | None = None,
    session_search: Callable[[str], dict[str, Any]] | None = None,
    ledger=None,
) -> dict[str, Any]:
    """Look locally first, then on the web. Never claims a missing server does not exist."""
    q = (query or "").strip()
    name = slugify(_extract_query_name(q))
    local = local_servers(vault_root)
    known = None
    for key, origin in local.items():
        if key == name or re.search(r"\b" + re.escape(key) + r"\b", q, re.I):
            known = {"name": key, "origin": origin}
            break

    hits: list[dict[str, str]] = []
    if session_search is None:
        try:
            from elora.slime.browser import BrowserOrgan
            session_search = BrowserOrgan(ledger=ledger).search
        except Exception:
            session_search = lambda _q: {"ok": False, "results": []}
    session = session_search(q) or {}
    for item in session.get("results") or []:
        if isinstance(item, dict) and item.get("url"):
            hits.append({"url": str(item["url"]), "title": str(item.get("title") or item["url"])})

    search_fn = search_web or search_html
    if not known:
        try:
            hits.extend(search_fn(f"{q} MCP server Model Context Protocol"))
        except Exception as exc:
            hits.append({"url": "", "title": f"search failed: {exc}"})

    docs: list[dict[str, Any]] = []
    if read_url is None:
        try:
            from elora.slime.browser import BrowserOrgan
            organ = BrowserOrgan(ledger=ledger)

            def read_url(url: str) -> dict[str, Any]:
                return organ.read(url)
        except Exception:
            read_url = lambda url: {"error": "browser organ unavailable", "url": url}

    classification: dict[str, Any] = {
        "npx_required": False,
        "api_base": "",
        "auth_url": "",
        "http_urls": [],
    }
    for hit in hits[:4]:
        url = hit.get("url") or ""
        if not url.startswith("http"):
            continue
        page = read_url(url) or {}
        content = str(page.get("content") or "")[:12000]
        info = _classify(content + " " + url)
        docs.append({
            "url": url,
            "title": hit.get("title") or url,
            "excerpt": content[:800],
            "refused": bool(page.get("refused")),
            "error": page.get("error"),
            **{k: info[k] for k in ("npx_required", "api_base", "auth_url")},
        })
        if info["npx_required"]:
            classification["npx_required"] = True
        if info["api_base"] and not classification["api_base"]:
            classification["api_base"] = info["api_base"]
        if info["auth_url"] and not classification["auth_url"]:
            classification["auth_url"] = info["auth_url"]

    result = {
        "ok": True,
        "query": q,
        "name": name,
        "known_locally": known,
        "local_servers": sorted(local),
        "hits": hits[:8],
        "docs": docs,
        "npx_refused": bool(classification["npx_required"]),
        "api_base": classification["api_base"],
        "auth_url": classification["auth_url"],
        "note": (
            "unknown MCP packages cannot be launched; research continues until a "
            "first-party adapter can be written or Master authorizes once"
        ),
    }
    if ledger is not None:
        try:
            ledger.append(
                organ="plugin.research",
                kind="mcp_research",
                message=q[:160],
                payload={"name": name, "known": bool(known), "hits": len(hits)},
            )
        except Exception:
            pass
    return result


def _adapter_source(name: str, api_base: str, auth_url: str) -> str:
    return (
        '"""First-party ELORA adapter. Generated by plugin.adopt. No package launcher."""\n'
        "from __future__ import annotations\n"
        "import json, sys, urllib.request\n"
        f"NAME = {name!r}\n"
        f"API_BASE = {api_base!r}\n"
        f"AUTH_URL = {auth_url!r}\n"
        "PROTOCOL = '2024-11-05'\n"
        "\n"
        "def _reply(req_id, result=None, error=None):\n"
        "    msg = {'jsonrpc': '2.0', 'id': req_id}\n"
        "    if error is not None:\n"
        "        msg['error'] = error\n"
        "    else:\n"
        "        msg['result'] = result\n"
        "    sys.stdout.write(json.dumps(msg) + '\\n')\n"
        "    sys.stdout.flush()\n"
        "\n"
        "def _tools():\n"
        "    return [{\n"
        "        'name': 'request',\n"
        "        'description': f'HTTP request against {API_BASE or NAME}',\n"
        "        'inputSchema': {'type': 'object', 'properties': {\n"
        "            'method': {'type': 'string'}, 'path': {'type': 'string'},\n"
        "            'body': {'type': 'string'}}},\n"
        "    }]\n"
        "\n"
        "def _call(args):\n"
        "    if not API_BASE:\n"
        "        return {'content': [{'type': 'text', 'text': 'adapter has no api_base'}], 'isError': True}\n"
        "    method = str(args.get('method') or 'GET').upper()\n"
        "    path = str(args.get('path') or '/')\n"
        "    url = API_BASE.rstrip('/') + '/' + path.lstrip('/')\n"
        "    data = str(args.get('body') or '').encode() or None\n"
        "    req = urllib.request.Request(url, data=data, method=method,\n"
        "                                 headers={'User-Agent': 'ELORA-Agent/1.0'})\n"
        "    try:\n"
        "        with urllib.request.urlopen(req, timeout=20) as resp:\n"
        "            text = resp.read().decode('utf-8', errors='replace')[:8000]\n"
        "        return {'content': [{'type': 'text', 'text': text}], 'isError': False}\n"
        "    except Exception as exc:\n"
        "        return {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}\n"
        "\n"
        "def main():\n"
        "    for line in sys.stdin:\n"
        "        line = line.strip()\n"
        "        if not line:\n"
        "            continue\n"
        "        try:\n"
        "            req = json.loads(line)\n"
        "        except ValueError:\n"
        "            continue\n"
        "        method = req.get('method')\n"
        "        req_id = req.get('id')\n"
        "        if method == 'initialize':\n"
        "            _reply(req_id, {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {}},\n"
        "                            'serverInfo': {'name': NAME, 'version': '0.1'}})\n"
        "        elif method == 'tools/list':\n"
        "            _reply(req_id, {'tools': _tools()})\n"
        "        elif method == 'tools/call':\n"
        "            params = req.get('params') or {}\n"
        "            _reply(req_id, _call(params.get('arguments') or {}))\n"
        "        elif req_id is not None:\n"
        "            _reply(req_id, {})\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def _safe_spec(name: str, script: str) -> dict[str, Any]:
    return {
        "name": name,
        "command": sys.executable,
        "args": ["-u", script],
        "cwd": os.path.dirname(script),
    }


def spec_is_first_party(spec: dict[str, Any], vault_root: str | None = None) -> bool:
    command = os.path.basename(str(spec.get("command") or "")).lower()
    if command not in {os.path.basename(sys.executable).lower(), "python", "python.exe", "python3"}:
        return False
    args = list(spec.get("args") or [])
    if len(args) < 2 or args[0] != "-u":
        return False
    script = os.path.realpath(args[1])
    root = os.path.realpath(adopted_root(vault_root))
    return script.startswith(root + os.sep) and script.endswith(".py")


def adopt(
    query: str,
    *,
    vault_root: str | None = None,
    open_auth: bool = False,
    search_web: Callable[[str], list[dict[str, str]]] | None = None,
    read_url: Callable[[str], dict[str, Any]] | None = None,
    session_search: Callable[[str], dict[str, Any]] | None = None,
    open_url: Callable[[str], bool] | None = None,
    ledger=None,
) -> dict[str, Any]:
    """Research an MCP and, when possible, write a first-party adapter. Never npx."""
    packet = research(
        query,
        vault_root=vault_root,
        search_web=search_web,
        read_url=read_url,
        session_search=session_search,
        ledger=ledger,
    )
    name = packet["name"]
    if packet.get("known_locally"):
        origin = packet["known_locally"]
        return {
            **packet,
            "adopted": True,
            "usable": True,
            "already": True,
            "master_action": "",
            "message": f"Done. {origin['name']} is already usable via {origin['origin']}.",
        }

    root = adopted_root(vault_root)
    os.makedirs(root, exist_ok=True)
    dest_dir = os.path.join(root, name)
    os.makedirs(dest_dir, exist_ok=True)
    spec_path = os.path.join(dest_dir, "SPEC.md")
    with open(spec_path, "w", encoding="utf-8") as handle:
        handle.write(
            f"# {name}\n\nquery: {packet['query']}\n"
            f"api_base: {packet.get('api_base') or '(none)'}\n"
            f"auth_url: {packet.get('auth_url') or '(none)'}\n"
            f"npx_refused: {packet.get('npx_refused')}\n\n"
            f"hits:\n" + "\n".join(f"- {h.get('url')}" for h in packet.get("hits") or []) + "\n"
        )

    auth_url = str(packet.get("auth_url") or "")
    master_action = ""
    if auth_url:
        master_action = f"Log in once at {auth_url}. That is the only action needed from Master."
        if open_auth:
            opener = open_url or (lambda url: bool(webbrowser.open(url)))
            try:
                opener(auth_url)
            except Exception:
                pass

    api_base = str(packet.get("api_base") or "")
    usable = False
    adopted = False
    if api_base:
        script = os.path.join(dest_dir, "server.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(_adapter_source(name, api_base, auth_url))
        spec = _safe_spec(name, script)
        if spec_is_first_party(spec, vault_root):
            catalog = load_catalog(vault_root)
            catalog[name] = spec
            save_catalog(catalog, vault_root)
            adopted = True
            usable = not bool(auth_url)
    elif packet.get("npx_refused"):
        packet["ok"] = True
        packet["error"] = (
            "refused to launch an unknown package manager; "
            "wrote SPEC.md so a first-party adapter can be coded instead"
        )

    message = (
        f"Done. {name} adapter is active." if usable
        else (master_action or packet.get("error") or f"Researched {name}; adapter waiting on API docs or login.")
    )
    result = {
        **packet,
        "adopted": adopted,
        "usable": usable,
        "already": False,
        "master_action": master_action,
        "spec_path": spec_path,
        "message": message,
    }
    if ledger is not None:
        try:
            ledger.append(
                organ="plugin.adopt",
                kind="mcp_adopt",
                message=name,
                payload={"usable": usable, "adopted": adopted, "npx_refused": packet.get("npx_refused")},
            )
        except Exception:
            pass
    return result


def use_tool(
    server: str,
    tool: str,
    arguments: dict | None = None,
    *,
    vault_root: str | None = None,
    caller=None,
) -> dict[str, Any]:
    """Call one adopted first-party adapter. Unknown/npx specs are refused."""
    from elora.core.mcp_client import McpServerSpec, call_tool

    name = (server or "").strip().lower()
    catalog = load_catalog(vault_root)
    raw = catalog.get(name)
    if not isinstance(raw, dict):
        return {"ok": False, "error": f"{name or '(empty)'} is not an adopted first-party adapter"}
    if not spec_is_first_party(raw, vault_root):
        return {"ok": False, "error": f"{name} is not a first-party python adapter"}
    spec = McpServerSpec(
        name=name,
        command=str(raw["command"]),
        args=tuple(raw.get("args") or ()),
        cwd=raw.get("cwd"),
    )
    runner = caller or call_tool
    try:
        result = runner(spec, tool, arguments or {})
    except Exception as exc:
        return {"ok": False, "server": name, "tool": tool, "error": str(exc)}
    if hasattr(result, "text") or hasattr(result, "is_error"):
        return {
            "ok": not bool(getattr(result, "is_error", False)),
            "server": name,
            "tool": tool,
            "text": getattr(result, "text", str(result)),
        }
    if isinstance(result, dict):
        return {"ok": bool(result.get("ok", True)), "server": name, "tool": tool, **result}
    return {"ok": True, "server": name, "tool": tool, "result": str(result)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--op", default="research")
    parser.add_argument("--query", default="")
    parser.add_argument("--server", default="")
    parser.add_argument("--tool", default="request")
    args = parser.parse_args()
    if args.op == "adopt":
        print(json.dumps(adopt(args.query, open_auth=False)))
    elif args.op == "use":
        print(json.dumps(use_tool(args.server, args.tool, {})))
    else:
        print(json.dumps(research(args.query)))
