"""Start the console server detached, then wait until it answers health.

Detached so it survives this script exiting, which is what lets a browser (or the
desktop shell) reach it afterwards.
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8765
LOG = os.path.join(ROOT, "tools", "_res", "server.log")


def health(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


if health(PORT):
    print(f"already running on {PORT}")
    raise SystemExit(0)

os.makedirs(os.path.dirname(LOG), exist_ok=True)
flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
with open(LOG, "wb") as log:
    subprocess.Popen(
        [sys.executable, "-m", "elora.dashboard.server", "--port", str(PORT), "--announce"],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=flags, cwd=ROOT,
    )

for _ in range(60):
    if health(PORT):
        print(f"listening on http://127.0.0.1:{PORT}/")
        raise SystemExit(0)
    time.sleep(0.5)

print("did not come up in 30s; see tools/_res/server.log")
raise SystemExit(1)
