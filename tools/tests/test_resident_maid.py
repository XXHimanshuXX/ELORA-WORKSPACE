"""
test_resident_maid.py — ELORA v7.3 Resident & Maid inspection rungs.

Verifies:
  1. test_chat_is_default_panel: The console defaults to the resident/chat front door.
  2. Resident language enters the inbox and the daemon records organ outcomes in the timeline.
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
from elora.organs.akashic import AkashicLedger
from elora.dashboard.server import (
    payload_organism_state,
    payload_perception,
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
    assert "id: 'house-still'" in app_js
    assert "/api/perception" in app_js


def test_resident_will_dispatches_to_inbox(tmp_path, monkeypatch):
    """The Resident has one language-first compose and persists wills into the inbox."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app_js = open(os.path.join(root, "overlay", "app.js"), encoding="utf-8").read()
    assert "h('textarea'" in app_js
    assert "event.key === 'Enter' && !event.shiftKey" in app_js
    assert "api('/api/inbox/task'" in app_js
    assert "quick-btn" not in app_js
    assert "clear(chatLog)" not in app_js
    assert "nothing spoken yet" in app_js
    assert "organMessage && state.organism) state.organism.ripple()" in app_js
    assert "SYSTEM QUEST" in app_js
    assert "[ORGAN: " in app_js

    # Test server inbox task dispatching
    state_dir = tmp_path / ".elora"
    state_dir.mkdir()
    monkeypatch.setattr("elora.dashboard.server.STATE_DIR", str(state_dir))
    monkeypatch.setattr("elora.dashboard.server.LEDGER_PATH", str(state_dir / "akashic.db"))
    AkashicLedger(str(state_dir / "akashic.db"))

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


def test_perception_absent_is_absent(tmp_path):
    res = payload_perception(str(tmp_path / "missing_state.json"))
    assert res["available"] is False
    assert "state.json absent" in res["reason"]
    state_file = tmp_path / "state.json"
    state_file.write_text("{}", encoding="utf-8")
    res = payload_perception(str(state_file))
    assert res["available"] is False
    assert "no still" in res["reason"]


