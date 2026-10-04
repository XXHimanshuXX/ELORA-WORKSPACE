"""Backup, drop the forked sibling pair 2767-2768, verify. One-shot."""
import os
import sqlite3
import sys
import time

from elora.organs.akashic import AkashicLedger

ROOT = os.path.abspath(".")
DB = os.path.join(ROOT, ".elora", "akashic.db")
BACKUP_DIR = os.path.join(ROOT, ".elora", "backup")
BACKUP = os.path.join(BACKUP_DIR, "akashic.pre-repair-2769.db")

os.makedirs(BACKUP_DIR, exist_ok=True)
src = sqlite3.connect(DB)
dst = sqlite3.connect(BACKUP)
with dst:
    src.backup(dst)
dst.close()
print("backup", BACKUP, os.path.getsize(BACKUP))

src.execute("BEGIN IMMEDIATE")
cur = src.execute("SELECT seq, organ, kind FROM events WHERE seq IN (2767, 2768)")
rows = cur.fetchall()
print("deleting", rows)
if rows != [(2767, "broker", "capability_intent"), (2768, "broker", "capability_result")]:
    src.rollback()
    src.close()
    print("REFUSE: rows are not the expected fork pair")
    sys.exit(2)
src.execute("DELETE FROM events WHERE seq IN (2767, 2768)")
src.commit()
src.close()

ledger = AkashicLedger(DB)
ok, bad = ledger.verify()
print("verify", ok, bad)
if not ok:
    sys.exit(2)
ledger.append(
    organ="akashic",
    kind="chain_repair",
    message="removed forked sibling seq 2767-2768 (concurrent inbox vs broker); restored linear chain",
    payload={"dropped": [2767, 2768], "first_bad_was": 2769, "backup": BACKUP},
)
ok, bad = ledger.verify()
print("verify_after_append", ok, bad)
ledger.conn.close()
sys.exit(0 if ok else 2)
