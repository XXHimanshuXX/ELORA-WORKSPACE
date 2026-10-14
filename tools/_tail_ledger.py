import json
import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else ".elora/akashic.db"
conn = sqlite3.connect(db)
cur = conn.execute(
    "SELECT organ, kind, message, payload FROM events "
    "WHERE kind IN ('capability_intent','capability_result','task_finished','will_compiled') "
    "ORDER BY rowid DESC LIMIT 14"
)
rows = list(cur)
for organ, kind, message, payload in reversed(rows):
    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        data = {"raw": str(payload)[:200]}
    summary = {k: (str(v)[:120]) for k, v in list(data.items())[:6]}
    print(f"[{organ}] {kind}: {message}")
    print(f"    {summary}")
