"""Personal sandbox — glob, dry tests, marketplace. No nested live pytest."""

import os

from elora.core.capabilities import CAPABILITY_ALIASES, REGISTRY
from elora.slime import sandbox


def test_aliases_point_at_sandbox():
    assert CAPABILITY_ALIASES["pytest"] == "sandbox.test"
    assert CAPABILITY_ALIASES["glob"] == "sandbox.glob"
    assert CAPABILITY_ALIASES["marketplace"] == "plugin.marketplace"


def test_glob_finds_this_file():
    res = sandbox.glob_files("test_sandbox.py", path="tools/tests")
    assert res["ok"] is True
    assert any(h.endswith("test_sandbox.py") for h in res["hits"])


def test_glob_exclusion_rules(tmp_path):
    # .elora output directories and pytest caches should be fully ignored by glob.
    elora_dir = tmp_path / ".elora" / "chat-history"
    elora_dir.mkdir(parents=True)
    (elora_dir / "dump.json").write_text("no", encoding="utf-8")
    (tmp_path / "file.py").write_text("", encoding="utf-8")
    res = sandbox.glob_files("*", path=str(tmp_path), root=str(tmp_path))
    joined = " ".join(res["hits"])
    assert "dump.json" not in joined
    assert "file.py" in joined


def test_glob_skips_secrets(tmp_path):
    secrets = tmp_path / ".elora" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "github_token").write_text("nope", encoding="utf-8")
    (tmp_path / "ok.py").write_text("x=1\n", encoding="utf-8")
    res = sandbox.glob_files("*", path=str(tmp_path), root=str(tmp_path))
    assert res["ok"] is True
    joined = " ".join(res["hits"]).lower()
    assert "github_token" not in joined
    assert any(h.endswith("ok.py") for h in res["hits"])


def test_run_tests_dry(monkeypatch):
    monkeypatch.setenv("ELORA_SANDBOX", "dry")
    res = sandbox.run_tests("tools/tests")
    assert res["ok"] is True
    assert res["dry"] is True
    assert res["argv"][1:3] == ["-m", "pytest"]


def test_marketplace_does_not_invent_packages():
    res = sandbox.marketplace()
    assert res["ok"] is True
    names = {row["name"] for row in res["servers"]}
    assert res["closed"] is True
    assert names == {"git", "sandbox", "ledger", "core"}
    from elora.core.mcp_client import DEFAULT_SERVERS
    assert all(spec.command != "npx" for spec in DEFAULT_SERVERS.values())
    assert res["note"]


def test_sandbox_organs_registered():
    for name in ("sandbox.glob", "sandbox.test", "sandbox.check", "sandbox.status", "plugin.marketplace"):
        assert name in REGISTRY
