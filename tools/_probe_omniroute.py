"""Throwaway: list OmniRoute models + test the exact alias run.py sends."""
import json
import pathlib
import urllib.error
import urllib.request

BASE = "http://localhost:20128"
KEY = pathlib.Path(".elora/secrets/omniroute_api_key").read_text(encoding="utf-8").strip()


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


status, body = call("/v1/models")
if status == 200:
    ids = [m["id"] for m in json.loads(body).get("data", [])]
    print(f"MODEL_IDS ({len(ids)}):", ids)
    print("HAS_BARE_auto:", "auto" in ids)

for alias in ("auto", "auto/best-coding"):
    st, bd = call("/v1/chat/completions", {
        "model": alias,
        "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
        "stream": False,
    })
    print(f"--- chat model={alias!r} -> status {st}")
    print("    ", bd[:500].replace("\n", " "))
