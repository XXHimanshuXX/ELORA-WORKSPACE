"""Count every prev_hash fork; check 2766 and post-2769 chain."""
import hashlib
import sqlite3

conn = sqlite3.connect(".elora/akashic.db")
rows = list(conn.execute(
    "SELECT seq, ts, organ, kind, message, payload, prev_hash, hash FROM events ORDER BY seq"
))
print("n", len(rows))
forks = []
prev = "GENESIS"
prev_seq = None
for seq, ts, organ, kind, message, payload, stored_prev, digest in rows:
    if stored_prev != prev:
        forks.append((seq, organ, kind, "parent_seq_expected", prev_seq, "got_prev", stored_prev[:12], "had", prev[:12]))
    computed = hashlib.sha256(
        f"{stored_prev}{organ}{kind}{message}{payload}{ts}".encode()
    ).hexdigest()
    digest_ok = computed == digest
    if not digest_ok:
        forks.append((seq, organ, kind, "digest_mismatch"))
    prev = digest
    prev_seq = seq
print("anomalies", len(forks))
for f in forks[:30]:
    print(" ", f)

r2766 = conn.execute("SELECT seq, hash FROM events WHERE seq=2766").fetchone()
print("2766", r2766)

# verify skipping 2767-2768
prev = "GENESIS"
bad = None
for seq, ts, organ, kind, message, payload, stored_prev, digest in rows:
    if seq in (2767, 2768):
        continue
    if stored_prev != prev:
        bad = (seq, organ, kind)
        break
    computed = hashlib.sha256(
        f"{prev}{organ}{kind}{message}{payload}{ts}".encode()
    ).hexdigest()
    if computed != digest:
        bad = (seq, "digest", organ)
        break
    prev = digest
print("skip_2767_2768", "ok" if bad is None else bad)

# verify prefix through 2768 only
prev = "GENESIS"
bad = None
for seq, ts, organ, kind, message, payload, stored_prev, digest in rows:
    if seq > 2768:
        break
    if stored_prev != prev:
        bad = seq
        break
    computed = hashlib.sha256(
        f"{prev}{organ}{kind}{message}{payload}{ts}".encode()
    ).hexdigest()
    if computed != digest:
        bad = ("digest", seq)
        break
    prev = digest
print("prefix_to_2768", "ok" if bad is None else bad)
