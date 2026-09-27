"""Hands organ: list/read/search/edit/git — the IDE body, not a chat wrapper."""

import json
import os

from elora.core.broker import Broker, Rejected, Result
from elora.core.capabilities import REGISTRY, SkillToken, Tier
from elora.core.metabolism import Metabolism
from elora.core.owner_will import WORKSPACE_ROOT
from elora.slime.hands import code_edit, code_read, code_search, dispatch, ws_list
from conftest import FakeLedger, FakeVault


def test_hands_caps_are_registered():
    for name in ("ws.list", "code.read", "code.search", "code.edit",
                 "git.status", "git.diff", "git.commit"):
        assert name in REGISTRY


def test_ws_list_and_read_and_search(tmp_path):
    sample = tmp_path / "alpha.py"
    sample.write_text("def hello():\n    return 42\n", encoding="utf-8")
    listed = ws_list(".", root=str(tmp_path))
    assert listed["ok"]
    assert any(e["name"] == "alpha.py" for e in listed["entries"])
    read = code_read("alpha.py", root=str(tmp_path))
    assert read["ok"]
    assert "return 42" in read["content"]
    hits = code_search("hello", glob=".py", root=str(tmp_path))
    assert hits["ok"]
    assert hits["hits"]


def test_code_edit_unique_replace_and_secret_refuse(tmp_path):
    target = tmp_path / "beta.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")
    dup = code_edit("beta.py", old_string="x = 1", new_string="x = 2", root=str(tmp_path))
    assert not dup["ok"]
    target.write_text("x = 1\n", encoding="utf-8")
    ok = code_edit("beta.py", old_string="x = 1", new_string="x = 2", root=str(tmp_path))
    assert ok["ok"]
    assert target.read_text(encoding="utf-8") == "x = 2\n"
    secrets = tmp_path / ".elora" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "omniroute_api_key").write_text("nope", encoding="utf-8")
    refused = code_edit(
        os.path.join(".elora", "secrets", "omniroute_api_key"),
        content="stolen", root=str(tmp_path),
    )
    assert not refused["ok"]


def test_path_cannot_escape_root(tmp_path):
    res = dispatch("code.read", {"path": "../outside.py"}, root=str(tmp_path))
    assert res["ok"] is False
    assert "escapes" in res["error"]


def test_broker_core_can_search_workspace(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"))
    token = SkillToken(skill_id="core", tier=Tier.CORE, workspace=WORKSPACE_ROOT, issued_at=0.0)
    try:
        res = broker.request(token, "code.search", {"query": "class Daemon", "glob": "daemon.py"})
        assert isinstance(res, Result)
        payload = json.loads(res.stdout)
        assert payload["ok"] is True
        assert payload["hits"]
    finally:
        metabolism.shutdown()


def test_trusted_cannot_commit(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"))
    token = SkillToken(skill_id="t", tier=Tier.TRUSTED, workspace=str(tmp_path), issued_at=0.0)
    try:
        res = broker.request(token, "git.commit", {"message": "should fail"})
        assert isinstance(res, Rejected)
        assert "CORE" in res.reason
    finally:
        metabolism.shutdown()


def test_grep_alias_is_code_search(tmp_path):
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=FakeLedger(), vault=FakeVault(),
                    consent_dir=str(tmp_path / "consent"))
    token = SkillToken(skill_id="core", tier=Tier.CORE, workspace=WORKSPACE_ROOT, issued_at=0.0)
    try:
        res = broker.request(token, "grep", {"query": "MAX_ITERATIONS", "glob": "daemon.py"})
        assert isinstance(res, Result)
        payload = json.loads(res.stdout)
        assert payload["ok"] is True
    finally:
        metabolism.shutdown()
