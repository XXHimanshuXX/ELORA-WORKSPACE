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
