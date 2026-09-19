"""
akashic.py — the hash-chained ledger.

Every heartbeat of the organism is an append-only event whose hash
commits the previous hash. Tamper anywhere and verify() fails; boot
halts with exit 2. There is no "plain INSERT".
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from typing import Any, Optional


class AkashicLedger:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                organ TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self._events: list[dict] = self._load_events()

    @property
    def events(self) -> list[dict]:
        return self._events

    def _load_events(self) -> list[dict]:
        cur = self.conn.execute(
            "SELECT seq, ts, organ, kind, message, payload, prev_hash, hash "
            "FROM events ORDER BY seq ASC"
        )
        out = []
        for row in cur.fetchall():
            seq, ts, organ, kind, message, payload, prev_hash, digest = row
            try:
                payload_obj = json.loads(payload)
            except json.JSONDecodeError:
                payload_obj = payload
            out.append({
                "seq": seq, "ts": ts, "organ": organ, "kind": kind,
                "message": message, "payload": payload_obj,
                "prev_hash": prev_hash, "hash": digest,
            })
        return out

    def _last_hash(self) -> str:
        cur = self.conn.execute(
            "SELECT hash FROM events ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else "GENESIS"

    def append(self, organ: str, kind: str, message: str,
               payload: Optional[Any] = None) -> str:
        ts = time.time()
        payload_str = json.dumps(payload if payload is not None else {},
                                 sort_keys=True, default=str)
        prev_hash = self._last_hash()
        digest = hashlib.sha256(
            f"{prev_hash}{organ}{kind}{message}{payload_str}{ts}".encode()
        ).hexdigest()
        self.conn.execute(
            "INSERT INTO events (ts, organ, kind, message, payload, prev_hash, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, organ, kind, message, payload_str, prev_hash, digest),
        )
        self.conn.commit()
        seq = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        rec = {
            "seq": seq, "ts": ts, "organ": organ, "kind": kind,
            "message": message, "payload": json.loads(payload_str),
            "prev_hash": prev_hash, "hash": digest,
        }
        self._events.append(rec)
        return digest

    def recent_events(self, kind: Optional[str] = None, n: int = 50) -> list[dict]:
        """Return the most recent events, optionally filtered by kind."""
        query = ("SELECT seq, ts, organ, kind, message, payload, prev_hash, hash "
                 "FROM events ")
        params: list[Any] = []
        if kind is not None:
            query += "WHERE kind = ? "
            params.append(kind)
        query += "ORDER BY seq DESC LIMIT ?"
        params.append(n)
        cur = self.conn.execute(query, tuple(params))
        out = []
        for row in cur.fetchall():
            seq, ts, organ, k, message, payload, prev_hash, digest = row
            try:
                payload_obj = json.loads(payload)
            except Exception:
                payload_obj = payload
            out.append({
                "seq": seq, "ts": ts, "organ": organ, "kind": k,
                "message": message, "payload": payload_obj,
                "prev_hash": prev_hash, "hash": digest,
            })
        return out[::-1]

    def verify(self):
        """
        Iterate the chain. Return (True, None) if intact, (False, seq)
        on the first tampered row. Boot MUST halt on False.
        """
        prev_hash = "GENESIS"
        cur = self.conn.execute(
            "SELECT seq, ts, organ, kind, message, payload, prev_hash, hash "
            "FROM events ORDER BY seq ASC"
        )
        for seq, ts, organ, kind, message, payload_str, stored_prev, stored in cur:
            if stored_prev != prev_hash:
                return False, seq
            computed = hashlib.sha256(
                f"{prev_hash}{organ}{kind}{message}{payload_str}{ts}".encode()
            ).hexdigest()
            if computed != stored:
                return False, seq
            prev_hash = stored
        return True, None


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--verify" in argv:
        path = os.environ.get("ELORA_AKASHIC", os.path.join(".elora", "akashic.db"))
        if not os.path.exists(path):
            print("no ledger")
            return 0
        ok, bad = AkashicLedger(path).verify()
        print("ok" if ok else f"tamper at {bad}")
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
