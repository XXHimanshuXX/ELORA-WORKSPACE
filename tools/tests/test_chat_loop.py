"""Hands, not puppets: chat tool calls must dispatch, loop back, and never confabulate."""

import json
import os

from elora.brain import ScriptedBrain, extract_tool_calls
from elora.core.broker import Broker, Rejected
from elora.core.capabilities import SkillToken, Tier
from elora.core.metabolism import Metabolism
from elora.core.owner_will import WORKSPACE_ROOT
from elora.daemon import Daemon, Event, Task, TaskState, public_chat_answer
from conftest import FakeLedger, FakeVault


def _loop(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(
        metabolism=metabolism, ledger=ledger, vault=vault,
        consent_dir=str(tmp_path / "consent"), vault_root=str(tmp_path / "vault"),
    )
    brain = ScriptedBrain(script=[])
    daemon = Daemon(
        brain=brain, broker=broker, metabolism=metabolism,
        ledger=ledger, vault=vault, inbox_dir=str(inbox),
    )
    return {
        "daemon": daemon, "brain": brain, "ledger": ledger,
        "inbox": inbox, "metabolism": metabolism, "tmp": tmp_path,
    }


def _drop(inbox, text, name="task.txt"):
    (inbox / name).write_text(text, encoding="utf-8")


def test_extract_blender_sized_fs_write():
    payload = {
        "path": r"D:\Coding\ELORA-Workspace\london_bridge_script.py",
        "content": "import bpy\n\nbpy.ops.object.select_all(action='SELECT')\n",
    }
    reply = f'<mcp_call server="elora" tool="fs.write">{json.dumps(payload)}</mcp_call>'
    calls, failures = extract_tool_calls(reply)
    assert failures == []
    assert calls[0]["tool"] == "fs.write"
    assert "import bpy" in calls[0]["args"]["content"]


def test_chat_tool_call_is_dispatched(tmp_path):
    """A chat reply containing <mcp_call> must result in a capability_intent event."""
    env = _loop(tmp_path)
    dest = os.path.join(os.path.abspath(".elora"), "hands_dispatch.txt")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        os.remove(dest)
    body = json.dumps({"path": dest, "content": "hello-hands"})
    env["brain"].script = [
        f'<mcp_call server="elora" tool="fs.write">{body}</mcp_call>',
        "The file is on disk. DONE",
    ]
    _drop(env["inbox"], "write a marker file")
    try:
        tasks = env["daemon"].tick()
        assert tasks[0].state == TaskState.DONE
        kinds = [e["kind"] for e in env["ledger"].events]
        assert "capability_intent" in kinds
        assert any(e.get("message") == "fs.write" for e in env["ledger"].events if e["kind"] == "capability_intent")
        assert os.path.exists(dest)
        assert open(dest, encoding="utf-8").read() == "hello-hands"
        answer = public_chat_answer(tasks[0])
        assert "<mcp_call" not in answer
        assert "fs.write" not in answer or "The file is on disk" in answer
    finally:
        env["metabolism"].shutdown()
        if os.path.exists(dest):
            os.remove(dest)


def test_chat_loop_back_after_tool_call(tmp_path):
    """After a tool executes, the result is fed back and the brain is called again."""
    env = _loop(tmp_path)
    dest = os.path.join(os.path.abspath(".elora"), "hands_loopback.txt")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    body = json.dumps({"path": dest, "content": "loop"})
    env["brain"].script = [
        f'<mcp_call server="elora" tool="fs.write">{body}</mcp_call>',
        "Wrote it. DONE",
    ]
    _drop(env["inbox"], "write loop file")
    try:
        env["daemon"].tick()
        assert len(env["brain"].calls) >= 2
        second = env["brain"].calls[1]["messages"]
        assert any(str(m.get("content", "")).startswith("result:") for m in second)
    finally:
        env["metabolism"].shutdown()
        if os.path.exists(dest):
            os.remove(dest)


def test_hallucinated_action_is_impossible(tmp_path):
    """Claiming 'I checked/searched/opened' without a capability_intent cannot be the spoken reply."""
    env = _loop(tmp_path)
    env["brain"].script = [
        "I checked the running applications on your system and confirmed Blender is closed.",
        "DONE",
    ]
    _drop(env["inbox"], "is blender open")
    try:
        tasks = env["daemon"].tick()
        task = tasks[0]
        answer = public_chat_answer(task)
        assert "I checked the running applications" not in answer
        assert "<mcp_call" not in answer
        nudged = any("ANTI-V4" in str(m.get("content", "")) for m in task.messages)
        assert nudged
        intents = [e for e in env["ledger"].events if e["kind"] == "capability_intent"]
        assert intents == []
    finally:
        env["metabolism"].shutdown()


def test_core_can_write_workspace_file(tmp_path):
    env = _loop(tmp_path)
    dest = os.path.join(WORKSPACE_ROOT, "proof_owner_write.txt")
    token = env["daemon"].core_token
    assert token.tier == Tier.CORE
    try:
        res = env["daemon"].broker.request(token, "fs.write", {"path": dest, "content": "from-core"})
        assert not isinstance(res, Rejected)
        assert os.path.exists(dest)
        assert open(dest, encoding="utf-8").read() == "from-core"
    finally:
        env["metabolism"].shutdown()
        if os.path.exists(dest):
            os.remove(dest)


def test_quarantine_still_cannot_write_workspace(tmp_path):
    env = _loop(tmp_path)
    dest = os.path.join(WORKSPACE_ROOT, "proof_should_not_exist.txt")
    try:
        res = env["daemon"].broker.request(
            env["daemon"].skills_token, "fs.write",
            {"path": dest, "content": "nope"},
        )
        assert isinstance(res, Rejected)
        assert not os.path.exists(dest)
    finally:
        env["metabolism"].shutdown()
