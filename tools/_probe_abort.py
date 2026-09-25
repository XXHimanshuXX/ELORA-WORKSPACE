"""
_probe_abort.py — a cancelled request must not produce a traceback.

The earlier server log filled with `ConnectionAbortedError [WinError 10053]` and a
full traceback every time a page load cancelled an in-flight fetch. The guard was
`except BrokenPipeError`, and on Windows a cancelled request raises
ConnectionAbortedError instead — a sibling under ConnectionError, not a subclass —
so it fell through to the generic handler, which tried to send a 500 down the same
dead socket and blew up a second time.

This reproduces that: connect, send a request for a slow endpoint, then slam the
socket shut before the response comes back. The server must survive it silently.
"""

import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795
HOST = "127.0.0.1"
SLOW = "/api/router/status"          # reaches out to OmniRoute, so it takes seconds


def wait_for_health(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


env = dict(os.environ)
env["ELORA_DASHBOARD_LOG"] = "1"

server = subprocess.Popen(
    [sys.executable, "-u", "-m", "elora.dashboard.server", "--port", str(PORT)],
    cwd=ROOT, env=env,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)

try:
    if not wait_for_health():
        print("server never came up")
        raise SystemExit(2)

    # Send the request, then reset the connection immediately. SO_LINGER 0 makes
    # close() emit an RST rather than an orderly FIN, which is what produces
    # WinError 10053 on the server's write.
    sock = socket.create_connection((HOST, PORT), timeout=5)
    sock.sendall(
        f"GET {SLOW} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n"
        f"X-ELORA-Client: dashboard\r\n\r\n".encode()
    )
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    sock.close()
    print(f"aborted a request to {SLOW}")

    # The handler is still talking to OmniRoute, so the write happens seconds later.
    time.sleep(8)

    # Prove the server is still alive and serving after the abuse.
    with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=5) as response:
        alive = response.status == 200
finally:
    server.terminate()
    try:
        output = server.communicate(timeout=15)[0] or ""
    except subprocess.TimeoutExpired:
        server.kill()
        output = server.communicate()[0] or ""

tracebacks = output.count("Traceback")
aborted = output.count("10053")
print(f"\nstill serving after the abort: {alive}")
print(f"tracebacks in the server's output: {tracebacks}")
print(f"'10053' mentions: {aborted}")
if output.strip():
    print("--- server output ---")
    print("\n".join(output.strip().splitlines()[:25]))

ok = alive and tracebacks == 0
print(f"\n{'PASS' if ok else 'FAIL'}  a cancelled request leaves no traceback")
raise SystemExit(0 if ok else 1)
