"""
control_plane.py — the hidden IDE loop.

Not buttons. Not a marketplace page. The organs that make a house feel
like Cursor/JetBrains without stealing their code:

  repo_map   compact symbol index so the brain does not grep the universe
  checkpoint copy of a file before overwrite (never secrets)
  restore    last checkpoint for one path
  diagnose   py_compile / syntax — run after every code.edit, silently

This is ELORA's control plane. Absence is reported as absence.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import py_compile
import re
import time
from typing import Any

from elora.core.owner_will import WORKSPACE_ROOT
from elora.slime.hands import SKIP_DIRS, _is_secret, _rel, _resolve

CHECKPOINT_ROOT = os.path.join(".elora", "checkpoints")
MAX_MAP_FILES = 80
MAX_SYMBOLS = 400
_PY_DEF = re.compile(r"^(?:async\s+)?def\s+(\w+)|^(?:class)\s+(\w+)", re.M)
_JS_DEF = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|^(?:export\s+)?class\s+(\w+)",
    re.M,
)

_STOPWORDS = {
    "fix", "update", "change", "add", "remove", "how", "to", "the", "a", "an",
    "in", "of", "and", "or", "is", "for", "with", "where", "what", "why",
    "when", "about", "please", "can", "you", "my", "this", "that", "it", "on",
    "from", "by", "as", "at", "use", "make", "current", "result", "using",
    "instead", "require", "prefer", "ignore", "keep", "over", "matches", "words"
}


def _ckpt_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), CHECKPOINT_ROOT, "objects")


def snapshot_file(path: str, root: str | None = None) -> dict[str, Any]:
    """Save one jailed file's bytes before mutation. Secrets refused."""
    try:
        resolved = _resolve(path, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if _is_secret(resolved):
        return {"ok": False, "error": "refused: secrets are not checkpointed"}
    store = _ckpt_dir(root or WORKSPACE_ROOT)
    os.makedirs(store, exist_ok=True)
    log_path = os.path.join(os.path.dirname(store), "log.jsonl")
    if not os.path.isfile(resolved):
        rec = {"ts": time.time(), "path": _rel(resolved), "exists": False,
               "sha256": None, "bytes": 0}
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(rec) + "\n")
        return {"ok": True, "created": True, "path": rec["path"], "bytes": 0}
    data = open(resolved, "rb").read()
    digest = hashlib.sha256(data).hexdigest()
    blob = os.path.join(store, digest)
    if not os.path.isfile(blob):
        with open(blob, "wb") as handle:
            handle.write(data)
    rec = {"ts": time.time(), "path": _rel(resolved), "exists": True,
           "sha256": digest, "bytes": len(data)}
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec) + "\n")
    return {"ok": True, "path": rec["path"], "sha256": digest, "bytes": len(data)}


