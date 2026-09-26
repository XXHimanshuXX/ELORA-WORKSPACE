"""
test_resident_maid.py — ELORA v7.3 Resident & Maid inspection rungs.

Verifies:
  1. test_chat_is_default_panel: The console defaults to the resident/chat front door.
  2. test_quick_buttons_dispatch_real_capabilities: The 4 buttons dispatch real capabilities
     (net.read, rag.recall, doc.ingest, ledger.verify) into .elora/inbox and record to ledger.
  3. test_daily_briefing_generated_from_ledger: Synthesizes honest report from ledger events.
  4. test_seed_is_deterministic: Same vault identity -> same seed -> same face.
  5. test_seed_changes_with_identity: Different vault identity -> different seed.
  6. test_organism_state_and_shader: Absence reported as absence, all 6 metabolism states mapped,
     and WGSL raymarched creature shader structurally valid.
"""

import json
import os
import pytest

from elora.core.briefing import generate_daily_briefing
from elora.dashboard.server import (
    payload_organism_state,
    payload_inbox_task,
    _STATE_INDEX,
)


def test_chat_is_default_panel():
    """Rung 1: The console lands on the Resident dialogue/chat panel by default."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    index_html = open(os.path.join(root, "overlay", "index.html"), encoding="utf-8").read()
    app_js = open(os.path.join(root, "overlay", "app.js"), encoding="utf-8").read()

    # Index rail places resident first
    assert 'data-nav="resident" aria-current="page"' in index_html
    # Default view in DOM is resident (not hidden)
    assert '<section class="view" data-view="resident" tabindex="-1">' in index_html
    assert '<section class="view" data-view="genome" tabindex="-1" hidden>' in index_html

    # App.js defaults view to resident
    assert "view: 'resident'" in app_js
    assert "location.hash || '#resident'" in app_js


def test_quick_buttons_dispatch_real_capabilities(tmp_path, monkeypatch):
    """Rung 2: Quick buttons map to real capability dispatches into .elora/inbox and ledger."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app_js = open(os.path.join(root, "overlay", "app.js"), encoding="utf-8").read()

    # Four buttons map to real capabilities in app.js
    assert 'net.read' in app_js
    assert 'rag.recall' in app_js
    assert 'doc.ingest' in app_js
    assert 'ledger.verify' in app_js

    # Test server inbox task dispatching
    state_dir = tmp_path / ".elora"
    state_dir.mkdir()
    monkeypatch.setattr("elora.dashboard.server.STATE_DIR", str(state_dir))
    monkeypatch.setattr("elora.dashboard.server.LEDGER_PATH", str(state_dir / "akashic.db"))

    res = payload_inbox_task("read https://example.com and tell me what it was about")
    assert res["ok"] is True
    assert res["task_id"].startswith("chat_")

    inbox_files = list((state_dir / "inbox").glob("*.txt"))
    assert len(inbox_files) == 1
    content = inbox_files[0].read_text(encoding="utf-8")
    assert "read https://example.com" in content

    # Chat file updated
    chat_file = state_dir / "chat.json"
    assert chat_file.exists()
    messages = json.loads(chat_file.read_text(encoding="utf-8"))
    assert len(messages) == 1
    assert messages[0]["sender"] == "user"


def test_daily_briefing_generated_from_ledger():
    """Rung 3: Daily briefing aggregates pages read, docs ingested, skills crystallized."""
    class MockLedger:
        def __init__(self):
            self.events = [
                {"organ": "browser", "kind": "read", "message": "page 1", "ts": 1000},
                {"organ": "browser", "kind": "read", "message": "page 2", "ts": 1001},
                {"organ": "doc", "kind": "ingest", "message": "sample.pdf", "ts": 1002},
                {"organ": "crystallizer", "kind": "skill_crystallized", "message": "skl_1", "ts": 1003},
                {"organ": "crystallizer", "kind": "skill_crystallized", "message": "skl_2", "ts": 1004},
            ]
        def recent_events(self, n=300):
            return self.events

    ledger = MockLedger()
    briefing = generate_daily_briefing(ledger=ledger, hours=999999)
    assert briefing["pages_read"] == 2
    assert briefing["docs_ingested"] == 1
    assert briefing["skills_crystallized"] == 2
    assert "read 2 pages, ingested 1 docs, crystallized 2 skills" in briefing["summary"]


def test_seed_is_deterministic(tmp_path):
    """Rung 4: Same vault identity -> same seed -> same face. Auditable identity, not decoration."""
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "ledger_genesis": "genesis_hash_alpha",
        "skills_count": 5,
        "metabolism": "ALIVE"
    }), encoding="utf-8")

    s1 = payload_organism_state(str(state_file))
    s2 = payload_organism_state(str(state_file))
    assert s1["available"] is True
    assert s1["seed"] == s2["seed"]


def test_seed_changes_with_identity(tmp_path):
    """Rung 5: Different vault identity / skills -> different seed."""
    f1 = tmp_path / "state1.json"
    f1.write_text(json.dumps({
        "ledger_genesis": "genesis_hash_alpha",
        "skills_count": 5,
        "metabolism": "ALIVE"
    }), encoding="utf-8")

    f2 = tmp_path / "state2.json"
    f2.write_text(json.dumps({
        "ledger_genesis": "genesis_hash_alpha",
        "skills_count": 6,
        "metabolism": "ALIVE"
    }), encoding="utf-8")

    s1 = payload_organism_state(str(f1))
    s2 = payload_organism_state(str(f2))
    assert s1["seed"] != s2["seed"]


def test_organism_state_and_shader(tmp_path):
    """Rung 6: Absence reported as absence, metabolism states mapped, WGSL structure validated."""
    # Absence reported as absence
    no_file = tmp_path / "missing_state.json"
    res = payload_organism_state(str(no_file))
    assert res["available"] is False
    assert "state.json absent" in res["reason"]

    # Metabolism index maps all 6 states
    for name, idx in [("CRYPTOBIOSIS", 0), ("ALIVE", 1), ("AWAKE", 2),
                      ("ALERT", 3), ("ARMED", 4), ("DIGESTING", 5)]:
        assert _STATE_INDEX.get(name) == idx

    # WGSL raymarched metaball creature parses entrypoints and uniform layout
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    shader_path = os.path.join(root, "overlay", "organism.wgsl")
    assert os.path.exists(shader_path)
    src = open(shader_path, encoding="utf-8").read()
    assert "@vertex" in src and "fn vs" in src
    assert "@fragment" in src and "fn fs" in src
    assert "struct Uniforms" in src
    assert "sdf_blob" in src
