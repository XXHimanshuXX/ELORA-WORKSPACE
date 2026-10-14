import pytest

from elora.dashboard import server as dashboard
from elora.organs.akashic import AkashicLedger


def test_recent_ledger_reader_pages_in_order_without_loading_full_history(tmp_path, monkeypatch):
    path = tmp_path / "akashic.db"
    writer = AkashicLedger(str(path))
    for index in range(5):
        writer.append("test", "event", f"event-{index + 1}", {"index": index + 1})

    def full_load_is_not_allowed(self):
        pytest.fail("bounded ledger read should not load the complete history")

    monkeypatch.setattr(AkashicLedger, "_load_events", full_load_is_not_allowed)

    newest = AkashicLedger.read_recent_events(str(path), n=2)
    older = AkashicLedger.read_recent_events(str(path), n=2, before_seq=newest[0]["seq"])

    assert [event["seq"] for event in newest] == [4, 5]
    assert [event["seq"] for event in older] == [2, 3]
    assert [event["message"] for event in older] == ["event-2", "event-3"]


def test_dashboard_ledger_page_exposes_an_older_cursor(tmp_path, monkeypatch):
    path = tmp_path / "akashic.db"
    writer = AkashicLedger(str(path))
    for index in range(4):
        writer.append("test", "event", f"event-{index + 1}")
    monkeypatch.setattr(dashboard, "LEDGER_PATH", str(path))

    newest = dashboard.payload_ledger(2)
    older = dashboard.payload_ledger(2, before_seq=newest["oldest_seq"])

    assert newest["has_older"] is True
    assert older["has_older"] is False
    assert [event["seq"] for event in newest["events"]] == [3, 4]
    assert [event["seq"] for event in older["events"]] == [1, 2]


def test_task_receipt_uses_only_broker_events_linked_to_that_run():
    task = {"id": "chat_1.txt", "goal": "inspect the status"}
    events = [
        {"seq": 1, "kind": "task_started", "message": "run-1",
         "payload": {"text": "inspect the status"}},
        {"seq": 2, "kind": "capability_intent", "message": "git.status",
         "payload": {"skill": "owner"}},
        {"seq": 3, "kind": "capability_result", "message": "git.status",
         "payload": {"rc": 0, "verified": True, "verification_basis": "capability_returncode"},
         "hash": "abc123"},
        {"seq": 4, "kind": "task_finished", "message": "run-1",
         "payload": {"status": "DONE"}},
        {"seq": 5, "kind": "capability_result", "message": "unrelated",
         "payload": {"rc": 0, "verified": True}},
    ]

    linked = dashboard._linked_task_events(task, events)
    receipt = dashboard._task_receipt(linked)

    assert [event["seq"] for event in linked] == [1, 2, 3, 4]
    assert receipt["verified"] is True  # Broker reports a zero return code.
    assert receipt["invariants_audited"] is False  # No invariant proof is recorded.
    assert receipt["hash"] == "abc123"
    assert [stage["key"] for stage in dashboard._stages_from_events(linked)] == [
        "task_started", "capability_intent", "capability_result", "task_finished"
    ]


def test_task_status_alone_does_not_create_a_verified_receipt():
    receipt = dashboard._task_receipt([])

    assert receipt["verified"] is False
    assert receipt["status"] == "NOT RECORDED"
    assert receipt["invariants_audited"] is False


def test_payload_tasks_does_not_turn_proactive_messages_into_tasks(tmp_path, monkeypatch):
    import json

    chat_path = tmp_path / "chat.json"
    chat_path.write_text(json.dumps([
        {"sender": "elora", "task_id": "proactive_1", "proactive": True,
         "status": "idle_reflection", "text": "Measured RAM update"},
        {"sender": "user", "task_id": "chat_1.txt", "status": "queued",
         "text": "inspect the status"},
    ]), encoding="utf-8")
    monkeypatch.setattr(dashboard, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(dashboard, "LEDGER_PATH", str(tmp_path / "missing.db"))

    result = dashboard.payload_tasks()

    assert [task["id"] for task in result["tasks"]] == ["chat_1.txt"]


def test_payload_tasks_cache_coalesces_reads_and_invalidates_on_chat_change(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time

    monkeypatch.setattr(dashboard, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(dashboard, "LEDGER_PATH", str(tmp_path / "akashic.db"))
    calls = []
    calls_lock = threading.Lock()

    def build(limit):
        with calls_lock:
            calls.append(limit)
            count = len(calls)
        time.sleep(0.02)
        return {"available": True, "count": count, "tasks": []}

    monkeypatch.setattr(dashboard, "_payload_tasks_uncached", build)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: dashboard.payload_tasks(), range(8)))

    assert len(calls) == 1
    assert {result["count"] for result in results} == {1}

    (tmp_path / "chat.json").write_text("[]", encoding="utf-8")
    refreshed = dashboard.payload_tasks()
    assert len(calls) == 2
    assert refreshed["count"] == 2
