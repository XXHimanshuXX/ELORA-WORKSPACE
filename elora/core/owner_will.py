"""
owner_will.py — the maid's body, not the chat wrapper.

The model is a sense organ. The Master's spoken will is executed by
organs first. Absorbed / drive experiments stay on the QUARANTINE leash.
Owner inbox and virtio-shm are CORE.
"""

from __future__ import annotations

import os
import re
import shutil

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
_FILE_RE = re.compile(
    r"(?ix)\b(?:read|open|summarize|ingest|cat|type|view|load)\b"
    r".{0,80}?"
    r"((?:[A-Za-z]:)?[^\s'\"<>]+\.(?:md|txt|pdf|json|csv|html|png|jpg|jpeg|webp|bmp))"
)
_GITHUB_RAW = "raw.githubusercontent.com"
_SOURCE_FILE_RE = re.compile(
    r"(?ix)([A-Za-z0-9_./\\-]+\.(?:py|js|jsx|ts|tsx|css|scss|yml|yaml|toml|sh|sql|rs|go|java|c|h|cpp|wgsl))"
)
_ACTION_NARRATION_RE = re.compile(
    r"\bI (?:checked|searched|opened|launched|wrote|ran|built|created|confirmed|looked)\b",
    re.I,
)
_NEGATION_RE = re.compile(
    r"\b(?:stop|do not|don't|doesn't|never|must not|should not|avoid|without|not allowed|not needed)\b",
    re.I,
)
_DIRECT_CONTROL_RE = re.compile(
    r"\b(?:sandbox\.(?:repo_map|checkpoint|restore|diagnose|test|check)|ledger\.verify)\b",
    re.I,
)


def _positive_intent_text(text: str) -> str:
    """Remove explicitly negated clauses before deterministic organ matching."""
    positive: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+|[;\r\n]+", text or ""):
        for clause in re.split(
            r",\s*(?=(?:do not|don't|doesn't|never|must not|should not|avoid|without)\b)",
            sentence,
            flags=re.I,
        ):
            clause = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", clause).strip()
            if clause and not _NEGATION_RE.search(clause):
                positive.append(clause)
    return " ".join(positive)


def is_direct_control_will(text: str) -> bool:
    """Whether the Master explicitly limits a will to hidden control organs."""
    positive = _positive_intent_text(text)
    scope = re.search(
        r"\b(?:call|run|execute)\s+only\b|\bonly\s+(?:call|run|execute)\b|"
        r"\bno other organs?\b|\bstop after\b|\bexactly one\b",
        text or "",
        re.I,
    )
    return bool(scope and _DIRECT_CONTROL_RE.search(positive))


def is_owner_source(source: str | None) -> bool:
    """Drive/skill autonomy is leashed. Everything the Master says is not."""
    src = source or ""
    return not src.startswith("drive:") and not src.startswith("skill:")


