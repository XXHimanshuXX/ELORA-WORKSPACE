"""
discovery.py — what this machine actually contains.

The dashboard claims to show "my skills and features". Claims like that are
normally satisfied with a hardcoded list. This module goes and looks: it walks
the real agent directories, parses the real manifest formats, and reports what
is on disk — including the parts that are broken.

Two rules shape every line below.

1. NOTHING SHAPE-SHIFTING LEAVES THIS MODULE.
   Config files in agent directories routinely carry API keys in plaintext. A
   discovery scan that faithfully returns them turns the dashboard into a
   credential-display surface. Redaction happens at two layers: secret-shaped
   KEYS have their whole value subtree dropped, and any string that still looks
   like a credential is masked, wherever it appears in the structure. There is a
   self-test (`contains_secret`) that the callers run over their own payload as
   a backstop, because one filter is a hope and two are a check.

2. A CAPPED SCAN MUST NOT LIE ABOUT ITS TOTAL.
   `.gemini` alone holds thousands of skill files. Walking all of it on every
   panel refresh is absurd, so per-root collection is capped — but the TRUE
   count is measured separately and every payload says whether it was truncated.
   A number that silently means "the first 300" is worse than no number.

Every root is reported, including the ones that are missing. A directory that
is absent is a finding, not an omission.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

# ----------------------------------------------------------------------
# Secrets
# ----------------------------------------------------------------------

# Explicit credential shapes. These are matched even inside paths/URLs, because
# a token embedded in a URL is still a token.
_SECRET_SHAPES = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}"),  # JWT
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
)

# A generic high-entropy token. Deliberately NOT applied to strings containing
# path or URL punctuation: a long directory name is not a credential, and
# mangling paths would make the inventory useless.
_OPAQUE = re.compile(r"^[A-Za-z0-9_\-]{24,}$")

# Keys whose entire subtree is dropped. Matched case-insensitively as substrings,
# so `omniroute_api_key`, `ANTHROPIC_AUTH_TOKEN` and `client_secret` all hit.
_SECRET_KEY_MARKERS = (
    "api_key", "apikey", "api-key", "secret", "token", "password", "passwd",
    "credential", "private_key", "access_key", "auth", "cookie", "session_key",
    "bearer", "client_id", "connection_string", "dsn",
)

MASK = "[redacted]"


def is_secret_key(key: str) -> bool:
    """True if a mapping key names something whose value must never be emitted."""
    lowered = str(key).lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _looks_secretish(value: str) -> bool:
    if any(pattern.search(value) for pattern in _SECRET_SHAPES):
        return True
    stripped = value.strip()
    if not stripped or len(stripped) < 24:
        return False
    # Only bare opaque blobs, never paths or URLs.
    if any(ch in stripped for ch in "/\\:. "):
        return False
    if not _OPAQUE.match(stripped):
        return False
    has_digit = any(ch.isdigit() for ch in stripped)
    has_alpha = any(ch.isalpha() for ch in stripped)
    return has_digit and has_alpha


def redact(value: Any, _depth: int = 0) -> Any:
    """
    Return a structurally identical copy with credentials removed.

    Recursion is depth-limited: agent config trees are shallow, and an
    unbounded walk over attacker-controlled JSON is a denial-of-service shape.
    """
    if _depth > 12:
        return MASK
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if is_secret_key(str(key)):
                out[str(key)] = MASK          # the NAME stays: it documents a requirement
            else:
                out[str(key)] = redact(item, _depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item, _depth + 1) for item in value]
    if isinstance(value, str):
        if _looks_secretish(value):
            return MASK
        for pattern in _SECRET_SHAPES:
            if pattern.search(value):
                return pattern.sub(MASK, value)
        return value
    return value


def contains_secret(value: Any, _depth: int = 0) -> bool:
    """
    Backstop self-test: does any un-redacted credential survive in this payload?

    Callers run this over what they are about to serve. If it ever returns True
    the correct response is to refuse the payload, not to serve it and hope.
    """
    if _depth > 12:
        return False
    if isinstance(value, dict):
        return any(contains_secret(v, _depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(v, _depth + 1) for v in value)
    if isinstance(value, str):
        return value != MASK and _looks_secretish(value)
    return False


# ----------------------------------------------------------------------
# Roots
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class Root:
    """One place things of a kind live. `kind` drives how it is interpreted."""
    id: str
    label: str
    path: str
    kind: str = "skills"          # skills | agents | mcp | plugins
    vendor: str = ""
    # Set when this root is a known duplicate (a backup tree, or a junction
    # pointing at another root). Its contents are MEASURED and REPORTED, but
    # never added to the totals — counting a backup copy as capability is
    # how an inventory inflates itself.
    duplicate_of: str = ""


# Relative to the user's home, so this survives the machine being reimaged.
#
# Every path here was MEASURED on this machine, not assumed. An earlier version
# guessed `.codex/skills` as the codex tree and missed 394 files; it also had no
# root for `.claude/agents`, which turns out to hold the 263 agent definitions.
_HOME = os.path.expanduser("~")

DEFAULT_ROOTS: tuple[Root, ...] = (
    Root("claude-agents", "Claude agents", os.path.join(_HOME, ".claude", "agents"),
         "agents", "claude"),
    Root("claude-skills", "Claude skills", os.path.join(_HOME, ".claude", "skills"),
         "skills", "claude"),
    Root("claude-plugins", "Claude plugins", os.path.join(_HOME, ".claude", "plugins"),
         "plugins", "claude"),
    Root("agents-skills", "Agent skills", os.path.join(_HOME, ".agents", "skills"),
         "skills", "agents"),
    Root("codex-skills", "Codex skills", os.path.join(_HOME, ".codex", "skills"),
         "skills", "codex"),
    Root("codex-plugins", "Codex plugins", os.path.join(_HOME, ".codex", "plugins"),
         "skills", "codex"),
    Root("gemini-skills", "Gemini config skills", os.path.join(_HOME, ".gemini", "config"),
         "skills", "gemini"),
    Root("gemini-ide", "Antigravity IDE skills",
         os.path.join(_HOME, ".gemini", "antigravity-ide"), "skills", "gemini"),
    # 1451 SKILL.md files that are a second copy of gemini-ide. Counted, labelled,
    # and left out of the totals.
    Root("gemini-backup", "Antigravity backup",
         os.path.join(_HOME, ".gemini", "antigravity-backup"), "skills", "gemini",
         duplicate_of="gemini-ide"),
    Root("codex-config", "Codex config", os.path.join(_HOME, ".codex", "config.toml"),
         "mcp", "codex"),
    Root("claude-config", "Claude config", os.path.join(_HOME, ".claude.json"),
         "mcp", "claude"),
    Root("gemini-config", "Gemini settings", os.path.join(_HOME, ".gemini", "settings.json"),
         "mcp", "gemini"),
)

# Directories that must never be descended into: they are caches, and they are
# where the thousands of duplicate skill files live. `.tmp` is measured, not
# guessed: `.codex/.tmp` alone held 310 SKILL.md files against 6 real ones.
_PRUNE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".next", ".turbo", ".tmp", ".cache",
}

_MAX_DEPTH = 8
_FRONTMATTER_CHARS = 4096
_TRUE_TOTAL_CAP = 200_000       # a runaway walk must terminate


@dataclass
class ScanStats:
    """What a scan was allowed to do, and what it had to skip."""
    roots_scanned: int = 0
    roots_missing: int = 0
    entries_seen: int = 0
    dirs_visited: int = 0
    truncated: bool = False
    duration_ms: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "roots_scanned": self.roots_scanned,
            "roots_missing": self.roots_missing,
            "entries_seen": self.entries_seen,
            "dirs_visited": self.dirs_visited,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "errors": self.errors,
        }


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

def _read_text(path: str, limit: int | None = None) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read() if limit is None else handle.read(limit)
    except (OSError, ValueError):
        return None


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """
    The `--- key: value ---` header that SKILL.md files use.

    Hand-rolled rather than pulling in a YAML dependency: the format here is a
    flat map of scalars, and a full parser would be a larger attack surface for
    a smaller feature. Nested structures are reported as raw strings rather than
    guessed at.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, Any] = {}
    for line in text[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        if not key:
            continue
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        meta[key] = raw
    return meta


def _parse_toml(text: str) -> dict[str, Any] | None:
    try:
        import tomllib                     # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        pass
    except Exception:
        return None
    try:
        import tomli                       # optional backport
        return tomli.loads(text)
    except Exception:
        return None


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------

def _walk_skill_dirs(root: Root, cap: int, stats: ScanStats,
                     deadline: float) -> list[dict[str, Any]]:
    """Collect skill directories under one root, up to `cap`."""
    found: list[dict[str, Any]] = []
    base = root.path
    if not os.path.isdir(base):
        return found

    for current, dirnames, filenames in os.walk(base, followlinks=False):
        if time.monotonic() > deadline:
            stats.truncated = True
            break
        stats.dirs_visited += 1
        depth = current[len(base):].count(os.sep)
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE_DIRS)

        if "SKILL.md" not in filenames:
            continue
        stats.entries_seen += 1
        if len(found) >= cap:
            stats.truncated = True
            continue

        skill_file = os.path.join(current, "SKILL.md")
        text = _read_text(skill_file, _FRONTMATTER_CHARS) or ""
        meta = _parse_frontmatter(text)
        try:
            size = os.path.getsize(skill_file)
            mtime = os.path.getmtime(skill_file)
        except OSError:
            size, mtime = 0, 0.0
        found.append({
            "name": meta.get("name") or os.path.basename(current),
            "description": (meta.get("description") or "")[:400],
            "slug": os.path.relpath(current, base).replace("\\", "/"),
            "path": current,
            "bytes": size,
            "modified": time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else "",
            "vendor": root.vendor,
            "source_root": root.id,
        })
    return found


