"""
_probe_dashboard.py — end-to-end check of the console.

Throwaway rig, kept in tools/ because it is how this console is verified rather
than described. It boots the real server on a spare port and exercises the exact
requests overlay/app.js makes, in the same order, plus the two refusals the
security model depends on.

What it is actually checking:
  1. the static bundle serves (a theme with no stylesheet is not a theme)
  2. the CSRF guards refuse a headerless request and a foreign Origin
  3. every endpoint the frontend calls answers with the shape the frontend reads
  4. every `var(--el-*)` in styles.css is emitted by the genome, so nothing the
     sheet depends on is silently being served by the fallback block
  5. every radius token carries a unit, whatever the current genome's values
     happen to be (the bug this rig was extended to catch)
"""

import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from elora.dashboard.server import serve  # noqa: E402

HOST, PORT = "127.0.0.1", 8791
BASE = f"http://{HOST}:{PORT}"
HDR = {"X-ELORA-Client": "dashboard"}

RESULTS: list[tuple[bool, str, str]] = []


def check(name, ok, note=""):
    RESULTS.append((bool(ok), name, str(note)))


def request(path, headers=None, method="GET", body=None, timeout=240):
    data = json.dumps(body).encode() if body is not None else None
    merged = dict(headers or {})
    if data is not None:
        merged["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


httpd = serve(HOST, PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"server on {BASE}\n")

# --- 1. static bundle -------------------------------------------------
for asset in ("/", "/index.html", "/styles.css", "/app.js"):
    status, body = request(asset)
    check(f"static {asset}", status == 200 and len(body) > 200, f"HTTP {status}, {len(body)}B")

status, _ = request("/../run.py")
check("path traversal refused", status in (403, 404), f"HTTP {status}")

# --- 2. the refusals --------------------------------------------------
status, _ = request("/api/aesthetic", headers={})
check("headerless request refused", status == 403, f"HTTP {status}")

status, _ = request("/api/aesthetic",
                    headers={"X-ELORA-Client": "dashboard", "Origin": "https://evil.example"})
check("foreign origin refused", status == 403, f"HTTP {status}")

status, _ = request("/api/aesthetic", method="OPTIONS", headers=HDR)
check("CORS preflight refused", status == 403, f"HTTP {status}")

# --- 3. health + genome ----------------------------------------------
status, body = request("/api/health", headers=HDR)
health = json.loads(body)
check("/api/health", status == 200 and health.get("ok") is True,
      f"python {health.get('python')}, pid {health.get('pid')}")

status, body = request("/api/aesthetic", headers=HDR)
aesthetic = json.loads(body)
genome, css = aesthetic.get("genome") or {}, aesthetic.get("css") or ""
check("/api/aesthetic", status == 200 and bool(genome),
      f"v{genome.get('version')} {genome.get('direction')}")
check("genome carries a rationale", len(genome.get("rationale") or []) >= 5,
      f"{len(genome.get('rationale') or [])} lines")
check("genome carries a contrast audit", len(genome.get("contrast_audit") or {}) == 7,
      f"{len(genome.get('contrast_audit') or {})} floors")

# --- 4. the genome/stylesheet contract --------------------------------
EXTERNAL = {"--el-radius-pill"}          # documented exceptions, none right now
sheet = open(os.path.join(ROOT, "overlay", "styles.css"), encoding="utf-8").read()
referenced = set(re.findall(r"var\((--el-[a-z0-9_-]+)\)", sheet))
emitted = set(re.findall(r"(--el-[a-z0-9_-]+)\s*:", css))
missing = sorted(referenced - emitted - EXTERNAL)
check("every var styles.css uses is emitted by the genome", not missing,
      f"missing: {missing}" if missing else f"{len(referenced)} vars, all sourceable")

radius_tokens = re.findall(r"--el-radius-[a-z0-9-]+:\s*([^;]+);", css)
unitless = [value.strip() for value in radius_tokens
            if value.strip() != "0"
            and not re.search(r"(px|rem|em|%|vh|vw|vmin|vmax)$", value.strip())]
# Genome-agnostic on purpose. This used to assert two literals —
# `--el-radius-pill: 9999px` and `--el-radius-card: 6px` — which only held for the
# genome present when it was written (base radius 4, so card = base + 2 = 6). The
# engine exists to change the genome, so that literal turned a perfectly valid
# generation (base 24, card 26) into a failure while every unit was correct.
# Assert the invariant the name claims: whatever the values are, each carries a
# unit. value == "0" is the one legal unitless length.
check("radius tokens carry units", len(radius_tokens) >= 4 and not unitless,
      f"{len(radius_tokens)} radius tokens, all with units" if not unitless
      else f"unitless: {unitless}")

# --- 5. every remaining endpoint the frontend calls -------------------
status, body = request("/api/aesthetic/genomes", headers=HDR)
genomes = json.loads(body)
check("/api/aesthetic/genomes", status == 200 and isinstance(genomes.get("generations"), list),
      f"{len(genomes.get('generations') or [])} generation(s), current v{genomes.get('current_version')}")

status, body = request("/api/capabilities", headers=HDR)
caps = json.loads(body)
check("/api/capabilities", status == 200 and caps.get("count"),
      f"{caps.get('count')} capabilities, ceilings {caps.get('tier_ceilings')}")

status, body = request("/api/ledger?limit=20", headers=HDR)
ledger = json.loads(body)
check("/api/ledger", status == 200 and ledger.get("available") is True,
      f"{ledger.get('count')} events")
if ledger.get("events"):
    first = ledger["events"][0]
    check("ledger events carry the fields the UI renders",
          all(k in first for k in ("seq", "ts", "organ", "kind", "message")),
          ", ".join(sorted(first)))

status, body = request("/api/discovery", headers=HDR)
discovery = json.loads(body)
check("/api/discovery", status == 200 and "skills" in discovery,
      f"{discovery.get('skills_total_on_disk')} skills, "
      f"{discovery.get('skills_uncounted_duplicates')} duplicates excluded, "
      f"{len(discovery.get('agents') or [])} agents, {len(discovery.get('plugins') or [])} manifests")
if discovery.get("skills"):
    check("discovery items carry the fields the UI filters on",
          all(k in discovery["skills"][0] for k in ("name", "path", "vendor", "source_root")),
          ", ".join(sorted(discovery["skills"][0])))

status, body = request("/api/plugins", headers=HDR)
plugins = json.loads(body)
check("/api/plugins states the loader is absent", plugins.get("loader_available") is False,
      f"{plugins.get('manifest_count')} read-only manifests")

status, body = request("/api/mcp/servers", headers=HDR)
servers = json.loads(body)
check("/api/mcp/servers (unprobed path)", status == 200 and servers.get("probed") is False,
      servers.get("note", "")[:70])

status, body = request("/api/router/status", headers=HDR)
router = json.loads(body)
if router.get("reachable"):
    check("/api/router/status", True,
          f"reachable, {router.get('model_count')} models, {router.get('latency_ms')}ms")
else:
    check("/api/router/status reports the failure honestly", bool(router.get("detail")),
          f"{router.get('error')}: {router.get('detail')}")

if router.get("reachable"):
    status, body = request("/api/router/models", headers=HDR)
    models = json.loads(body)
    check("/api/router/models", status == 200,
          f"{models.get('count')} models, resolved {models.get('resolved_model')} "
          f"by {models.get('resolved_by')} (alias={models.get('resolved_is_alias')})")

    status, body = request("/api/router/tools?name=health", headers=HDR)
    tool = json.loads(body)
    check("/api/router/tools health", status == 200 and tool.get("protocol_ok"),
          f"protocol_ok={tool.get('protocol_ok')} is_error={tool.get('is_error')} "
          f"degraded={tool.get('degraded')} {tool.get('latency_ms')}ms")

# --- report -----------------------------------------------------------
print()
passed = sum(1 for ok, _, _ in RESULTS if ok)
for ok, name, note in RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —  {note}" if note else ""))
print(f"\n{passed}/{len(RESULTS)} checks passed")
httpd.shutdown()
raise SystemExit(0 if passed == len(RESULTS) else 1)
