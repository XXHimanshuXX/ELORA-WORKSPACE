import os
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

repos = {
    'eidolon-os': 'https://github.com/fokrulanthro16-eng/eidolon-os.git',
    'eidetic-os': 'https://github.com/paulholland511/eidetic-os.git',
    'forge-os': 'https://github.com/Nolane-x/forge-os.git',
    'aura-os': 'https://github.com/aniketkrs/aura-os.git',
}

base_dir = os.path.join('scratch', 'stolen_repos')
os.makedirs(base_dir, exist_ok=True)

for name, url in repos.items():
    dest = os.path.join(base_dir, name)
    if not os.path.exists(dest):
        print(f"Cloning {name}...")
        res = subprocess.run(['git', 'clone', '--depth', '1', url, dest], capture_output=True, text=True)
        print(f"[{name}] returncode={res.returncode}")
        if res.stderr:
            print(f"  stderr: {res.stderr[:200]}")
    else:
        print(f"[{name}] already cloned.")
