"""
household.py — the maid's chore book.

Claude/Codex look like hired developers because they keep working after
the chat tab closes, send workers, and pick up plugins. That is household
labor, not a contractor. ELORA is the resident maid: when Master leaves
the room, unfinished chores stay on the book and the daemon continues them.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

_SMALL_TALK = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|ok|okay|yes|no|good morning|good night)"
    r"[\s!.?]*$",
    re.I,
)
_CHORE_HINT = re.compile(
    r"\b(build|make|implement|fix|add|write|refactor|test|continue|open|connect|"
    r"create|install|wire|search|edit|commit|run|keep working|finish)\b",
    re.I,
)


@dataclass
class Chore:
    id: str
    goal: str
    status: str = "open"          # open | running | done | blocked
    source: str = ""
    attempts: int = 0
    last_tick: float = 0.0
    notes: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)


def is_chore_text(text: str) -> bool:
    """True when Master is assigning household work, not greeting the maid."""
    t = (text or "").strip()
    if not t or _SMALL_TALK.match(t):
        return False
    if _CHORE_HINT.search(t):
        return True
    return len(t) >= 80


class Household:
    MAX_ATTEMPTS = 8

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self._chores: list[Chore] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._chores = []
            return
        items = raw if isinstance(raw, list) else raw.get("chores", [])
        self._chores = [Chore(**{k: v for k, v in c.items() if k in Chore.__dataclass_fields__})
                        for c in items if isinstance(c, dict)]

    def save(self) -> None:
        payload = [asdict(c) for c in self._chores]
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, self.path)

    def keep(self, goal: str, source: str = "") -> Chore:
        goal = (goal or "").strip()
        for c in self._chores:
            if c.goal == goal and c.status in ("open", "running"):
                return c
        chore = Chore(id=uuid.uuid4().hex[:10], goal=goal, source=source)
        self._chores.append(chore)
        self.save()
        return chore

    def next_open(self) -> Chore | None:
        now = time.time()
        for c in self._chores:
            if c.status == "blocked" and c.attempts >= self.MAX_ATTEMPTS:
                continue
            if c.status in ("open", "running") and (now - c.last_tick) >= 1.0:
                return c
        return None

    def mark(self, chore_id: str, status: str, note: str = "") -> Chore | None:
        for c in self._chores:
            if c.id == chore_id:
                c.status = status
                if note:
                    c.notes.append(note[:800])
                    c.notes = c.notes[-8:]
                self.save()
                return c
        return None

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "chores": [
                {"id": c.id, "goal": c.goal[:200], "status": c.status,
                 "attempts": c.attempts}
                for c in self._chores[-20:]
            ],
        }

    def note_task(self, source: str, state_name: str, answer: str, goal: str = "") -> None:
        if source.startswith("inbox:chore:"):
            cid = source.split("inbox:chore:", 1)[-1]
            if state_name == "DONE":
                self.mark(cid, "done", answer)
            elif state_name == "FAILED":
                for c in self._chores:
                    if c.id == cid:
                        if c.attempts >= self.MAX_ATTEMPTS:
                            self.mark(cid, "blocked", answer or "failed")
                        else:
                            self.mark(cid, "open", answer)
                        return
            return
        if state_name == "DONE" and goal:
            for c in self._chores:
                if c.goal == goal and c.status in ("open", "running"):
                    self.mark(c.id, "done", answer)
                    return
