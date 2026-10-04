"""Inspect akashic.db around first verify failure. No payload dumps."""
import hashlib
import json
import os
import sqlite3
import sys

path = os.path.join(".elora", "akashic.db")
print("db", os.path.abspath(path), "exists", os.path.isfile(path),
      "bytes", os.path.getsize(path) if os.path.isfile(path) else 0)
conn = sqlite3.connect(path)
n = conn.execute("SELECT COUNT(*), MIN(seq), MAX(seq) FROM events").fetchone()
print("count,min,max", n)
gaps = conn.execute(
    "SELECT a.seq+1 FROM events a WHERE NOT EXISTS (SELECT 1 FROM events b WHERE b.seq=a.seq+1) "
    "AND a.seq < (SELECT MAX(seq) FROM events) LIMIT 20"
).fetchall()
print("seq_gaps_after", [g[0] for g in gaps])

prev_hash = "GENESIS"
first = None
kind_fail = None
for seq, ts, organ, kind, message, payload_str, stored_prev, stored in conn.execute(
    "SELECT seq, ts, organ, kind, message, payload, prev_hash, hash FROM events ORDER BY seq"
):
    if stored_prev != prev_hash:
        first, kind_fail = seq, "prev_hash"
        break
    computed = hashlib.sha256(
        f"{prev_hash}{organ}{kind}{message}{payload_str}{ts}".encode()
    ).hexdigest()
    if computed != stored:
        first, kind_fail = seq, "digest"
        break
    prev_hash = stored

print("first_bad", first, "why", kind_fail)
if first is None:
    sys.exit(0)

rows = conn.execute(
    "SELECT seq, ts, organ, kind, length(message), length(payload), prev_hash, hash "
    "FROM events WHERE seq BETWEEN ? AND ? ORDER BY seq",
    (first - 2, first + 2),
).fetchall()
print("neighbors:")
for row in rows:
    print(" ", row)

seq, ts, organ, kind, message, payload_str, stored_prev, stored = conn.execute(
    "SELECT seq, ts, organ, kind, message, payload, prev_hash, hash FROM events WHERE seq=?",
    (first,),
).fetchone()
parent = conn.execute(
    "SELECT seq, hash FROM events WHERE seq=?", (first - 1,)
).fetchone()
print("parent", parent)
print("bad organ/kind", organ, kind, "msg_len", len(message), "ts", ts, type(ts), repr(ts)[:40])
print("stored_prev==parent", parent and stored_prev == parent[1])

alts = {}
parent_hash = parent[1] if parent else "GENESIS"
alts["current"] = hashlib.sha256(
    f"{parent_hash}{organ}{kind}{message}{payload_str}{ts}".encode()
).hexdigest()
alts["no_ts"] = hashlib.sha256(
    f"{parent_hash}{organ}{kind}{message}{payload_str}".encode()
).hexdigest()
try:
    dumped = json.dumps(json.loads(payload_str), sort_keys=True, default=str)
except Exception:
    dumped = payload_str
alts["roundtrip_payload"] = hashlib.sha256(
    f"{parent_hash}{organ}{kind}{message}{dumped}{ts}".encode()
).hexdigest()
alts["ts_repr"] = hashlib.sha256(
    f"{parent_hash}{organ}{kind}{message}{payload_str}{ts!r}".encode()
).hexdigest()
print("stored", stored)
for name, digest in alts.items():
    print(" alt", name, digest == stored, digest[:16])
print("payload_eq_roundtrip", dumped == payload_str)
