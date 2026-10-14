import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

base = os.path.join('scratch', 'stolen_repos')
repos = ['eidolon-os', 'eidetic-os', 'forge-os', 'aura-os', 'nava-agent', 'AgentVerse-OS', 'gsv', 'OpenDAN']

for r in repos:
    rpath = os.path.join(base, r)
    print(f"\n==========================================")
    print(f"  REPO: {r}")
    print(f"==========================================")
    if not os.path.exists(rpath):
        print("  DOES NOT EXIST")
        continue
    for root, dirs, files in os.walk(rpath):
        # Skip git and heavy dirs
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', 'target', '__pycache__', '.venv', 'dist', 'build')]
        rel = os.path.relpath(root, rpath)
        depth = rel.count(os.sep)
        if depth <= 2:
            indent = "  " * depth
            dname = os.path.basename(root) if rel != '.' else '.'
            print(f"{indent}[{dname}] ({len(files)} files)")
            for f in files[:8]:
                print(f"{indent}  - {f}")
            if len(files) > 8:
                print(f"{indent}  ... and {len(files) - 8} more files")
