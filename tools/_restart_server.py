"""Restart the console server with per-request logging on.

The point is to capture what the *browser* asks for. The probe already proves the
server answers; a request log proves the frontend actually drives it, which is a
different claim. Logging is behind ELORA_DASHBOARD_LOG, and stdout is a file here,
so `-u` matters or nothing is flushed.

Kills only the PID that /api/health reports, so an unrelated python process is
never touched.
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8765
LOG = os.path.join(ROOT, "tools", "_res", "requests.log")


def health_pid():
    """The pid the server reports about itself. /api/health is the liveness probe,
    so it answers without the client header, and its body carries the pid."""
    import json

    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/health")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode()).get("pid")
    except (urllib.error.URLError, OSError, ValueError):
        return None


pid = health_pid()
if pid:
    print(f"stopping the console server, pid {pid}")
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
    for _ in range(20):
        if health_pid() is None:
            break
        time.sleep(0.25)

os.makedirs(os.path.dirname(LOG), exist_ok=True)
with open(LOG, "wb") as log:
    log.write(b"")

env = dict(os.environ)
env["ELORA_DASHBOARD_LOG"] = "1"
flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
with open(LOG, "wb") as log:
    subprocess.Popen(
        [sys.executable, "-u", "-m", "elora.dashboard.server", "--port", str(PORT), "--announce"],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=flags, cwd=ROOT, env=env,
    )

for _ in range(60):
    if health_pid():
        print(f"listening on {PORT} with logging -> {LOG}")
        raise SystemExit(0)
    time.sleep(0.5)

print("did not come up; see tools/_res/requests.log")
raise SystemExit(1)
