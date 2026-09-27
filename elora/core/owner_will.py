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
    calls: list[tuple[str, dict]] = []
    lower = text.lower()

    for url in _URL_RE.findall(text):
        if _GITHUB_RAW in url:
            continue
        calls.append(("net.read", {"url": url.rstrip(".,;:")}))

    if "ledger" in lower and any(w in lower for w in ("verify", "check", "integrity", "audit")):
        calls.append(("ledger.verify", {}))

    if any(p in lower for p in (
        "what was the page",
        "recall from memory",
        "you read earlier",
        "page you read",
    )):
        calls.append(("rag.recall", {"query": text.strip()}))

    for raw in _FILE_RE.findall(text):
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
        "Plugins: plugin.list, plugin.call {\"server\": \"omniroute\", \"tool\": \"NAME\", \"arguments\": {}}. "
        "OmniRoute is a sense organ, not a replacement for your hands.\n"
        "HANDS of the house (do not send Master to Cursor/VS Code/Claude/Codex):\n"
        "  ws.list, code.read, code.search, code.edit, git.status, git.diff, git.commit,\n"
        "  shell.run_command for pytest/python/build. Never skip tests. Never --no-verify.\n"
        "Local docs: net.read {\"url\": \"README.md\"}. Web: net.read / net.search. Memory: rag.recall.\n"
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