def restore_file(path: str, root: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    """Restore the latest checkpoint, or an explicitly named checkpoint, for one path."""
    try:
        resolved = _resolve(path, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if _is_secret(resolved):
        return {"ok": False, "error": "refused: secrets are not writable"}
    requested_sha = str(sha256 or "").strip().lower()
    if requested_sha and not re.fullmatch(r"[a-f0-9]{64}", requested_sha):
        return {"ok": False, "error": "invalid checkpoint sha256"}
    log_path = os.path.join(os.path.abspath(root or WORKSPACE_ROOT), CHECKPOINT_ROOT, "log.jsonl")
    if not os.path.isfile(log_path):
        return {"ok": False, "error": "no checkpoints yet"}
    target = _rel(resolved)
    selected = None
    with open(log_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("path") == target or rec.get("path") == target.replace("\\", "/"):
                candidate = str(rec.get("sha256", "")).lower()
                if requested_sha and candidate != requested_sha:
                    continue
                selected = rec
    if selected is None:
        return {"ok": False, "error": f"no checkpoint for {target}"}
    if not selected.get("exists", True):
        return {"ok": False, "error": "checkpoint records an absent file; restore will not delete current data"}
    sha = str(selected.get("sha256") or "").lower()
    blob = os.path.join(_ckpt_dir(root or WORKSPACE_ROOT), sha)
    if not os.path.isfile(blob):
        return {"ok": False, "error": "checkpoint blob missing"}
    os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
    data = open(blob, "rb").read()
    with open(resolved, "wb") as handle:
        handle.write(data)
    return {"ok": True, "path": target, "sha256": sha, "bytes": len(data)}


def diagnose(path: str, root: str | None = None) -> dict[str, Any]:
    """Syntax check one file. Python uses py_compile. Other languages: readable."""
    try:
        resolved = _resolve(path, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not os.path.isfile(resolved):
        return {"ok": False, "error": f"not a file: {_rel(resolved)}"}
    if _is_secret(resolved):
        return {"ok": False, "error": "refused: secrets"}
    rel = _rel(resolved)
    if resolved.endswith(".py"):
        try:
            py_compile.compile(resolved, doraise=True)
        except py_compile.PyCompileError as exc:
            return {"ok": False, "path": rel, "error": str(exc)}
        try:
            ast.parse(open(resolved, encoding="utf-8", errors="replace").read())
        except SyntaxError as exc:
            return {"ok": False, "path": rel, "error": f"{exc.msg} line {exc.lineno}"}
        return {"ok": True, "path": rel, "lang": "python"}
    if resolved.endswith((".js", ".mjs")):
        import subprocess
        try:
            proc = subprocess.run(
                ["node", "--check", resolved],
                cwd=os.path.abspath(root or WORKSPACE_ROOT),
                capture_output=True,
                text=True,
                timeout=5,
                shell=False
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout).strip()
                return {"ok": False, "path": rel, "error": err}
            return {"ok": True, "path": rel, "lang": "javascript"}
        except FileNotFoundError:
            return {"ok": True, "path": rel, "lang": "opaque", "note": "node unavailable"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "path": rel, "error": "timeout running node"}
    return {"ok": False, "path": rel, "lang": "opaque", "note": "no syntax engine for this suffix"}


def repo_map(query: str = "", path: str = ".", root: str | None = None) -> dict[str, Any]:
    """Compact symbol map. Query ranks; empty query is recency."""
    needle = (query or "").strip().lower()
    try:
        base = _resolve(path or ".", root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    scored: list[tuple[float, dict[str, Any]]] = []
    n_files = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith((".py", ".js", ".ts", ".mjs")):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            if _is_secret(full):
                continue
            n_files += 1
            try:
                text = open(full, encoding="utf-8", errors="replace").read()
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            symbols: list[str] = []
            if name.endswith(".py"):
                try:
                    tree = ast.parse(text)
                    for node in tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            symbols.append(node.name)
                except SyntaxError:
                    symbols = [m.group(1) or m.group(2) for m in _PY_DEF.finditer(text) if m.group(1) or m.group(2)]
            else:
                symbols = [m.group(1) or m.group(2) for m in _JS_DEF.finditer(text) if m.group(1) or m.group(2)]
            rel = _rel(full).replace("\\", "/")
            hay = (rel + " " + " ".join(symbols)).lower()
            is_test = 1 if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.js") else 0
            if needle:
                terms = [t for t in needle.split() if t not in _STOPWORDS and len(t) > 2]
                overlap = sum(1 for term in terms if term in hay)
                if terms and overlap == 0:
                    continue
                rank = (-overlap, is_test, -mtime, rel)
            else:
                rank = (0, is_test, -mtime, rel)
            scored.append((rank, {"path": rel, "symbols": symbols[:24], "mtime": int(mtime)}))
    scored.sort(key=lambda row: row[0])
    files = [row[1] for row in scored[:MAX_MAP_FILES]]
    n_sym = 0
    for item in files:
        n_sym += len(item["symbols"])
        if n_sym > MAX_SYMBOLS:
            item["symbols"] = item["symbols"][: max(0, MAX_SYMBOLS - (n_sym - len(item["symbols"])))]
            break
    return {
        "ok": True,
        "query": query,
        "files": files,
        "file_count": len(files),
        "walked": n_files,
    }


def dispatch(name: str, args: dict, root: str | None = None) -> dict[str, Any]:
    args = args or {}
    if name == "sandbox.repo_map":
        return repo_map(args.get("query", args.get("q", "")), args.get("path", "."), root=root)
    if name == "sandbox.checkpoint":
        paths = args.get("paths") or args.get("path") or args.get("file")
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return {"ok": False, "error": "path required"}
        return snapshot_file(str(paths[0]), root=root)
    if name == "sandbox.restore":
        return restore_file(
            str(args.get("path", args.get("file", ""))),
            root=root,
            sha256=args.get("sha256"),
        )
    if name == "sandbox.diagnose":
        return diagnose(str(args.get("path", args.get("file", ""))), root=root)
    return {"ok": False, "error": f"unknown control-plane organ: {name}"}
