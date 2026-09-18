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
        self.conn.commit()

    def save_episode(self, content: str):
        self.conn.execute(
            "INSERT INTO episodes (ts, content) VALUES (?, ?)",
            (time.time(), content),
        )
        self.conn.commit()

    def get_recent_episodes(self, n: int = 5) -> List[str]:
        cur = self.conn.execute(
            "SELECT content FROM episodes ORDER BY id DESC LIMIT ?", (n,)
        )
        rows = cur.fetchall()
        return [r[0] for r in rows][::-1]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    return 0


if __name__ == "__main__":
    sys.exit(main())
