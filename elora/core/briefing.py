"""
briefing.py — Daily Briefing generator for ELORA Resident.

Synthesizes recent ledger events and vault episodes into an honest summary:
"Since 19:00 yesterday: read N pages, ingested M docs, crystallized K skills."
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional


def generate_daily_briefing(ledger: Any, vault: Optional[Any] = None, hours: int = 24) -> dict[str, Any]:
    """
    Generates an honest daily briefing directly from ledger events and vault episodes.
    """
    pages_read = 0
    docs_ingested = 0
    skills_crystallized = 0
    tasks_completed = 0

    events = []
    if ledger is not None:
        if hasattr(ledger, "recent_events"):
            events = ledger.recent_events(n=1000)
        elif hasattr(ledger, "events"):
            events = getattr(ledger, "events", [])

    cutoff = time.time() - (hours * 3600)

    for event in events:
        ts = event.get("ts", 0)
        # If timestamp is provided and older than cutoff, skip; otherwise count
        if ts and ts < cutoff:
            continue

        organ = event.get("organ", "")
        kind = event.get("kind", "")

        if organ == "browser" and kind in ("read", "page_read"):
            pages_read += 1
        elif organ in ("rag", "doc", "absorb") and kind in ("ingest", "doc_ingested", "skill_absorbed"):
            docs_ingested += 1
        elif kind == "skill_crystallized":
            skills_crystallized += 1
        elif kind in ("task_finished", "task_done"):
            tasks_completed += 1

    time_str = "19:00 yesterday"
    summary = (
        f"Since {time_str}: read {pages_read} pages, "
        f"ingested {docs_ingested} docs, crystallized {skills_crystallized} skills."
    )

    return {
        "summary": summary,
        "pages_read": pages_read,
        "docs_ingested": docs_ingested,
        "skills_crystallized": skills_crystallized,
        "tasks_completed": tasks_completed,
        "events_count": len(events),
        "timestamp": time.time(),
    }
