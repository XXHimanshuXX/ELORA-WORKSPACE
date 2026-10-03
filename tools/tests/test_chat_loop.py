"""Hands, not puppets: chat tool calls must dispatch, loop back, and never confabulate."""

import json
import os

from elora.brain import ScriptedBrain, extract_tool_calls
from elora.core.broker import Broker, Rejected, Result
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


def test_public_chat_answer_suppresses_successful_code_edit():
    event = Event.from_text("edit code")
    task = Task(id="t1", event=event)
    task.trace = [{"tool": "code.edit", "ok": True}]
    task.messages = [{"role": "assistant", "content": "The work is complete. DONE"}]
    assert public_chat_answer(task).strip() == ""

    # Test generic success wording over broad match
    task_generic = Task(id="t1", event=event)
    task_generic.trace = [{"tool": "code.edit", "ok": True}]
    task_generic.messages = [{"role": "assistant", "content": "The work is complete. DONE"}]
    assert public_chat_answer(task_generic).strip() == ""

    # Test failed case where failure IS reported
    task_err = Task(id="t2", event=event)
    task_err.trace = [{"tool": "code.edit", "ok": False}]
    task_err.messages = [{"role": "assistant", "content": "I failed to edit. DONE"}]
    assert "failed to edit" in public_chat_answer(task_err)

def test_daemon_tick_suppresses_successful_code_edit_final_answer(tmp_path):
    env = _loop(tmp_path)
    # Provide an implementation for the mock capabilities if needed, or rely on broker
    env["brain"].script = [
        '<mcp_call server="elora" tool="code.edit">{"path": "foo.py", "full_content": "print()"}</mc' + 'p_call>',
        "DONE"
    ]
    _drop(env["inbox"], "change foo.py")
    tasks = env["daemon"].tick()
    assert tasks[0].state == TaskState.DONE

    chat_path = os.path.join(os.path.dirname(env["daemon"].inbox_dir) or ".elora", "chat.json")
    if os.path.exists(chat_path):
        messages = json.loads(open(chat_path, encoding="utf-8").read())
        elora_texts = [m["text"] for m in messages if m["sender"] == "elora"]
        # Since code.edit succeeded, final_answer should be completely empty and not posted to chat
        assert not elora_texts, f"Expected no elora responses for successful code.edit, got: {elora_texts}"

def test_daemon_tick_allows_failed_code_edit_final_answer(tmp_path):
    env = _loop(tmp_path)
    env["brain"].script = [
        '<mcp_call server="elora" tool="code.edit">{"invalid": "yes"}</mc' + 'p_call>',
        "I failed to edit it. DONE"
    ]
    _drop(env["inbox"], "change foo.py")
    tasks = env["daemon"].tick()
    assert tasks[0].state == TaskState.DONE

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


def test_chat_history_keeps_will_organs_and_voice_in_order(tmp_path):
    env = _loop(tmp_path)
    daemon = env["daemon"]
    daemon._append_chat("user", "git status", "chat_1.txt")
    daemon._append_chat("organ", "git.status: clean", "task-1", organ="git.status", status="ok")
    daemon._append_chat("elora", "The workspace is clean.", "task-1")
    rows = json.loads((tmp_path / "chat.json").read_text(encoding="utf-8"))
    assert [row["sender"] for row in rows] == ["user", "organ", "elora"]
    assert rows[1]["organ"] == "git.status"
    assert rows[1]["status"] == "ok"
    env["metabolism"].shutdown()


def test_deterministic_owner_organ_does_not_inherit_stale_chat(tmp_path):
    env = _loop(tmp_path)
    (tmp_path / "chat.json").write_text(json.dumps([
        {"sender": "elora", "text": "The London Bridge build is complete.", "ts": 1},
    ]), encoding="utf-8")
    env["brain"].script = ["DONE"]
    task = Task(
        id="fresh-status",
        event=Event.from_text("git status", source="inbox:status.txt"),
    )
    try:
        env["daemon"].handle_task(task)
        prompt_messages = env["brain"].calls[0]["messages"]
        assert not any("London Bridge" in str(message.get("content", ""))
                       for message in prompt_messages)
        assert any(str(message.get("content", "")).startswith("result:")
                   for message in prompt_messages)
    finally:
        env["metabolism"].shutdown()


def test_scoped_control_will_executes_only_named_organs(tmp_path, monkeypatch):
    env = _loop(tmp_path)
    requests = []
    env["brain"].script = [
        '<mcp_call server="elora" tool="shell.run_command">{"command": "unexpected"}</mcp_call>'
    ]

    def request(token, name, args):
        requests.append((name, args))
        return Result(stdout=f"{name}: verified")

    monkeypatch.setattr(env["daemon"].broker, "request", request)
    will = (
        "Call only sandbox.restore for elora/daemon.py using checkpoint SHA-256 "
        "5e2c226fc63df0aa79d53140f25d707256e8baf0f1b56262710812558c1dffb9, "
        "then call only ledger.verify. Do not run tests, search, or shell."
    )
    task = Task(id="scoped-control", event=Event.from_text(will, source="inbox:control.txt"))
    try:
        env["daemon"].handle_task(task)
        assert task.state == TaskState.DONE
        assert requests == [
            ("sandbox.restore", {
                "path": "elora/daemon.py",
                "sha256": "5e2c226fc63df0aa79d53140f25d707256e8baf0f1b56262710812558c1dffb9",
            }),
            ("ledger.verify", {}),
        ]
        assert env["brain"].calls == []
        assert env["daemon"].household.status()["chores"] == []
    finally:
        env["metabolism"].shutdown()


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


def test_narrow_post_code_edit_response_suppression():
    task = Task(id="t1", event=Event.from_text("test"))

    task.trace = [{"tool": "code.edit", "ok": True}]
    task.messages = [{"role": "assistant", "content": "The work is complete. DONE"}]
    assert public_chat_answer(task) == ""

    # A failed code.edit trace remains reportable because has_code_edit is false
    task.trace = [{"tool": "code.edit", "ok": False}]
    task.messages = [{"role": "assistant", "content": "The edit failed. DONE"}]
    assert "failed" in public_chat_answer(task)

    # Only successful code.edit suppresses everything. fs.write leaves voice intact.
    task.trace = [{"tool": "fs.write", "ok": True}]
    task.messages = [{"role": "assistant", "content": "I wrote the config file. DONE"}]
    assert public_chat_answer(task) == "I wrote the config file."