def _count_skill_dirs(root: Root, stats: ScanStats, deadline: float) -> int:
    """
    The TRUE number of skills under a root, measured independently of the cap.

    This is a second walk on purpose. Deriving the total from a capped
    collection is how a dashboard ends up confidently reporting "300 skills"
    for a directory that holds three thousand.
    """
    if not os.path.isdir(root.path):
        return 0
    total = 0
    for current, dirnames, filenames in os.walk(root.path, followlinks=False):
        if time.monotonic() > deadline or total > _TRUE_TOTAL_CAP:
            stats.truncated = True
            break
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE_DIRS)
        if "SKILL.md" in filenames:
            total += 1
    return total


def _discover_agents(root: Root, cap: int, stats: ScanStats) -> list[dict[str, Any]]:
    """Agent definitions: markdown files carrying frontmatter, directly in a dir."""
    found: list[dict[str, Any]] = []
    if not os.path.isdir(root.path):
        return found
    try:
        names = sorted(os.listdir(root.path))
    except OSError as exc:
        stats.errors.append({"root": root.id, "error": str(exc)})
        return found
    for name in names:
        if not name.lower().endswith(".md"):
            continue
        stats.entries_seen += 1
        if len(found) >= cap:
            stats.truncated = True
            continue
        full = os.path.join(root.path, name)
        meta = _parse_frontmatter(_read_text(full, _FRONTMATTER_CHARS) or "")
        found.append({
            "name": meta.get("name") or name[:-3],
            "description": (meta.get("description") or "")[:400],
            "slug": name[:-3],
            "path": full,
            "vendor": root.vendor,
            "source_root": root.id,
        })
    return found


