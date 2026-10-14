from types import SimpleNamespace

import psutil

from elora.core.proactive import ProactiveConsciousness
from elora.core.system_metrics import memory_snapshot


def test_memory_snapshot_uses_measured_available_and_total(monkeypatch):
    monkeypatch.setattr(
        psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8_000 * 1024 * 1024, available=800 * 1024 * 1024),
    )

    measured = memory_snapshot()

    assert measured == {
        "ram_metric_available": True,
        "ram_headroom": 0.1,
        "ram_available_mb": 800.0,
        "ram_total_mb": 8000.0,
    }


def test_memory_snapshot_reports_unknown_without_a_guess(monkeypatch):
    def unavailable():
        raise OSError("memory provider unavailable")

    monkeypatch.setattr(psutil, "virtual_memory", unavailable)

    measured = memory_snapshot()

    assert measured["ram_metric_available"] is False
    assert measured["ram_headroom"] is None
    assert measured["ram_available_mb"] is None
    assert measured["ram_metric_error"] == "OSError"


def test_idle_proactive_feed_only_speaks_on_force_or_measured_change(tmp_path, monkeypatch):
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(
        total=8_000 * 1024 * 1024, available=800 * 1024 * 1024))
    monkeypatch.setattr(psutil, "process_iter", lambda *args, **kwargs: iter(()))
    consciousness = ProactiveConsciousness(str(tmp_path))

    assert consciousness.tick_idle() is None  # establish a baseline silently
    assert consciousness.tick_idle() is None  # no changed observation, no chatter
    assert consciousness._read_chat() == []

    result = consciousness.tick_idle(force=True)
    assert result is not None
    assert "available RAM: 800 MiB of 8000 MiB (10.0%)" in result["message"]
    assert "kernel is hot" not in result["message"]
    assert "ring buffer is synchronized" not in result["message"]
    assert "unbounded filesystem writes" not in result["message"]
