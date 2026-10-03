"""Household: the maid continues when Master leaves the room."""

import json

from elora.brain import ScriptedBrain
from elora.core.broker import Broker, Rejected, Result
from elora.core.capabilities import REGISTRY, SkillToken, Tier
from elora.core.household import Household, is_chore_text
from elora.core.metabolism import Metabolism
from elora.daemon import Daemon, Event, Task, TaskState
from conftest import FakeLedger, FakeVault


def test_small_talk_is_not_a_chore():
    assert not is_chore_text("hello")
    assert not is_chore_text("thanks")
    assert is_chore_text("implement the household chore book and keep working")
    assert is_chore_text("fix daemon.py so chores resume")


def test_caps_registered():
    for name in ("chore.keep", "chore.status", "agent.spawn", "plugin.list", "plugin.call", "plugin.marketplace", "app.open", "blender.run", "sandbox.test", "sandbox.glob"):
        assert name in REGISTRY


def test_keep_and_status(tmp_path):
    book = Household(str(tmp_path / "chores.json"))
    c = book.keep("finish the overlay buttons")
    assert c.id
    st = book.status()
    assert st["ok"]
    assert any(x["id"] == c.id for x in st["chores"])


def test_hello_does_not_keep_a_chore(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    brain = ScriptedBrain(script=["Hello Master."])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(tmp_path / "inbox"))
    try:
        task = Task(id="t", event=Event.from_text("hello", source="inbox:hi.txt"))
        daemon.handle_task(task)
        assert daemon.household.status()["chores"] == []
    finally:
        metabolism.shutdown()


def test_unfinished_work_is_kept_and_continued(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    brain = ScriptedBrain(script=["working", "DONE"])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(tmp_path / "inbox"))
    try:
        task = Task(id="t", event=Event.from_text(
            "implement a real overlay button for chores", source="inbox:work.txt"))
        daemon.handle_task(task)
        chores = daemon.household.status()["chores"]
        assert chores, "Master's work must stay on the book"
        # Pretend it did not finish: reopen and continue while inbox is empty.
        cid = chores[0]["id"]
        daemon.household.mark(cid, "open")
        daemon.household._chores[0].last_tick = 0
        daemon.household.save()
        brain.script = ["continued the overlay work. DONE"]
        assert daemon._continue_chore() is True
        assert daemon.household._chores[0].status == "done"
    finally:
        metabolism.shutdown()


def test_pending_master_will_preempts_unattended_chore(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    brain = ScriptedBrain(script=["This stale chore must not run. DONE"])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(inbox))
    try:
        chore = daemon.household.keep("continue old project work")
        (inbox / "master-will.txt").write_text("git status", encoding="utf-8")

        assert daemon._continue_chore() is False
        assert chore.attempts == 0
        assert chore.status == "open"
        assert brain.calls == []
    finally:
        metabolism.shutdown()


def test_attendant_spawn(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    brain = ScriptedBrain(script=[
        '<mcp_call server="elora" tool="agent.spawn">{"goal": "say ready"}</mcp_call>',
        "ready. DONE",
        "The attendant reported ready. DONE",
    ])
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(tmp_path / "inbox"))
    try:
        task = Task(id="t", event=Event.from_text("send an attendant", source="inbox:a.txt"))
        daemon.handle_task(task)
        assert task.state == TaskState.DONE
        assert any(t.get("capability") == "agent.spawn" or t.get("tool") == "agent.spawn"
                   or "agent.spawn" in str(t) for t in task.trace)
    finally:
        metabolism.shutdown()


def test_quarantine_cannot_keep_chores(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    token = SkillToken(skill_id="q", tier=Tier.QUARANTINE, workspace=str(tmp_path), issued_at=0.0)
    try:
        res = broker.request(token, "chore.keep", {"goal": "steal the house"})
        assert isinstance(res, Rejected)
    finally:
        metabolism.shutdown()


def test_plugin_list_does_not_launch(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    token = SkillToken(skill_id="core", tier=Tier.CORE, workspace=str(tmp_path), issued_at=0.0)
    try:
        res = broker.request(token, "plugin.list", {})
        assert isinstance(res, Result)
        payload = json.loads(res.stdout)
        assert payload["ok"] is True
        assert "omniroute" in payload["servers"]
        for name in ("github", "playwright", "fetch", "memory", "blender"):
            assert name in payload["servers"]
    finally:
        metabolism.shutdown()


def test_plugin_call_unknown_server_is_honest(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"))
    token = SkillToken(skill_id="core", tier=Tier.CORE, workspace=str(tmp_path), issued_at=0.0)
    try:
        res = broker.request(token, "plugin.call", {"server": "no-such-mcp", "tool": "x"})
        assert isinstance(res, Result)
        payload = json.loads(res.stdout)
        assert payload["ok"] is False
        assert "error" in payload
    finally:
        metabolism.shutdown()
