"""Acceptance checks for ELORA's Resident → organs → ledger control loop."""

import ast
import json
import os
from types import SimpleNamespace

import pytest

from elora.core.capabilities import SkillToken, Tier
from elora.core.broker import Result
from elora.core.owner_will import infer_owner_organs
from elora.dashboard import server
from elora.daemon import Daemon, Event, Task
from elora.organs.akashic import AkashicLedger
from elora.slime import control_plane, hands, sandbox


def test_infer_owner_organs_maps_implementation_before_model_and_respects_stop():
    calls = infer_owner_organs("Please fix the Resident timeline after inspecting the organ flow")
    assert calls and calls[0][0] == "sandbox.repo_map"
    assert infer_owner_organs("Stop making ELORA open Blender over and over again") == []


def test_repo_map_returns_workspace_symbols(tmp_path):
    (tmp_path / "module.py").write_text("def elora_acceptance_symbol():\n    return 1\n", encoding="utf-8")
    result = control_plane.repo_map("elora_acceptance_symbol", root=str(tmp_path))
    assert result["ok"] is True
    assert result["file_count"] > 0
    assert any("elora_acceptance_symbol" in item["symbols"] for item in result["files"])


def test_code_edit_fails_closed_when_snapshot_fails(tmp_path, monkeypatch):
    target = tmp_path / "module.py"
    target.write_text("before = True\n", encoding="utf-8")
    monkeypatch.setattr(control_plane, "snapshot_file", lambda *a, **k: {"ok": False, "error": "disk full"})
    result = hands.code_edit("module.py", content="after = True\n", root=str(tmp_path))
    assert result["ok"] is False
    assert "checkpoint failed" in result["error"]
    assert target.read_text(encoding="utf-8") == "before = True\n"


