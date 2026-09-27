"""
hands.py — the coding body.

This is the organ Cursor / VS Code / Codex / Claude actually use under
the chrome: list, read, search, surgical edit, git. Not a fake IDE.
Workspace-jailed. Secrets are not writable. Git never uses --no-verify.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from elora.core.owner_will import WORKSPACE_ROOT

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", "target", ".next",
}
SECRET_FRAGMENTS = (
    os.path.join(".elora", "secrets"),
    ".env",
    "omniroute_api_key",
)
MAX_READ_BYTES = 400_000
MAX_SEARCH_HITS = 40
MAX_LIST = 200


def _resolve(path: str, root: str | None = None) -> str:
    base = os.path.abspath(root or WORKSPACE_ROOT)
    raw = (path or "").strip()
    if not raw:
        raise ValueError("empty path")
    if not os.path.isabs(raw):
        raw = os.path.join(base, raw)
    resolved = os.path.abspath(os.path.expanduser(raw))
    if resolved != base and not resolved.startswith(base + os.sep):
        raise ValueError(f"path escapes workspace: {path}")
    return resolved


def _is_secret(path: str) -> bool:
    norm = path.replace("/", os.sep).replace("\\", os.sep).lower()
    return any(frag.lower() in norm for frag in SECRET_FRAGMENTS)


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, WORKSPACE_ROOT)
    except ValueError:
        return path


def ws_list(path: str = ".", glob: str = "", root: str | None = None) -> dict[str, Any]:
    try:
        root = _resolve(path or ".", root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not os.path.isdir(root):
        return {"ok": False, "error": f"not a directory: {_rel(root)}"}
    entries = []
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        return {"ok": False, "error": str(e)}
    needle = (glob or "").lower()
    for name in names:
        if name in SKIP_DIRS or name.startswith(".git"):
            continue
        if needle and needle not in name.lower():
            continue
        full = os.path.join(root, name)
        kind = "dir" if os.path.isdir(full) else "file"
        size = os.path.getsize(full) if kind == "file" else None
        entries.append({"name": name, "path": _rel(full), "kind": kind, "bytes": size})
        if len(entries) >= MAX_LIST:
            break
    return {"ok": True, "path": _rel(root), "entries": entries, "count": len(entries)}


def code_read(path: str, start: int = 1, limit: int = 400, root: str | None = None) -> dict[str, Any]:
    try:
        resolved = _resolve(path, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not os.path.isfile(resolved):
        return {"ok": False, "error": f"not a file: {_rel(resolved)}"}
    if os.path.getsize(resolved) > MAX_READ_BYTES:
        return {"ok": False, "error": f"file too large (>{MAX_READ_BYTES} bytes)"}
    try:
        text = open(resolved, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return {"ok": False, "error": str(e)}
    lines = text.splitlines()
    start = max(1, int(start or 1))
    limit = max(1, min(int(limit or 400), 800))
    chunk = lines[start - 1:start - 1 + limit]
    numbered = "\n".join(f"{i + start}|{line}" for i, line in enumerate(chunk))
    return {
        "ok": True,
        "path": _rel(resolved),
        "start": start,
        "lines": len(lines),
        "shown": len(chunk),
        "content": numbered,
    }


def code_search(query: str, glob: str = "", path: str = ".", root: str | None = None) -> dict[str, Any]:
    if not (query or "").strip():
        return {"ok": False, "error": "empty query"}
    try:
        root = _resolve(path or ".", root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    glob_l = (glob or "").lower()
    hits = []
    try:
        rx = re.compile(query)
    except re.error:
        rx = None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if glob_l and glob_l not in name.lower() and not name.lower().endswith(glob_l):
                continue
            full = os.path.join(dirpath, name)
            if _is_secret(full):
                continue
            try:
                if os.path.getsize(full) > MAX_READ_BYTES:
                    continue
                text = open(full, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                found = bool(rx.search(line)) if rx is not None else query in line
                if not found:
                    continue
                hits.append({"path": _rel(full), "line": i, "text": line[:240]})
                if len(hits) >= MAX_SEARCH_HITS:
                    return {"ok": True, "query": query, "hits": hits, "truncated": True}
    return {"ok": True, "query": query, "hits": hits, "truncated": False}


def code_edit(path: str, old_string: str | None = None, new_string: str | None = None,
              content: str | None = None, root: str | None = None) -> dict[str, Any]:
    try:
        resolved = _resolve(path, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if _is_secret(resolved):
        return {"ok": False, "error": "refused: secrets are not writable by hands"}
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    if old_string:
        if not os.path.isfile(resolved):
            return {"ok": False, "error": f"not a file: {_rel(resolved)}"}
        current = open(resolved, encoding="utf-8", errors="replace").read()
        count = current.count(old_string)
        if count == 0:
            return {"ok": False, "error": "old_string not found", "path": _rel(resolved)}
        if count > 1:
            return {"ok": False, "error": f"old_string matched {count} times; make it unique", "path": _rel(resolved)}
        updated = current.replace(old_string, new_string if new_string is not None else "", 1)
    else:
        updated = content if content is not None else (new_string or "")
    data = updated.encode("utf-8")
    with open(resolved, "wb") as f:
        f.write(data)
    return {"ok": True, "path": _rel(resolved), "bytes": len(data)}


def _git(argv: list[str]) -> dict[str, Any]:
    git = shutil.which("git")
    if not git:
        return {"ok": False, "error": "git not on PATH"}
    try:
        proc = subprocess.run(
            [git, *argv],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "")[-8000:],
        "stderr": (proc.stderr or "")[-2000:],
        "argv": argv,
    }


def git_status() -> dict[str, Any]:
    return _git(["status", "--porcelain", "-b"])


def git_diff(path: str = "") -> dict[str, Any]:
    argv = ["diff"]
    if path:
        argv.extend(["--", path])
    return _git(argv)


def git_commit(message: str, paths: list[str] | None = None) -> dict[str, Any]:
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "commit message required"}
    if "--no-verify" in msg or "-n " in f" {msg} ":
        return {"ok": False, "error": "commit message must not request --no-verify"}
    if paths:
        add = _git(["add", "--", *[str(p) for p in paths]])
    else:
        add = _git(["add", "-u"])
    if not add.get("ok"):
        return {"ok": False, "error": "git add failed", "detail": add}
    return _git(["commit", "-m", msg])


def dispatch(name: str, args: dict, root: str | None = None) -> dict[str, Any]:
    args = args or {}
    if name == "ws.list":
        return ws_list(args.get("path", args.get("dir", ".")), args.get("glob", args.get("query", "")), root=root)
    if name == "code.read":
        return code_read(args.get("path", args.get("file", "")), int(args.get("start", 1) or 1),
                         int(args.get("limit", args.get("n", 400)) or 400), root=root)
    if name == "code.search":
        return code_search(args.get("query", args.get("pattern", args.get("q", ""))),
                           args.get("glob", ""), args.get("path", "."), root=root)
    if name == "code.edit":
        return code_edit(
            args.get("path", args.get("file", "")),
            old_string=args.get("old_string", args.get("old", None)),
            new_string=args.get("new_string", args.get("new", None)),
            content=args.get("content"),
            root=root,
        )
    if name == "git.status":
        return git_status()
    if name == "git.diff":
        return git_diff(args.get("path", ""))
    if name == "git.commit":
        paths = args.get("paths") or args.get("files")
        if isinstance(paths, str):
            paths = [paths]
        return git_commit(args.get("message", args.get("m", "")), paths)
    return {"ok": False, "error": f"unknown hand: {name}"}
