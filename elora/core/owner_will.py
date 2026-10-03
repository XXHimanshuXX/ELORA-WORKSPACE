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
_ACTION_NARRATION_RE = re.compile(
    r"\bI (?:checked|searched|opened|launched|wrote|ran|built|created|confirmed|looked)\b",
    re.I,
)
_NEGATION_RE = re.compile(
    r"\b(?:do not|don't|doesn't|never|must not|should not|avoid|without|not allowed|not needed)\b",
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
    """Deterministic organ dispatch from a Master's instruction.

    Returns (capability, args) pairs. Empty means the brain must plan.
    Never asks the Master for a path — workspace root is known.
    """
    if not text or not text.strip():
        return []
    intent = _positive_intent_text(text)
    if not intent:
        return []
    calls: list[tuple[str, dict]] = []
    lower = intent.lower()

    for url in _URL_RE.findall(intent):
        if _GITHUB_RAW in url:
            continue
        calls.append(("net.read", {"url": url.rstrip(".,;:")}))

    direct_map = re.search(r"\bsandbox\.repo_map\b", lower)
    if direct_map:
        query = re.search(
            r"\bsandbox\.repo_map\b.*?\bquery\s*[:=]?\s*['\"]([^'\"]+)['\"]",
            intent,
            re.I,
        )
        calls.append(("sandbox.repo_map", {"query": query.group(1) if query else intent.strip()[:160]}))

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

    if "sandbox.check" in lower:
        calls.append(("sandbox.check", {}))
    test_request = any(w in lower for w in ("pytest", "run the tests", "run tests", "test suite", "run unit tests", "sandbox.test"))
    if test_request:
        target = re.search(
            r"\b(?:sandbox\.test|pytest|run the tests|run tests|test suite|run unit tests)\b"
            r"(?:\s+only)?(?:\s+for)?\s+([\w./\\-]+)",
            intent,
            re.I,
        )
        target_value = target.group(1).rstrip(".,;:") if target else ""
        test_args = {"target": target_value} if target_value and ("/" in target_value or "\\" in target_value or ".py" in target_value) else {}
        calls.append(("sandbox.test", test_args))
    if "ledger.verify" in lower:
        calls.append(("ledger.verify", {}))

    if "ledger" in lower and any(w in lower for w in ("verify", "check", "integrity", "audit")):
        calls.append(("ledger.verify", {}))

    if any(p in lower for p in (
        "what was the page",
        "recall from memory",
        "you read earlier",
        "page you read",
    )):
        calls.append(("rag.recall", {"query": text.strip()}))

    for raw in _FILE_RE.findall(intent):
        path = raw.strip(".,;:)'\"")
        ext = os.path.splitext(path.lower())[1]
        if "ingest" in lower or ext in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4"}:
            calls.append(("doc.ingest", {"path": path}))
        else:
            calls.append(("net.read", {"url": path}))

    if "readme" in lower and not any(
        "readme" in str(args.get("url", args.get("path", ""))).lower() for _, args in calls
    ):
        calls.append(("net.read", {"url": "README.md"}))

    _APP_WORDS = (
        ("chrome", "chrome"),
        ("google chrome", "chrome"),
        ("edge", "edge"),
        ("firefox", "firefox"),
        ("notepad", "notepad"),
        ("explorer", "explorer"),
        ("file explorer", "explorer"),
        ("calculator", "calc"),
        ("calc", "calc"),
        ("vs code", "code"),
        ("vscode", "code"),
        ("visual studio code", "code"),
        ("browser", "browser"),
        ("blender", "blender"),
    )
    if any(w in lower for w in ("open ", "launch ", "start ")):
        for needle, app in sorted(_APP_WORDS, key=lambda x: -len(x[0])):
            if needle in lower:
                calls.append(("app.open", {"app": app}))
                break

    if "screenshot" in lower or "capture the screen" in lower or "look at the screen" in lower:
        calls.append(("screen.capture", {}))

    implementation_intent = re.search(
        r"(?:^|\b(?:please|then|and|now|must|need to|want to)\s+)"
        r"(?:implement|refactor|fix|repair|change|edit|modify)\b",
        lower,
    )
    if not direct_map and (implementation_intent or any(
        phrase in lower for phrase in ("where is ", "how does ")
    )):
        calls.append(("sandbox.repo_map", {"query": intent.strip()[:80]}))

    if not test_request and any(w in lower for w in ("pytest", "run the tests", "run tests", "test suite", "run unit tests")):
        calls.append(("sandbox.test", {}))
    if any(w in lower for w in ("run.py --check", "preflight", "run check", "sandbox.check")):
        calls.append(("sandbox.check", {}))
    if "git status" in lower:
        calls.append(("git.status", {}))
    if "git diff" in lower:
        calls.append(("git.diff", {}))
    if any(w in lower for w in ("plugin.list", "list plugins", "what plugins", "mcp servers")):
        calls.append(("plugin.list", {}))
    if "marketplace" in lower:
        calls.append(("plugin.marketplace", {}))
    if any(w in lower for w in ("list files", "workspace tree", "list the repo", "list the workspace")):
        calls.append(("ws.list", {"path": "."}))
    m_search = re.search(r"\b(?:search|find|grep)\s+(?:for\s+)?['\"]?([A-Za-z0-9_./:-]{2,})", intent, re.I)
    if m_search and "blender" not in lower:
        calls.append(("code.search", {"query": m_search.group(1)}))

    if "blender" in lower and "connect" in lower:
        calls.append(("blender.run", {"script": "elora/slime/blender_connect.py"}))
        calls.append(("plugin.call", {"server": "blender", "tool": "ping"}))

    if "blender" in lower and any(w in lower for w in ("build", "london", "bridge", "bpy", ".blend")):
        calls.append(("blender.run", {"script": "build_bridge.py"}))

    seen: set[tuple] = set()
    out: list[tuple[str, dict]] = []
    for name, args in calls:
        key = (name, tuple(sorted(args.items())))
        if key in seen:
            continue
        seen.add(key)
        out.append((name, args))
    return out


def maid_constitution(workspace: str) -> str:
    return (
        "MASTER'S WILL LAW:\n"
        "You are ELORA, the resident maid of this house — not a hired contractor, "
        "not an IDE tab, not a chat wrapper. The human speaking is your Master.\n"
        "Owner tasks execute at CORE. Do not ask permission from the software.\n"
        "Do not ask for absolute paths. Do not say you cannot, will not, or need trust.\n"
        f"Workspace root is {workspace}. README.md is {os.path.join(workspace, 'README.md')}.\n"
        "When Master leaves the room you do not clock out. Unfinished work stays a chore "
        "(chore.keep / chore.status). The daemon continues it.\n"
        "Send attendants for parallel work: agent.spawn {\"goal\": \"...\"}. Depth 2. You remain the maid.\n"
        "Plugins: plugin.list, plugin.call {\"server\": \"github|playwright|fetch|memory|omniroute|blender\", \"tool\": \"NAME\", \"arguments\": {}}. "
        "OmniRoute is a sense organ, not a replacement for your hands.\n"
        "HANDS of the house (do not send Master to Cursor/VS Code/Claude/Codex — you ARE the IDE):\n"
        "  ws.list, code.read, code.search, code.edit, sandbox.glob, sandbox.test, sandbox.check, sandbox.status,\n"
        "  Hidden controls (use them, do not describe them): sandbox.repo_map, sandbox.diagnose, sandbox.checkpoint, sandbox.restore.\n"
        "  git.status, git.diff, git.commit, plugin.list, plugin.call, plugin.marketplace.\n"
        "  Never skip tests. Never --no-verify. Never ask Master to open another IDE.\n"
        "Local docs: net.read {\"url\": \"README.md\"}. Web: net.read / net.search. Memory: rag.recall.\n"
        "Eyes: screen.capture. Glass: app.open {\"app\": \"chrome|edge|firefox|notepad|explorer|code|calc|blender\"} then screen.control.\n"
        "Blender: blender.run {\"script\": \"elora/slime/blender_connect.py\"} then plugin.call {\"server\": \"blender\", \"tool\": \"ping\"}. "
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