def test_resident_language_is_not_a_capability_toolbar():
    """Actions are inferred from the will and the resident does not expose tool shortcuts."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app_js = open(os.path.join(root, "overlay", "app.js"), encoding="utf-8").read()
    assert "dispatchTask('read README.md" not in app_js
    assert "quickActions" not in app_js
    assert "execution_tier" in app_js


def test_infer_owner_organs_readme_and_urls():
    from elora.core.owner_will import infer_owner_organs, is_direct_control_will, is_owner_source

    calls = infer_owner_organs("read README.md and summarize it")
    assert calls == [("net.read", {"url": "README.md"})]
    calls = infer_owner_organs("read https://example.com and tell me what it was about")
    assert calls[0][0] == "net.read"
    assert calls[0][1]["url"].startswith("https://example.com")
    calls = infer_owner_organs("ingest tests/fixtures/sample.pdf")
    assert calls == [("doc.ingest", {"path": "tests/fixtures/sample.pdf"})]
    calls = infer_owner_organs("open chrome")
    assert ("app.open", {"app": "chrome"}) in calls
    calls = infer_owner_organs("run the tests")
    assert ("sandbox.test", {}) in calls
    assert infer_owner_organs("sandbox.test only tools/tests/test_chat_loop.py") == [
        ("sandbox.test", {"target": "tools/tests/test_chat_loop.py"})
    ]
    calls = infer_owner_organs("git status")
    assert ("git.status", {}) in calls
    assert ("sandbox.repo_map", {"query": "fix the overlay task flow"}) in infer_owner_organs("fix the overlay task flow")
    calls = infer_owner_organs("list plugins")
    assert ("plugin.list", {}) in calls
    calls = infer_owner_organs("open blender, connect to it, and build the London Bridge")
    assert ("app.open", {"app": "blender"}) in calls
    assert ("blender.run", {"script": "elora/slime/blender_connect.py"}) in calls
    assert ("plugin.call", {"server": "blender", "tool": "ping"}) in calls
    assert ("blender.run", {"script": "build_bridge.py"}) in calls

    bounded = (
        "Call only sandbox.restore for elora/daemon.py using checkpoint SHA-256 "
        "5e2c226fc63df0aa79d53140f25d707256e8baf0f1b56262710812558c1dffb9, "
        "then call only ledger.verify. Do not run tests, sandbox.check, search, "
        "open app, or shell."
    )
    assert infer_owner_organs(bounded) == [
        ("sandbox.restore", {
            "path": "elora/daemon.py",
            "sha256": "5e2c226fc63df0aa79d53140f25d707256e8baf0f1b56262710812558c1dffb9",
        }),
        ("ledger.verify", {}),
    ]
    assert is_direct_control_will(bounded)
    assert infer_owner_organs(
        "Do not run tests, git status/diff, plugins, marketplace, list files, "
        "search/grep, README, ledger, open app, screenshot, or Blender."
    ) == []
    assert is_owner_source("inbox:chat_1.txt") is True
    assert is_owner_source("drive:self_experiment") is False


def test_owner_readme_executes_net_read_at_core(tmp_path, monkeypatch):
    """Master's will is CORE. The body reads README.md without shell and without asking for a path."""
    from elora.brain import ScriptedBrain
    from elora.core.broker import Broker
    from elora.core.capabilities import Tier
    from elora.core.metabolism import Metabolism
    from elora.daemon import Daemon, Task, Event, TaskState
    from conftest import FakeLedger, FakeVault

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    brain = ScriptedBrain(script=["README describes ELORA OS. DONE"])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(inbox))
    try:
        task = Task(
            id="owner-readme",
            event=Event.from_text("read README.md and summarize it", source="inbox:chat_readme.txt"),
        )
        daemon.handle_task(task)
        assert task.state == TaskState.DONE
        assert daemon._token_for(task).tier == Tier.CORE
        ok_tools = [t.get("tool") for t in task.trace if t.get("ok")]
        assert "net.read" in ok_tools
        assert "shell.run_command" not in [t.get("tool") for t in task.trace]
        combined = " ".join(m.get("content", "") for m in task.messages)
        assert "result:" in combined
        assert "Please provide the absolute path" not in combined
    finally:
        metabolism.shutdown()


def test_drive_experiment_stays_quarantine(tmp_path):
    from elora.brain import ScriptedBrain
    from elora.core.broker import Broker
    from elora.core.capabilities import Tier
    from elora.core.metabolism import Metabolism
    from elora.daemon import Daemon, Task, Event
    from conftest import FakeLedger, FakeVault

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"))
    brain = ScriptedBrain(script=["DONE"])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(inbox))
    try:
        task = Task(
            id="exp",
            event=Event.from_text("Verify skill x self-check and reply with DONE",
                                  source="drive:self_experiment"),
        )
        assert daemon._token_for(task).tier == Tier.QUARANTINE
        daemon.handle_task(task)
        prompt = brain.calls[0]["system"] if brain.calls else ""
        assert "QUARANTINE EXPERIMENT LAW" in prompt
        assert "MASTER'S WILL LAW" not in prompt
    finally:
        metabolism.shutdown()


def test_browser_read_alias_is_net_read(tmp_path):
    from elora.core.broker import Broker, Result
    from elora.core.capabilities import SkillToken, Tier
    from elora.core.metabolism import Metabolism
    from conftest import FakeLedger, FakeVault

    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    token = SkillToken(skill_id="t", tier=Tier.CORE, workspace=str(tmp_path), issued_at=0.0)
    try:
        res = broker.request(token, "browser.read", {"url": "README.md"})
        assert isinstance(res, Result)
        assert "ELORA" in (res.stdout or "") or "content" in (res.stdout or "")
    finally:
        metabolism.shutdown()
