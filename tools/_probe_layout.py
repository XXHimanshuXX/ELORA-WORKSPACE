"""Locate where skills / agents / plugin manifests ACTUALLY live. Counts + paths only."""
import os
import sys

HOME = os.path.expanduser("~")
CANDIDATES = [".claude", ".agents", ".codex", ".gemini", ".config"]
PRUNE = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build"}


def walk_counts(base, filename, max_depth=9):
    """Return (per_first_child_counts, total)."""
    per = {}
    total = 0
    if not os.path.isdir(base):
        return per, 0
    for current, dirnames, filenames in os.walk(base, followlinks=False):
        depth = current[len(base):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if d not in PRUNE]
        if filename in filenames:
            total += 1
            rel = os.path.relpath(current, base)
            head = rel.split(os.sep)[0] if rel != "." else "(root)"
            per[head] = per.get(head, 0) + 1
    return per, total


for top in CANDIDATES:
    base = os.path.join(HOME, top)
    if not os.path.isdir(base):
        print(f"{top}: ABSENT")
        continue
    print(f"\n### {top}")
    # 1. Where are SKILL.md files?
    per, total = walk_counts(base, "SKILL.md")
    print(f"  SKILL.md total={total}  by top-level dir: {dict(sorted(per.items(), key=lambda kv: -kv[1])[:8])}")
    # 2. Agent-style markdown dirs
    for sub in ("agents", "subagents", "personas"):
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            try:
                mds = [f for f in os.listdir(p) if f.lower().endswith(".md")]
            except OSError:
                mds = []
            print(f"  {sub}/ -> {len(mds)} .md files")
    # 3. plugin.json manifests
    per3, total3 = walk_counts(base, "plugin.json")
    if total3:
        print(f"  plugin.json total={total3} by top-level: {dict(sorted(per3.items(), key=lambda kv: -kv[1])[:6])}")
    # 4. immediate children listing (1 level)
    try:
        kids = sorted(os.listdir(base))[:22]
        print(f"  top-level entries ({len(os.listdir(base))}): {kids}")
    except OSError as exc:
        print(f"  unreadable: {exc}")

print("\n### omniroute mcp server path check")
for p in (os.path.join(HOME, "AppData", "Roaming", "npm", "node_modules", "omniroute", "bin", "mcp-server.mjs"),):
    print(f"  {p} exists={os.path.exists(p)}")