def test_diagnose_reports_unsupported_file_as_unverified(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("plain text", encoding="utf-8")
    result = control_plane.diagnose("notes.txt", root=str(tmp_path))
    assert result["ok"] is False
    assert result["lang"] == "opaque"
    assert result["note"] == "no syntax engine for this suffix"


def test_jailed_pytest_uses_subprocess_without_shell(tmp_path, monkeypatch):
    (tmp_path / "tools" / "tests").mkdir(parents=True)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.delenv("ELORA_SANDBOX", raising=False)
    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    result = sandbox.run_tests("tools/tests", root=str(tmp_path))
    assert result["ok"] is True
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[1:3] == ["-m", "pytest"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["shell"] is False


def test_closed_marketplace_has_only_first_party_organs_and_no_npx():
    result = sandbox.marketplace()
    assert result["ok"] is True and result["closed"] is True
    assert {item["name"] for item in result["servers"]} == {"git", "sandbox", "ledger", "core"}
    from elora.core.mcp_client import DEFAULT_SERVERS
    assert all(spec.command != "npx" for spec in DEFAULT_SERVERS.values())


def test_workspace_jail_and_secret_read_boundary(tmp_path):
    secret_dir = tmp_path / ".elora" / "secrets"
    secret_dir.mkdir(parents=True)
    (secret_dir / "token.txt").write_text("never expose", encoding="utf-8")
    refused = hands.code_read(".elora/secrets/token.txt", root=str(tmp_path))
    assert refused["ok"] is False
    assert "secrets are not readable" in refused["error"]

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    jailed = hands.code_read(str(outside), root=str(tmp_path))
    assert jailed["ok"] is False
    assert "escapes workspace" in jailed["error"]


def test_elora_source_never_enables_shell_true():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for directory, dirnames, filenames in os.walk(os.path.join(root, "elora")):
        dirnames[:] = [name for name in dirnames if name not in {"__pycache__", ".elora"}]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(directory, filename)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read(), filename=path)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    assert not any(
                        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                        for kw in node.keywords
                    ), f"shell=True in {os.path.relpath(path, root)}"


def test_resident_stream_orders_will_organs_voice_and_reports_rc(tmp_path):
    daemon = object.__new__(Daemon)
    daemon.inbox_dir = str(tmp_path / ".elora" / "inbox")
    os.makedirs(daemon.inbox_dir, exist_ok=True)
    task = Task(id="control-loop", event=Event.from_text("run an organ", source="inbox:will.txt"))
    daemon._append_chat("user", "run an organ", task.id)
    daemon._append_chat("organ", "sandbox.test: failed", task.id,
                        organ="sandbox.test", status="failed", rc=2, evidence="pytest failed")
    daemon._append_chat("elora", "The test organ returned a failure.", task.id)
    rows = json.loads((tmp_path / ".elora" / "chat.json").read_text(encoding="utf-8"))
    assert [row["sender"] for row in rows] == ["user", "organ", "elora"]
    assert rows[1]["rc"] == 2 and rows[1]["status"] == "failed"
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    app_js = open(os.path.join(root, "overlay", "app.js"), encoding="utf-8").read()
    assert "'X-ELORA-Client': 'resident-overlay'" in app_js
    assert "placeholder: 'Speak will...'" in app_js
    assert "tab is uncontrolled - no real session" in app_js
    assert "const stream = h('div', { class: 'chat' }," in app_js
    assert "label = '[SYSTEM QUEST]';" in app_js
    assert "label = '[ORGAN: '" in app_js
    assert "clear(chatLog)" not in app_js
    daemon_py = open(os.path.join(root, "elora", "daemon.py"), encoding="utf-8").read()
    tick_start = daemon_py.index("    def tick(self)")
    tick_end = daemon_py.find("\n    def ", tick_start + 8)
    tick_source = daemon_py[tick_start:tick_end]
    assert tick_source.index('self._append_chat("user"') < tick_source.index("self.handle_task(task)")


def test_organ_payload_failure_is_not_marked_success(tmp_path):
    daemon = object.__new__(Daemon)
    daemon.inbox_dir = str(tmp_path / ".elora" / "inbox")
    os.makedirs(daemon.inbox_dir, exist_ok=True)
    daemon.vault = None
    task = Task(id="bad-organ", event=Event.from_text("check", source="inbox:will.txt"))
    daemon._apply_broker_result(
        task, "plugin.call", {},
        Result(returncode=0, stdout='{"ok": false, "is_error": true}'),
        owner=False,
    )
    assert task.trace[-1]["ok"] is False
    row = json.loads((tmp_path / ".elora" / "chat.json").read_text(encoding="utf-8"))[-1]
    assert row["sender"] == "organ" and row["status"] == "failed" and row["rc"] == 0


def test_inbox_record_flows_to_core_daemon(tmp_path, monkeypatch):
    state_dir = tmp_path / ".elora"
    state_dir.mkdir()
    ledger_path = state_dir / "akashic.db"
    monkeypatch.setattr(server, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(server, "LEDGER_PATH", str(ledger_path))
    with pytest.raises(server.ApiError) as error:
        server.payload_inbox_task("verify the house")
    assert error.value.status == 503
    assert not list((state_dir / "inbox").glob("*.txt"))

    AkashicLedger(str(ledger_path))
    queued = server.payload_inbox_task("Call only sandbox.repo_map")
    assert queued["ok"] is True
    assert AkashicLedger(str(ledger_path)).verify() == (True, None)

    daemon = object.__new__(Daemon)
    daemon.inbox_dir = str(state_dir / "inbox")
    daemon._poll_ring = lambda: []
    daemon.core_token = SkillToken("core", tier=Tier.CORE, workspace=str(tmp_path), issued_at=0)
    daemon.skills_token = SkillToken("skill", tier=Tier.QUARANTINE, workspace=str(tmp_path), issued_at=0)
    tasks = daemon.poll_inbox()
    assert len(tasks) == 1
    assert daemon._is_owner_will(tasks[0]) is True
    assert daemon._token_for(tasks[0]).tier == Tier.CORE
"""Acceptance coverage for the Resident will → CORE → broker → evidence loop."""

from __future__ import annotations

import http.client
import json
import os
import threading
from pathlib import Path

import pytest

from elora.brain import ScriptedBrain
from elora.core.broker import Broker, Rejected, Result
from elora.core.capabilities import SkillToken, Tier
from elora.core.metabolism import Metabolism
from elora.core.owner_will import WORKSPACE_ROOT, infer_owner_organs
from elora.daemon import Daemon, Event, Task, TaskState
from elora.dashboard import server as dashboard
from elora.organs.akashic import AkashicLedger
from elora.slime import browser as browser_module
from elora.slime import sandbox
from conftest import FakeLedger, FakeVault


@pytest.fixture
def runtime(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    ledger, vault = FakeLedger(), FakeVault()
    broker = Broker(
        metabolism=metabolism,
        ledger=ledger,
        vault=vault,
        consent_dir=str(tmp_path / "consent"),
        vault_root=str(tmp_path / "vault"),
    )
    brain = ScriptedBrain(script=[])
    daemon = Daemon(
        brain=brain,
        broker=broker,
        metabolism=metabolism,
        ledger=ledger,
        vault=vault,
        inbox_dir=str(inbox),
    )
    # Keep acceptance tests inside their tmp_path; no repo state file is written.
    daemon._write_state = lambda **kwargs: None
    try:
        yield {
            "daemon": daemon,
            "brain": brain,
            "broker": broker,
            "ledger": ledger,
            "metabolism": metabolism,
            "inbox": inbox,
            "tmp": tmp_path,
        }
    finally:
        metabolism.shutdown()


def test_owner_will_routes_registered_workspace_organs_and_closed_marketplace():
    assert infer_owner_organs("git status/diff") == [
        ("git.status", {}),
        ("git.diff", {}),
    ]
    assert infer_owner_organs("list files in overlay") == [("ws.list", {"path": "overlay"})]
    assert infer_owner_organs("read src-tauri/src/main.rs") == [
        ("code.read", {"path": "src-tauri/src/main.rs"})
    ]
    assert infer_owner_organs("is blender open") == []
    assert infer_owner_organs("Do not open chrome or run tests") == []

    catalogue = sandbox.marketplace()
    assert catalogue["ok"] is True
    assert catalogue["allowed"] == ["git", "sandbox", "ledger", "core"]
    assert {row["name"] for row in catalogue["servers"]} == set(catalogue["allowed"])
    assert catalogue["no_npx"] is True
    assert all(row["installable"] is False for row in catalogue["servers"])


def test_implementation_will_maps_before_model_and_defers_tests():
    calls = infer_owner_organs("fix the overlay and run tests")
    assert calls
    assert calls[0][0] == "sandbox.repo_map"
    assert all(name != "sandbox.test" for name, _ in calls)
    assert infer_owner_organs("run tests") == [("sandbox.test", {})]


def test_resident_inbox_requires_identity_and_records_queued_akashic_evidence(tmp_path, monkeypatch):
    state_dir = tmp_path / ".elora"
    state_dir.mkdir()
    ledger_path = state_dir / "akashic.db"
    ledger = AkashicLedger(str(ledger_path))
    monkeypatch.setattr(dashboard, "STATE_DIR", str(state_dir))
    monkeypatch.setattr(dashboard, "LEDGER_PATH", str(ledger_path))

    server = dashboard.serve("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(client_name):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.request(
            "POST",
            "/api/inbox/task",
            body=json.dumps({"prompt": "read README.md"}),
            headers={
                "Content-Type": "application/json",
                dashboard.CLIENT_HEADER: client_name,
            },
        )
        response = connection.getresponse()
        status = response.status
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return status, payload

    try:
        status, _ = post("dashboard")
        assert status == 403
        assert not list((state_dir / "inbox").glob("*.txt"))

        status, payload = post("resident-overlay")
        assert status == 200
        task_id = payload["task_id"]
        assert (state_dir / "inbox" / task_id).read_text(encoding="utf-8") == "read README.md"
        row = json.loads((state_dir / "chat.json").read_text(encoding="utf-8"))[-1]
        assert row["client"] == "resident-overlay"
        assert row["status"] == "queued"

        event = next(
            item for item in ledger.recent_events(kind="task_queued", n=10)
            if item["payload"].get("filename") == task_id
        )
        assert event["payload"]["client"] == "resident-overlay"
        assert ledger.verify() == (True, None)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        ledger.conn.close()


def test_owner_daemon_compiles_and_executes_inferred_organ_before_brain(runtime, monkeypatch):
    import elora.daemon as daemon_module

    order = []
    original_infer = daemon_module.infer_owner_organs
    original_complete = runtime["brain"].complete

    def infer(text):
        order.append("infer")
        return original_infer(text)

    def complete(system, messages):
        order.append("brain")
        return original_complete(system, messages)

    def request(token, name, args):
        order.append(f"broker:{name}")
        assert token.tier == Tier.CORE
        return Result(stdout="## arena/acceptance")

    monkeypatch.setattr(daemon_module, "infer_owner_organs", infer)
    monkeypatch.setattr(runtime["brain"], "complete", complete)
    monkeypatch.setattr(runtime["broker"], "request", request)
    runtime["brain"].script = ["DONE"]

    task = Task(
        id="owner-order",
        event=Event.from_text("git status", source="inbox:chat_order.txt"),
    )
    runtime["daemon"].handle_task(task)

    assert task.state == TaskState.DONE
    assert order == ["infer", "broker:git.status", "brain"]
    assert any(event["kind"] == "will_compiled" for event in runtime["ledger"].events)
    assert any(item.get("organ") == "infer_owner_organs" and item.get("recorded") for item in task.trace)
    assert any(item.get("tool") == "git.status" and item.get("ok") for item in task.trace)


def test_code_edit_checkpoints_before_write_and_runs_controls_after(runtime, monkeypatch):
    import elora.daemon as daemon_module

    order = []
    compiled = []
    original_infer = daemon_module.infer_owner_organs
    original_complete = runtime["brain"].complete

    def infer(text):
        calls = original_infer(text)
        compiled.append(calls)
        return calls

    def complete(system, messages):
        order.append("brain")
        return original_complete(system, messages)

    def request(token, name, args):
        order.append(f"broker:{name}")
        return Result(stdout=f"{name} recorded")

    runtime["brain"].script = [
        '<mcp_call server="elora" tool="code.edit">'
        + json.dumps({"path": "overlay/app.js", "full_content": "// checkpointed fixture"})
        + "</mcp_call>",
        "DONE",
    ]
    monkeypatch.setattr(daemon_module, "infer_owner_organs", infer)
    monkeypatch.setattr(runtime["brain"], "complete", complete)
    monkeypatch.setattr(runtime["broker"], "request", request)

    task = Task(
        id="post-edit-order",
        event=Event.from_text("fix the overlay and run tests", source="inbox:chat_edit.txt"),
    )
    runtime["daemon"].handle_task(task)

    assert task.state == TaskState.DONE
    assert compiled and compiled[0][0][0] == "sandbox.repo_map"
    assert all(name != "sandbox.test" for name, _ in compiled[0])
    assert order == [
        "broker:sandbox.repo_map",
        "brain",
        "broker:sandbox.checkpoint",
        "broker:code.edit",
        "broker:sandbox.diagnose",
        "broker:sandbox.test",
        "brain",
    ]


def test_owner_voice_is_silent_for_success_and_factual_for_failures():
    successful = Task(id="success", event=Event.from_text("fix overlay"))
    successful.trace = [{"tool": "code.edit", "ok": True}]
    assert Daemon._owner_voice(successful) == ""

    failed = Task(id="failure", event=Event.from_text("git status"))
    failed.trace = [{
        "tool": "git.status",
        "ok": False,
        "rc": 1,
        "evidence": "permission denied",
    }]
    voice = Daemon._owner_voice(failed)
    assert "git.status rc=1" in voice
    assert "permission denied" in voice
    assert "SUCCESS" not in voice.upper()


def test_public_chat_endpoint_is_talk_only_even_if_reply_contains_tool_markup(monkeypatch):
    requests = []
    tool_markup = '<mcp_call server="elora" tool="shell.run_command">{"command":"echo no"}</mcp_call>'

    def fake_request(path, timeout, method, body):
        requests.append((path, timeout, method, json.loads(body.decode("utf-8"))))
        return {
            "choices": [{"message": {"content": tool_markup}}],
            "usage": {"total_tokens": 4},
            "id": "talk-only-test",
        }

    monkeypatch.setattr(dashboard, "omniroute_config", lambda: {"model": "test-model"})
    monkeypatch.setattr(
        dashboard,
        "resolve_model",
        lambda model: {"model": model, "chosen_by": "test", "is_alias": False},
    )
    monkeypatch.setattr(dashboard, "_omni_request", fake_request)

    result = dashboard.payload_chat("talk only", model="test-model")
    assert result["reply"] == tool_markup
    assert len(requests) == 1
    assert requests[0][0] == "/v1/chat/completions"
    assert requests[0][2] == "POST"
    assert requests[0][3]["messages"][-1] == {"role": "user", "content": "talk only"}

    catalogue = dashboard.payload_mcp_servers(refresh=True)
    assert catalogue["allowed"] == ["git", "sandbox", "ledger", "core"]
    assert catalogue["probed"] is False
    with pytest.raises(dashboard.ApiError) as mcp_call:
        dashboard.payload_mcp_call("omniroute", "health", {})
    assert mcp_call.value.status == 410
    with pytest.raises(dashboard.ApiError) as router_call:
        dashboard.payload_router_tool("health")
    assert router_call.value.status == 410


def test_browser_context_is_real_handoff_or_explicitly_uncontrolled(tmp_path, monkeypatch):
    session_file = tmp_path / "browser-session.json"
    monkeypatch.setattr(browser_module, "SESSION_PATH", str(session_file))

    absent = browser_module.read_session_context()
    assert absent["available"] is False
    assert absent["reason"] == "tab is uncontrolled - no real session"
    assert absent["bookmarks"] is None

    handoff = browser_module.handoff_session({
        "current_page": {"url": "https://docs.example/python", "title": "Python docs"},
        "current_pages": [{"url": "https://docs.example/reference", "title": "Reference"}],
        "bookmarks": [{"url": "https://docs.example/guide", "title": "Python guide"}],
        "quick_links": [{"url": "https://docs.example/start", "title": "Python start"}],
    }, path=str(session_file))
    assert handoff["ok"] is True

    browser = browser_module.BrowserOrgan(headless=True)
    all_items = browser.search("")
    results = browser.search("python")
    assert all_items["ok"] is True
    assert len(all_items["results"]) == 4
    assert results["ok"] is True
    assert results["source"] == "handed-off browser session"
    assert len(results["results"]) == 3
    assert all("python" in item["title"].lower() for item in results["results"])


def test_perception_requires_real_jail_contained_image(tmp_path):
    from PIL import Image

    missing = dashboard.payload_perception(str(tmp_path / "missing-state.json"))
    assert missing["available"] is False
    assert missing["reason"] == "state.json absent"

    screenshots = tmp_path / "screenshots"
    screenshots.mkdir()
    good = screenshots / "still.png"
    Image.new("RGB", (2, 2), color=(12, 24, 36)).save(good)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "last_perception": {"available": True, "synthetic": False, "path": str(good)},
    }), encoding="utf-8")
    real = dashboard.payload_perception(str(state_file))
    assert real["available"] is True
    assert real["path"] == str(good.resolve())

    state_file.write_text(json.dumps({
        "last_perception": {"available": True, "synthetic": True, "path": str(good)},
    }), encoding="utf-8")
    synthetic = dashboard.payload_perception(str(state_file))
    assert synthetic["available"] is False

    outside = tmp_path / "outside.png"
    Image.new("RGB", (2, 2), color=(36, 24, 12)).save(outside)
    escape = screenshots / "escape.png"
    try:
        escape.symlink_to(outside)
    except OSError:
        escape = None
    if escape is not None:
        state_file.write_text(json.dumps({
            "last_perception": {"available": True, "synthetic": False, "path": str(escape)},
        }), encoding="utf-8")
        assert dashboard.payload_perception(str(state_file))["available"] is False

    corrupt = screenshots / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    state_file.write_text(json.dumps({
        "last_perception": {"available": True, "synthetic": False, "path": str(corrupt)},
    }), encoding="utf-8")
    assert dashboard.payload_perception(str(state_file))["available"] is False


