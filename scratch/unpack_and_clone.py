import os
import zipfile
import subprocess
import glob
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Unpack nava wheel
whl_files = glob.glob('scratch/stolen_repos/nava_pkg/*.whl')
if whl_files:
    whl = whl_files[0]
    out_dir = os.path.join('scratch', 'stolen_repos', 'nava-agent')
    print(f"Extracting {whl} to {out_dir}...")
    with zipfile.ZipFile(whl, 'r') as z:
        z.extractall(out_dir)
    print("NAVA extracted successfully!")

# Clone gsv, OpenDAN, AgentVerse-OS
remaining = {
    'gsv': 'https://github.com/deathbyknowledge/gsv.git',
    'OpenDAN': 'https://github.com/fiatrete/OpenDAN-Personal-AI-OS.git',
    'AgentVerse-OS': 'https://github.com/agentverse-os/AgentVerse-OS.git',
}

base_dir = os.path.join('scratch', 'stolen_repos')
for name, url in remaining.items():
    dest = os.path.join(base_dir, name)
    if not os.path.exists(dest):
        print(f"Cloning {name}...")
        res = subprocess.run(['git', 'clone', '--depth', '1', url, dest], capture_output=True, text=True)
        print(f"[{name}] returncode={res.returncode}")
        if res.stderr:
            print(f"  stderr: {res.stderr[:200]}")
    else:
        print(f"[{name}] already cloned.")
