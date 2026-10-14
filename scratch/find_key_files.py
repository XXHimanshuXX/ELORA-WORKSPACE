import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

targets = ['nava-agent', 'eidetic-os', 'eidolon-os', 'forge-os', 'AgentVerse-OS', 'aura-os']
base = os.path.join('scratch', 'stolen_repos')

for t in targets:
    tpath = os.path.join(base, t)
    print(f"\n======================================")
    print(f" TARGET: {t}")
    print(f"======================================")
    all_files = []
    for root, dirs, files in os.walk(tpath):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', 'target', '__pycache__', '.venv', 'dist', 'build')]
        for f in files:
            all_files.append(os.path.relpath(os.path.join(root, f), tpath))

    # Filter interesting files (UI, task, chat, agent, workflow)
    interesting = [f for f in all_files if any(k in f.lower() for k in ('ui', 'task', 'chat', 'agent', 'workflow', 'pipeline', 'prompt', 'server', 'view', 'web', 'app'))]
    print(f"Total files: {len(all_files)}, Interesting: {len(interesting)}")
    for f in interesting[:25]:
        print(f"  * {f}")
    if len(interesting) > 25:
        print(f"  ... and {len(interesting) - 25} more")