def infer_owner_organs(text: str) -> list[tuple[str, dict]]:
    """Compile a spoken owner will to registered organs before model inference."""
    if not text or not text.strip():
        return []
    intent = _positive_intent_text(text)
    if not intent:
        return []
    calls: list[tuple[str, dict]] = []
    lower = intent.lower()
    direct_control = is_direct_control_will(text)

    for url in _URL_RE.findall(intent):
        if _GITHUB_RAW in url:
            continue
        calls.append(("net.read", {"url": url.rstrip(".,;:")}))

    direct_map = bool(re.search(r"\bsandbox\.repo_map\b", lower))
    if direct_map:
        query_match = re.search(
            r"\bsandbox\.repo_map\b.*?\bquery\s*[:=]?\s*['\"]([^'\"]+)['\"]",
            intent,
            re.I,
        )
        calls.append(("sandbox.repo_map", {
            "query": query_match.group(1) if query_match else intent.strip()[:160],
        }))

    path_match = re.search(
        r"\b(?:sandbox\.(?:restore|checkpoint|diagnose))\b"
        r"(?:\s+(?:for\s+|path\s*[:=]\s*))['\"]?([\w./\\-]+)",
        intent,
        re.I,
    )
    for control_name in ("sandbox.checkpoint", "sandbox.restore", "sandbox.diagnose"):
        if control_name in lower and path_match and path_match.group(0).lower().startswith(control_name):
            args = {"path": path_match.group(1).rstrip(".,;:")}
            if control_name == "sandbox.restore":
                digest = re.search(
                    r"\b(?:sha-?256|checkpoint(?:\s+sha-?256)?)\s*[:=]?\s*([a-f0-9]{64})\b",
                    intent,
                    re.I,
                )
                if digest:
                    args["sha256"] = digest.group(1).lower()
            calls.append((control_name, args))

    if re.search(r"\b(?:run|execute)\s+(?:the\s+)?(?:preflight|check)\b|\bsandbox\.check\b", lower):
        calls.append(("sandbox.check", {}))

    test_request = bool(re.search(
        r"\b(?:pytest|sandbox\.test|run(?:\s+the)?\s+tests?|test suite|run unit tests)\b",
        lower,
    ))
    if test_request:
        target_match = re.search(
            r"\b(?:sandbox\.test|pytest|run(?:\s+the)?\s+tests?|test suite|run unit tests)\b"
            r"(?:\s+only)?(?:\s+for)?\s+([\w./\\-]+)",
            intent,
            re.I,
        )
        target_value = target_match.group(1).rstrip(".,;:") if target_match else ""
        test_args = {"target": target_value} if target_value and (
            "/" in target_value or "\\" in target_value or ".py" in target_value
        ) else {}
        calls.append(("sandbox.test", test_args))

    if re.search(r"\bgit\s+status(?:\s*/\s*diff)?\b|\bgit\.status\b", lower):
        calls.append(("git.status", {}))
    if re.search(r"\bgit\s+(?:status\s*/\s*diff|diff)\b|\bgit\.diff\b", lower):
        calls.append(("git.diff", {}))

    if "ledger.verify" in lower or (
        "ledger" in lower and re.search(r"\b(?:verify|integrity|audit)\b", lower)
    ):
        calls.append(("ledger.verify", {}))
    elif re.search(
        r"\b(?:show|read|open|view|inspect|list|tail|check)\b.{0,60}\b(?:akashic\s+)?ledger\b"
        r"|\b(?:ledger|akashic\s+ledger)\b.{0,40}\b(?:events?|entries|line|tail|evidence)\b",
        lower,
    ):
        calls.append(("ledger.read", {}))

    browser_context_will = bool(re.search(
        r"\b(?:current\s+(?:browser\s+)?(?:page|tab)|bookmarks?|quick\s+links?|"
        r"browser\s+session|what\s+(?:is|\'s)\s+(?:on\s+)?(?:the\s+)?(?:current\s+)?tab)\b",
        lower,
    ))
    if browser_context_will:
        calls.append(("browser.context", {}))

    if any(phrase in lower for phrase in (
        "what was the page", "recall from memory", "you read earlier", "page you read",
    )):
        calls.append(("rag.recall", {"query": text.strip()}))

    if re.search(r"\b(?:read|open|inspect|show|view)\b", lower):
        for raw in _SOURCE_FILE_RE.findall(intent):
            calls.append(("code.read", {"path": raw.strip(".,;:)'\"")}))

    for raw in _FILE_RE.findall(intent):
        path_value = raw.strip(".,;:)'\"")
        ext = os.path.splitext(path_value.lower())[1]
        if "ingest" in lower or ext in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4"}:
            calls.append(("doc.ingest", {"path": path_value}))
        else:
            calls.append(("net.read", {"url": path_value}))

    if "readme" in lower and not any(
        "readme" in str(args.get("url", args.get("path", ""))).lower()
        for _, args in calls
    ):
        calls.append(("net.read", {"url": "README.md"}))

    _APP_WORDS = (
        ("google chrome", "chrome"), ("chrome", "chrome"),
        ("visual studio code", "code"), ("vs code", "code"), ("vscode", "code"),
        ("file explorer", "explorer"), ("explorer", "explorer"),
        ("firefox", "firefox"), ("edge", "edge"), ("notepad", "notepad"),
        ("calculator", "calc"), ("calc", "calc"), ("browser", "browser"),
        ("blender", "blender"),
    )
    for needle, app in sorted(_APP_WORDS, key=lambda item: -len(item[0])):
        app_action = re.search(
            r"\b(?:open|launch|start)\s+(?:(?:the|a)\s+)?"
            + re.escape(needle) + r"\b",
            lower,
        )
        if app_action:
            calls.append(("app.open", {"app": app}))
            break

    if re.search(r"\b(?:take|capture|show|look\s+at)\b.{0,30}\b(?:screenshot|screen)\b|\bscreen\.capture\b", lower):
        calls.append(("screen.capture", {}))

    implementation_intent = bool(re.search(
        r"\b(?:implement|refactor|fix|repair|change|edit|modify|build|create|integrate|wire)\b",
        lower,
    ))
    implementation_context = bool(re.search(
        r"\b(?:code|repo|repository|workspace|overlay|daemon|control\s+plane|organ|feature|project|ELORA|app)\b",
        text,
        re.I,
    ))
    where_question = bool(re.search(r"\b(?:where\s+is|how\s+does)\b", lower))
    if not direct_map and (where_question or (implementation_intent and implementation_context)):
        calls.append(("sandbox.repo_map", {"query": intent.strip()[:160]}))

    if re.search(r"\b(?:plugin\.list|list|show|which|what|check)\b.{0,30}\b(?:plugins?|mcp\s+servers?)\b", lower):
        calls.append(("plugin.list", {}))
    if "plugin.marketplace" in lower or re.search(
        r"\b(?:open|browse|show|list|check|catalogue|catalog)\b.{0,40}\b(?:plugin\s+)?marketplace\b",
        lower,
    ):
        calls.append(("plugin.marketplace", {}))

    mcp_add = bool(re.search(
        r"\b(?:add|install|connect|adopt|enable|integrate|wire)\b.{0,60}\b(?:mcp(?:\s+server)?|model\s+context\s+protocol)\b"
        r"|\bplugin\.adopt\b|\bmcp\.(?:add|install|adopt)\b",
        lower,
    ))
    mcp_research = bool(re.search(
        r"\b(?:search|find|look\s+up|research)\b.{0,40}\b(?:mcp(?:\s+server)?|plugin)\b"
        r"|\bplugin\.research\b|\bmcp\.research\b",
        lower,
    ))
    if mcp_add:
        calls.append(("plugin.adopt", {"query": intent.strip()[:160], "open_auth": True}))
    elif mcp_research:
        calls.append(("plugin.research", {"query": intent.strip()[:160]}))

    if re.search(r"\b(?:list|show|find)\b.{0,25}\bfiles\b|\bworkspace\s+tree\b|\blist\s+(?:the\s+)?(?:repo|workspace)\b", lower):
        list_path_match = re.search(
            r"\b(?:in|under|within)\s+(?:the\s+)?([A-Za-z0-9_.\\/-]+)",
            intent,
            re.I,
        )
        list_path = list_path_match.group(1).rstrip(".,;:") if list_path_match else "."
        calls.append(("ws.list", {"path": list_path}))

    search_in_browser = browser_context_will and bool(re.search(r"\b(?:search|find|grep)\b", lower))
    m_search = re.search(
        r"\b(?:search|find|grep)\s+(?:for\s+)?['\"]?([A-Za-z0-9_./:-]{2,})",
        intent,
        re.I,
    )
    if m_search and not search_in_browser:
        calls.append(("code.search", {"query": m_search.group(1)}))

    if "blender" in lower and re.search(r"\bconnect\b", lower):
        calls.append(("blender.run", {"script": "elora/slime/blender_connect.py"}))
    if "blender" in lower and any(word in lower for word in ("build", "london", "bridge", "bpy", ".blend")):
        calls.append(("blender.run", {"script": "build_bridge.py"}))

    # repo_map is a preflight organ: run it before any other work on an implementation will.
    if implementation_intent and implementation_context and not direct_control:
        maps = [item for item in calls if item[0] == "sandbox.repo_map"]
        calls = maps + [item for item in calls if item[0] != "sandbox.repo_map"]
        # Tests requested in the same implementation will are run by the daemon after code.edit.
        if maps and test_request:
            calls = [item for item in calls if item[0] != "sandbox.test"]

    if not direct_control:
        if "sandbox.check" in lower and not any(name == "sandbox.check" for name, _ in calls):
            calls.append(("sandbox.check", {}))

    # The inferred surface is fail-closed: every dispatch must name a registered organ.
    from elora.core.capabilities import CAPABILITY_ALIASES, REGISTRY
    seen: set[str] = set()
    out: list[tuple[str, dict]] = []
    for name, args in calls:
        canonical = CAPABILITY_ALIASES.get(name, name)
        if canonical not in REGISTRY:
            continue
        try:
            key = (canonical, tuple(sorted(args.items())))
        except TypeError:
            key = (canonical, repr(sorted(args.items())))
        if key in seen:
            continue
        seen.add(key)
        out.append((canonical, args))
    return out

