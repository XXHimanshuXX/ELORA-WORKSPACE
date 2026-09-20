"""
vault.py — episodic memory. Plain SQLite, no fernet, no theater.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from typing import List


class Vault:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                content TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS refused_nutrients (
                url_sha TEXT PRIMARY KEY,
                url TEXT,
                ts REAL,
                reason TEXT
            )
            """
        )
        self.conn.commit()

    def save_episode(self, content: str):
        self.conn.execute(
            "INSERT INTO episodes (ts, content) VALUES (?, ?)",
            (time.time(), content),
        )
        self.conn.commit()

    def count(self) -> int:
        cur = self.conn.execute("SELECT count(*) FROM episodes")
        row = cur.fetchone()
        return row[0] if row else 0

    def get_recent_episodes(self, n: int = 5) -> List[str]:
        cur = self.conn.execute(
            "SELECT content FROM episodes ORDER BY id DESC LIMIT ?", (n,)
        )
        rows = cur.fetchall()
        return [r[0] for r in rows][::-1]

    def record_refused_nutrient(self, url: str, reason: str = ""):
        import hashlib
        url_sha = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO refused_nutrients (url_sha, url, ts, reason)
            VALUES (?, ?, ?, ?)
            """,
            (url_sha, url.strip(), time.time(), reason),
        )
        self.conn.commit()

    def is_nutrient_refused(self, url: str, max_age_s: float = 7 * 86400) -> bool:
        import hashlib
        url_sha = hashlib.sha256(url.strip().encode("utf-8")).hexdigest()
        cur = self.conn.execute(
            "SELECT ts FROM refused_nutrients WHERE url_sha = ?",
            (url_sha,),
        )
        row = cur.fetchone()
        if not row:
            return False
        return (time.time() - row[0]) < max_age_s


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    path = os.environ.get("ELORA_VAULT", os.path.join(".elora", "vault.db"))
    v = Vault(path)
    if "--recall" in argv:
        idx = argv.index("--recall")
        n = int(argv[idx + 1]) if idx + 1 < len(argv) and argv[idx + 1].isdigit() else 5
        episodes = v.get_recent_episodes(n)
        for ep in episodes:
            print(ep)
        return 0
    elif "--save" in argv:
        idx = argv.index("--save")
        content = argv[idx + 1] if idx + 1 < len(argv) else ""
        v.save_episode(content)
        print("saved")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