def _discover_plugin_manifests(root: Root, cap: int, stats: ScanStats,
                               deadline: float) -> list[dict[str, Any]]:
    """`plugin.json` manifests — the only plugin format that actually exists here."""
    found: list[dict[str, Any]] = []
    if not os.path.isdir(root.path):
        return found
    for current, dirnames, filenames in os.walk(root.path, followlinks=False):
        if time.monotonic() > deadline:
            stats.truncated = True
            break
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE_DIRS)
        if "plugin.json" not in filenames:
            continue
        stats.entries_seen += 1
        if len(found) >= cap:
            stats.truncated = True
            continue
        full = os.path.join(current, "plugin.json")
        raw = _read_text(full, 65536)
        if raw is None:
            continue
        try:
            manifest = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            stats.errors.append({"root": root.id, "path": full,
                                 "error": f"invalid JSON: {exc}"})
            continue
        if not isinstance(manifest, dict):
            continue
        plugins = manifest.get("plugins")
        if isinstance(plugins, list) and plugins:
            for entry in plugins:
                if not isinstance(entry, dict) or len(found) >= cap:
                    continue
                found.append({
                    "name": entry.get("name") or os.path.basename(current),
                    "description": (entry.get("description") or "")[:400],
                    "slug": entry.get("name") or os.path.basename(current),
                    "path": full,
                    "vendor": root.vendor,
                    "source_root": root.id,
                    "marketplace": manifest.get("name", ""),
                })
        else:
            found.append({
                "name": manifest.get("name") or os.path.basename(current),
                "description": (manifest.get("description") or "")[:400],
                "slug": manifest.get("name") or os.path.basename(current),
                "path": full,
                "vendor": root.vendor,
                "source_root": root.id,
                "marketplace": manifest.get("name", ""),
            })
    return found