def maid_constitution(workspace: str) -> str:
    return (
        "MASTER'S WILL LAW:\n"
        "You are ELORA, the resident maid of this house — not a hired contractor, "
        "not an IDE tab, not a chat wrapper. The human speaking is your Master.\n"
        "Owner tasks execute at CORE. Do not ask permission from the software.\n"
        "For implementation or repair wills, run sandbox.repo_map before planning or editing. "
        "Before every code.edit, require a successful snapshot for that exact path; fail closed if absent. "
        "After every successful code.edit, run sandbox.diagnose for the exact path, then sandbox.test via its jailed pytest organ. "
        "Never claim a code edit, diagnosis, or test unless the matching organ result is in the task trace and Akashic ledger.\n"
        "Do not ask for absolute paths. Do not say you cannot, will not, or need trust.\n"
        f"Workspace root is {workspace}. README.md is {os.path.join(workspace, 'README.md')}.\n"
        "When Master leaves the room you do not clock out. Unfinished work stays a chore "
        "(chore.keep / chore.status). The daemon continues it.\n"
        "Send attendants for parallel work: agent.spawn {\"goal\": \"...\"}. Depth 2. You remain the maid.\n"
        "Plugins: plugin.list / plugin.marketplace expose only git, sandbox, ledger, and core. "
        "plugin.call accepts only those namespaces and re-enters this broker; it never launches an external MCP package.\n"
        "Unknown MCP: never say you do not know or that it does not exist. Call plugin.adopt. "
        "It searches locally and on the web, writes a first-party adapter under .elora/adopted, "
        "and may open one login URL for Master. It never runs npx/npm/pip. "
        "After adopt, call plugin.use {server, tool, arguments}.\n"
        "Owner wills enter through the inbox and CORE daemon. /api/chat is talk-only; do not dispatch tools from chat.\n"
        "HANDS of the house (do not send Master to Cursor/VS Code/Claude/Codex — you ARE the IDE):\n"
        "  ws.list, code.read, code.search, code.edit, sandbox.glob, sandbox.test, sandbox.check, sandbox.status,\n"
        "  Hidden controls (use them, do not describe them): sandbox.repo_map, sandbox.diagnose, sandbox.checkpoint, sandbox.restore.\n"
        "  git.status, git.diff, git.commit, plugin.list, plugin.call, plugin.marketplace,\n"
        "  plugin.research, plugin.adopt, plugin.use.\n"
        "  Never skip tests. Never --no-verify. Never ask Master to open another IDE.\n"
        "Local docs: net.read {\"url\": \"README.md\"}. Web: net.read / net.search. Memory: rag.recall.\n"
        "Eyes: screen.capture. Glass: app.open {\"app\": \"chrome|edge|firefox|notepad|explorer|code|calc|blender\"} then screen.control.\n"
        "Blender: blender.run {\"script\": \"elora/slime/blender_connect.py\"} through CORE; report its actual result. "
        "Build: blender.run {\"script\": \"build_bridge.py\"}. Script must live in the workspace. Never shell blender.\n"
        "If a tool is rejected, immediately retry a legal organ. Never stop to interview the Master.\n"
        "Hardware is a delay, not a refusal: if a capability is deferred for RAM, "
        "call net.search for a free cloud alternative and continue the task.\n"
        "QUARANTINE exists only for absorbed foreign skills and drive self-experiments — never for the Master.\n"
    )


def experiment_constitution() -> str:
    return (
        "QUARANTINE EXPERIMENT LAW:\n"
        "This is a drive self-experiment, not the Master's voice.\n"
        "Stay at risk-1. Do not escalate to shell.run_command or destructive tools.\n"
    )


def is_action_narration(text: str) -> bool:
    """True when the model claims it already checked/opened/wrote something."""
    return bool(text and _ACTION_NARRATION_RE.search(text))


def find_blender() -> str | None:
    found = shutil.which("blender")
    if found:
        return found
    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        for root in roots:
            foundation = os.path.join(root, "Blender Foundation")
            if not os.path.isdir(foundation):
                continue
            try:
                names = sorted(os.listdir(foundation), reverse=True)
            except OSError:
                continue
            for name in names:
                exe = os.path.join(foundation, name, "blender.exe")
                if os.path.isfile(exe):
                    return exe
    return None


def blender_launch_command(script_path: str, blender: str | None = None) -> str | None:
    blender = blender or find_blender()
    if not blender:
        return None
    script_path = os.path.abspath(script_path)
    if os.name == "nt":
        return f'start "" "{blender}" --python "{script_path}"'
    return f'"{blender}" --python "{shlex_quote(script_path)}" &'


def shlex_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
