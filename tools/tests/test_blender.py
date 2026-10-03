"""Jailed blender.run — allowlist, jail, no shell, no live GUI in CI."""

import pytest

from elora.core.broker import Rejected
from elora.core.capabilities import REGISTRY, Tier
from elora.slime import blender as blender_organ


def test_blender_run_is_registered():
    cap = REGISTRY["blender.run"]
    assert cap.tier_required == Tier.TRUSTED


def test_script_outside_jail_refused(tmp_path):
    res = blender_organ.run_script(r"C:\Windows\System32\foo.py", work_dir=str(tmp_path))
    assert res["ok"] is False
    assert "jail" in res["error"]


def test_missing_script_refused(tmp_path):
    res = blender_organ.run_script("missing.py", work_dir=str(tmp_path))
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_secrets_path_refused(tmp_path):
    secrets = tmp_path / ".elora" / "secrets"
    secrets.mkdir(parents=True)
    evil = secrets / "steal.py"
    evil.write_text("print(1)\n", encoding="utf-8")
    res = blender_organ.run_script(str(evil), work_dir=str(tmp_path))
    assert res["ok"] is False
    assert "jail" in res["error"]


def test_dry_run_jailed_script(tmp_path, monkeypatch):
    script = tmp_path / "build_bridge.py"
    script.write_text("import bpy\n", encoding="utf-8")
    monkeypatch.setenv("ELORA_BLENDER_RUN", "dry")
    exe = __import__("elora.slime.computer_use", fromlist=["resolve_allowed_app"]).resolve_allowed_app("blender")
    if not exe:
        pytest.skip("blender not installed")
    res = blender_organ.run_script("build_bridge.py", work_dir=str(tmp_path), gui=True)
    assert res["ok"] is True
    assert res["dry"] is True
    assert res["script"] == str(script)
    assert "--python" in res["argv"]
    assert "-b" not in res["argv"]


def test_blender_is_a_default_mcp_server():
    from elora.core.mcp_client import DEFAULT_SERVERS
    spec = DEFAULT_SERVERS["blender"]
    assert spec.name == "blender"
    assert "-m" in spec.args
    assert "elora.core.blender_mcp" in spec.args


def test_blender_mcp_lists_tools():
    from elora.core.mcp_client import list_tools
    tools = list_tools("blender", timeout=8)
    names = {t["name"] for t in tools}
    assert names == {"ping", "get_scene_info", "execute_code", "run_script"}


def test_blender_mcp_execute_code_jail():
    from elora.core.blender_mcp import dispatch
    res = dispatch("execute_code", {"code": "import subprocess; subprocess.call(['calc'])"})
    assert res["isError"] is True
    assert "subprocess" in res["content"][0]["text"]


def test_blender_mcp_ping_dark_socket_is_honest():
    from elora.core.blender_mcp import dispatch
    res = dispatch("ping", {})
    text = res["content"][0]["text"]
    if res["isError"]:
        assert "socket" in text.lower() or "dark" in text.lower()
    else:
        assert "ok" in text.lower()


def test_quarantine_cannot_run_blender(broker, tmp_path):
    from conftest import token
    tok = token(Tier.QUARANTINE, str(tmp_path / "ws"))
    result = broker.request(tok, "blender.run", {"script": "build_bridge.py"})
    assert isinstance(result, Rejected)
    assert "tier" in result.reason.lower()