def _mcp_from_json(path: str, key: str) -> tuple[dict[str, Any], str]:
    """Extract an MCP server map from a JSON config. Returns (servers, error)."""
    raw = _read_text(path, 4_000_000)
    if raw is None:
        return {}, "unreadable"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return {}, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return {}, "config root is not an object"
    servers = data.get(key)
    if not isinstance(servers, dict):
        return {}, f"no {key!r} object"
    return servers, ""


def collect_mcp_servers(roots: Iterable[Root]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """
    Every configured MCP server, across every client that configures one.

    Server NAMES and the env var names they expect are reported; the values are
    dropped by `redact`. A dashboard should be able to say "this server needs
    GITHUB_TOKEN" without ever saying what GITHUB_TOKEN is.
    """
    servers: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []

    for root in roots:
        if root.kind != "mcp":
            continue
        if not os.path.exists(root.path):
            problems.append({"root": root.id, "path": root.path, "error": "absent"})
            continue
        if root.path.endswith(".json"):
            found, error = _mcp_from_json(root.path, "mcpServers")
            if not found:
                found, error2 = _mcp_from_json(root.path, "mcp_servers")
                error = error if found else (error2 or error)
            if error and not found:
                if error not in ("no 'mcpServers' object", "no 'mcp_servers' object"):
                    problems.append({"root": root.id, "path": root.path, "error": error})
                continue
        elif root.path.endswith(".toml"):
            text = _read_text(root.path, 4_000_000)
            if text is None:
                problems.append({"root": root.id, "path": root.path, "error": "unreadable"})
                continue
            parsed = _parse_toml(text)
            if parsed is None:
                problems.append({"root": root.id, "path": root.path,
                                 "error": "TOML parser unavailable or file invalid"})
                continue
            found = parsed.get("mcp_servers")
            if not isinstance(found, dict):
                problems.append({"root": root.id, "path": root.path,
                                 "error": "no [mcp_servers] table"})
                continue
        else:
            continue

        for name, spec in found.items():
            if not isinstance(spec, dict):
                continue
            env = spec.get("env") if isinstance(spec.get("env"), dict) else {}
            servers.append({
                "name": str(name),
                "client": root.vendor,
                "source": root.path,
                "command": str(spec.get("command", "")),
                "args": [str(a) for a in (spec.get("args") or [])][:12],
                "url": str(spec.get("url", "")),
                "env_names": sorted(str(k) for k in env),
                "disabled": bool(spec.get("disabled", False)),
            })
    return servers, problems


def discover(roots: Iterable[Root] | None = None, per_root_cap: int = 300,
             budget_s: float = 45.0) -> dict[str, Any]:
    """
    One full inventory pass.

    Returns a payload shaped for the dashboard, plus the scan's own honesty
    record: what was capped, what was missing, what failed to parse.
    """
    started = time.monotonic()
    deadline = started + budget_s
    roots = tuple(roots if roots is not None else DEFAULT_ROOTS)
    stats = ScanStats()

    skills: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    plugins: list[dict[str, Any]] = []
    skills_by_root: dict[str, dict[str, Any]] = {}
    seen_realpaths: dict[str, str] = {}
    effective_roots: list[Root] = []

    for root in roots:
        if root.kind == "mcp":
            continue
        exists = os.path.exists(root.path)
        if not exists:
            stats.roots_missing += 1
            continue

        # A junction makes one tree appear under two names. `.claude/skills` is
        # measured to be a junction onto `.agents/skills`, so without this check
        # those 79 skills are counted twice and the headline number is wrong by
        # 79. Whichever root is reached second is demoted to a reported
        # duplicate, automatically, from the filesystem rather than a guess.
        resolved = os.path.realpath(root.path)
        if not root.duplicate_of:
            first = seen_realpaths.get(resolved)
            if first is not None:
                root = replace(root, duplicate_of=first)
            else:
                seen_realpaths[resolved] = root.id

        stats.roots_scanned += 1
        effective_roots.append(root)

        # Plugin trees also carry skills of their own, so they are walked for
        # both. Skipping the skill walk here is how 31 real skills in
        # `.claude/plugins` go uncounted while their manifests get listed.
        if root.kind in ("skills", "plugins"):
            collected = _walk_skill_dirs(root, per_root_cap, stats, deadline)
            true_total = _count_skill_dirs(root, stats, deadline)
            if not root.duplicate_of:
                skills.extend(collected)
            skills_by_root[root.id] = {
                "label": root.label,
                "vendor": root.vendor,
                "found": len(collected),
                "total": true_total,
                "capped": len(collected) < true_total,
                "counted": not bool(root.duplicate_of),
                "duplicate_of": root.duplicate_of,
            }

        if root.kind == "agents":
            collected = _discover_agents(root, per_root_cap, stats)
            agents.extend(collected)
        elif root.kind == "plugins":
            collected = _discover_plugin_manifests(root, per_root_cap, stats, deadline)
            plugins.extend(collected)

    mcp_servers, mcp_problems = collect_mcp_servers(roots)

    # Per-vendor totals, so duplication between vendor trees is visible rather
    # than hidden behind one aggregate number.
    by_vendor: dict[str, int] = {}
    for skill in skills:
        by_vendor[skill["vendor"]] = by_vendor.get(skill["vendor"], 0) + 1

    stats.duration_ms = int((time.monotonic() - started) * 1000)

    def _root_row(r: Root) -> dict[str, Any]:
        exists = os.path.exists(r.path)
        # A junction or symlink makes one tree appear twice. Reporting where a
        # root actually resolves is what lets the UI say "these 79 are the same
        # 79" instead of showing 158 distinct-looking skills.
        resolved = os.path.realpath(r.path) if exists else ""
        return {
            "id": r.id,
            "label": r.label,
            "path": r.path,
            "kind": r.kind,
            "vendor": r.vendor,
            "exists": exists,
            "duplicate_of": r.duplicate_of,
            "resolves_to": "" if resolved == os.path.abspath(r.path) else resolved,
        }

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "roots": [_root_row(r) for r in effective_roots],
        "skills": redact(skills),
        "skills_by_root": skills_by_root,
        "skills_total_on_disk": sum(v["total"] for v in skills_by_root.values() if v["counted"]),
        "skills_uncounted_duplicates": sum(
            v["total"] for v in skills_by_root.values() if not v["counted"]),
        "agents": redact(agents),
        "plugins": redact(plugins),
        "plugin_system": {
            "available": False,
            "note": ("No runtime plugin loader exists in ELORA. `plugin.json` manifests "
                     "found on disk belong to other clients and are listed read-only."),
        },
        "mcp_servers": redact(mcp_servers),
        "mcp_problems": mcp_problems,
        "scan": stats.to_dict(),
    }
    return payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Inventory this machine's agent surface")
    parser.add_argument("--cap", type=int, default=300)
    parser.add_argument("--budget", type=float, default=45.0)
    parser.add_argument("--json", action="store_true", help="emit the raw payload")
    args = parser.parse_args()

    result = discover(per_root_cap=args.cap, budget_s=args.budget)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        scan = result["scan"]
        print(f"roots scanned {scan['roots_scanned']}, missing {scan['roots_missing']}, "
              f"{scan['duration_ms']}ms, truncated={scan['truncated']}")
        for root_id, info in result["skills_by_root"].items():
            flags = ""
            if info["capped"]:
                flags += " (CAPPED)"
            if info["duplicate_of"]:
                flags += f" (DUPLICATE of {info['duplicate_of']} — not counted)"
            print(f"  {info['label']:<24} {info['found']:>5} shown / {info['total']:>5} on disk{flags}")
        print(f"  skills counted       : {result['skills_total_on_disk']}")
        print(f"  duplicates excluded  : {result['skills_uncounted_duplicates']}")
        print(f"  agents               : {len(result['agents'])}")
        for row in result["roots"]:
            if row["resolves_to"]:
                print(f"    ~ {row['id']} resolves to {row['resolves_to']}")
        print(f"  plugin manifests     : {len(result['plugins'])}")
        print(f"  mcp servers configured: {len(result['mcp_servers'])}")
        for problem in result["mcp_problems"]:
            print(f"    ! {problem['root']}: {problem['error']}")
        leaked = contains_secret(result)
        print(f"  secret self-test     : {'LEAK DETECTED' if leaked else 'clean'}")
        if leaked:
            raise SystemExit(1)
