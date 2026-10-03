"""
sandbox.py — ELORA's personal IDE cage.

This is the house's own Cursor/VS Code/Codex loop: glob, test, preflight,
plugin marketplace catalogue. Not a shell. Not an npm install of strangers.
Workspace-jailed. Secrets unread. Nested pytest in CI is dry-run only.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tempfile
from typing import Any

from elora.core.owner_will import WORKSPACE_ROOT
from elora.slime.hands import SKIP_DIRS, _is_secret, _rel, _resolve

MAX_GLOB = 200

MARKETPLACE: dict[str, str] = {
    "omniroute": "Local OmniRoute MCP gateway (node mcp-server.mjs).",
    "github": "GitHub MCP. PAT from .elora/secrets/github_token.",
    "playwright": "Playwright MCP. No CAPTCHA solving.",
    "fetch": "Fetch MCP for allowlisted HTTP.",
    "memory": "Memory MCP.",
    "filesystem": "Filesystem MCP jailed to this workspace.",
    "blender": "First-party ELORA Blender MCP (127.0.0.1:9876).",
}


def glob_files(pattern: str, path: str = ".", root: str | None = None) -> dict[str, Any]:
    pat = (pattern or "").strip() or "*"
    try:
        base = _resolve(path or ".", root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not os.path.isdir(base):
        return {"ok": False, "error": f"not a directory: {_rel(base)}"}
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            if _is_secret(full):
                continue
            rel = _rel(full).replace("\\", "/")
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"**/{pat}"):
                hits.append(rel)
                if len(hits) >= MAX_GLOB:
                    return {"ok": True, "pattern": pat, "hits": hits, "truncated": True}
    return {"ok": True, "pattern": pat, "hits": hits, "truncated": False}


def _pytest_target(target: str, root: str) -> str | None:
    raw = (target or "tools/tests").strip() or "tools/tests"
    try:
        resolved = _resolve(raw, root)
    except ValueError:
        return None
    base = os.path.abspath(root)
    if resolved != base and not resolved.startswith(base + os.sep):
        return None
    return resolved


def run_tests(target: str = "tools/tests", root: str | None = None) -> dict[str, Any]:
    base = os.path.abspath(root or WORKSPACE_ROOT)
    dest = _pytest_target(target, base)
    if not dest:
        return {"ok": False, "error": "test path escapes workspace"}
    temp_root = os.path.join(base, ".elora", "test-tmp")
    os.makedirs(temp_root, exist_ok=True)
    basetemp = tempfile.mkdtemp(prefix="pytest-", dir=temp_root)
    argv = [sys.executable, "-m", "pytest", dest, "-q", "--tb=short",
            "-p", "no:cacheprovider", "--basetemp", basetemp]
    if os.environ.get("ELORA_SANDBOX") == "dry":
        return {"ok": True, "dry": True, "argv": argv, "cwd": base}
    try:
        proc = subprocess.run(
            argv, cwd=base, capture_output=True, text=True, timeout=180, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "argv": argv}
    out = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-12000:]
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "argv": argv,
        "output": out,
    }


def run_check(root: str | None = None) -> dict[str, Any]:
    base = os.path.abspath(root or WORKSPACE_ROOT)
    run_py = os.path.join(base, "run.py")
    if not os.path.isfile(run_py):
        return {"ok": False, "error": "run.py absent"}
    argv = [sys.executable, run_py, "--check"]
    if os.environ.get("ELORA_SANDBOX") == "dry":
        return {"ok": True, "dry": True, "argv": argv}
    try:
        proc = subprocess.run(
            argv, cwd=base, capture_output=True, text=True, timeout=90, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "argv": argv}
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "argv": argv,
        "output": ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-8000:],
    }


def marketplace() -> dict[str, Any]:
    from elora.core.mcp_client import DEFAULT_SERVERS
    installed = set(DEFAULT_SERVERS)
    items = []
    for name, blurb in MARKETPLACE.items():
        items.append({
            "name": name,
            "blurb": blurb,
            "installed": name in installed,
        })
    extras = sorted(installed - set(MARKETPLACE))
    for name in extras:
        items.append({"name": name, "blurb": "registered, undocumented in catalogue", "installed": True})
    return {"ok": True, "servers": items, "note": "unknown MCP packages cannot be installed. Jail stays."}


def status(root: str | None = None) -> dict[str, Any]:
    from elora.core.mcp_client import DEFAULT_SERVERS
    from elora.slime.hands import git_status
    base = os.path.abspath(root or WORKSPACE_ROOT)
    git = git_status()
    return {
        "ok": True,
        "workspace": base,
        "plugins": sorted(DEFAULT_SERVERS),
        "git": git,
    }


def dispatch(name: str, args: dict, root: str | None = None) -> dict[str, Any]:
    args = args or {}
    if name == "sandbox.glob":
        return glob_files(args.get("pattern", args.get("glob", args.get("query", "*"))),
                          args.get("path", "."), root=root)
    if name == "sandbox.test":
        return run_tests(args.get("target", args.get("path", "tools/tests")), root=root)
    if name == "sandbox.check":
        return run_check(root=root)
    if name == "plugin.marketplace":
        return marketplace()
    if name == "sandbox.status":
        return status(root=root)
    if name in ("sandbox.repo_map", "sandbox.checkpoint", "sandbox.restore", "sandbox.diagnose"):
        from elora.slime.control_plane import dispatch as plane_dispatch
        return plane_dispatch(name, args, root=root)
    return {"ok": False, "error": f"unknown sandbox organ: {name}"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--op", default="sandbox.status")
    parser.add_argument("--pattern", default="*")
    parser.add_argument("--target", default="tools/tests")
    args = parser.parse_args()
    print(json.dumps(dispatch(args.op, {"pattern": args.pattern, "target": args.target})))