def test_resident_tauri_and_single_timeline_contract():
    root = Path(WORKSPACE_ROOT)
    app = (root / "overlay" / "app.js").read_text(encoding="utf-8")
    styles = (root / "overlay" / "styles.css").read_text(encoding="utf-8")
    bridge = (root / "overlay" / "tauri_bridge.js").read_text(encoding="utf-8")
    rust = (root / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    live_smoke = (root / "tools" / "_test_live_resident.py").read_text(encoding="utf-8")

    assert "placeholder: 'Speak will...'" in app
    assert "placeholder: 'Speak will…'" not in app
    assert "e.key === 'Enter' && !e.shiftKey" in app
    assert "client: 'resident-overlay'" in app
    assert "api('/api/inbox/task'" in app
    assert "text: 'nothing spoken yet'" in app
    assert "dataset: { role: isWill ? 'will'" in app
    assert "clear(chatLog)" not in app
    assert "msg.sender === 'organ' && msg.recorded === true && state.organism) state.organism.ripple()" in app
    assert "state.ripples" not in app
    assert "resident-ripples-feed" not in app
    assert "existingLayout" in app
    assert "const BASE = '';" in app
    assert "http://127.0.0.1" not in app
    assert ".quick-btn" not in styles
    assert ".quick-actions" not in styles
    assert "align-self: flex-end" not in styles

    dispatch = app.split("async function dispatchTask(prompt) {", 1)[1].split(
        "function residentMessageKey", 1
    )[0]
    assert "[ORGAN: inbox FAILED]" in dispatch
    assert "toast(" not in dispatch
    sync = app.split("async function syncChat() {", 1)[1].split(
        "async function dispatchTask", 1
    )[0]
    assert "organism.ripple" not in sync

    assert "sendInboxTask" not in bridge
    assert "send_inbox_task" not in rust
    assert "onRipple" not in bridge
    assert "window.emit(\"ripple\"" not in rust
    assert "trigger_ripple" not in rust
    assert '"--brain", "bitnet"' in rust
    assert "res.available && Array.isArray(res.data)" in app
    assert "api('/api/mcp/servers')" in app
    assert "/api/mcp/tools" not in app
    assert "/api/mcp/call" not in app
    assert "/api/router/tools" not in app
    assert "github|playwright|fetch|memory|filesystem|blender" not in app
    assert "Direct tool execution is disabled here" in app
    assert "ELORA_CONSOLE_URL" in live_smoke
    assert "quick-btn" not in live_smoke


def test_broker_ripple_follows_akashic_result(tmp_path, monkeypatch):
    from elora import overlay_bridge

    ledger = AkashicLedger(str(tmp_path / "akashic.db"))
    metabolism = Metabolism(cache_dir=str(tmp_path / "cache"), ram_hard_cap_mb=16000)
    broker = Broker(
        metabolism=metabolism,
        ledger=ledger,
        vault=FakeVault(),
        consent_dir=str(tmp_path / "consent"),
        vault_root=str(tmp_path / "vault"),
    )
    token = SkillToken(
        skill_id="control-loop-acceptance",
        tier=Tier.CORE,
        workspace=WORKSPACE_ROOT,
        issued_at=0.0,
    )
    observed = []
    real_append = ledger.append

    def append(organ, kind, message, payload=None):
        digest = real_append(organ, kind, message, payload)
        if kind in ("capability_intent", "capability_result"):
            observed.append(("ledger", kind))
        return digest

    def ripple(capability):
        observed.append(("ripple", capability, ledger.events[-1]["kind"]))

    def emit(organ, kind, ring_path=None):
        observed.append(("ring", organ, kind, ledger.events[-1]["kind"]))

    monkeypatch.setattr(ledger, "append", append)
    monkeypatch.setattr(overlay_bridge, "ripple", ripple)
    monkeypatch.setattr(overlay_bridge, "emit_ripple", emit)
    try:
        result = broker.request(token, "git.status", {})
        assert result.ok is True
        assert result.evidence_recorded is True
        assert observed == [
            ("ledger", "capability_intent"),
            ("ledger", "capability_result"),
            ("ripple", "git.status", "capability_result"),
            ("ring", "broker", "git.status", "capability_result"),
        ]
        assert ledger.verify() == (True, None)
        assert [event["kind"] for event in ledger.recent_events()] == [
            "capability_intent",
            "capability_result",
        ]

        class BrokenIntentLedger:
            def append(self, **kwargs):
                raise OSError("ledger disk unavailable")

        blocked_metabolism = Metabolism(
            cache_dir=str(tmp_path / "blocked-cache"), ram_hard_cap_mb=16000,
        )
        blocked = Broker(
            metabolism=blocked_metabolism,
            ledger=BrokenIntentLedger(),
            consent_dir=str(tmp_path / "blocked-consent"),
            vault_root=str(tmp_path / "blocked-vault"),
        )
        executed = []
        monkeypatch.setattr(blocked, "_execute", lambda *args: executed.append(args))
        try:
            rejected = blocked.request(token, "git.status", {})
            assert isinstance(rejected, Rejected)
            assert rejected.evidence_recorded is False
            assert "was not executed" in rejected.reason
            assert executed == []
        finally:
            blocked_metabolism.shutdown()

        class ResultWriteFails:
            def __init__(self):
                self.count = 0

            def append(self, **kwargs):
                self.count += 1
                if self.count == 2:
                    raise OSError("ledger locked")
                return "intent-hash"

        result_metabolism = Metabolism(
            cache_dir=str(tmp_path / "result-cache"), ram_hard_cap_mb=16000,
        )
        result_broker = Broker(
            metabolism=result_metabolism,
            ledger=ResultWriteFails(),
            consent_dir=str(tmp_path / "result-consent"),
            vault_root=str(tmp_path / "result-vault"),
        )
        from types import SimpleNamespace
        monkeypatch.setattr(result_broker, "_execute", lambda *args: SimpleNamespace(
            returncode=0, killed_by=None, stdout_sha256="", stdout="ran", stderr="",
        ))
        pulses_before = list(observed)
        try:
            unsealed = result_broker.request(token, "git.status", {})
            assert isinstance(unsealed, Result)
            assert unsealed.ok is False
            assert unsealed.evidence_recorded is False
            assert "capability_result write failed after execution" in unsealed.stderr
            assert observed == pulses_before
        finally:
            result_metabolism.shutdown()
    finally:
        metabolism.shutdown()
        ledger.conn.close()
