"""
test_tauri.py — Inspection rungs for Tauri Desktop Packaging & SHM Ripple Bridge.

Pass criteria:
  1. test_overlay_bridge_ripple_counter: a hash-chained Akashic event is recorded before
     the matching SPSC ripple is written; checksum valid.
  2. test_overlay_bridge_tamper_detection: flipping a byte in that recorded ripple raises
     RuntimeError ("slot checksum failed").
  3. test_tauri_conf_valid: parses src-tauri/tauri.conf.json and verifies identifier
     com.elora.os, transparent window, and active bundle.
  4. test_tauri_sidecar_uses_bitnet_without_resident_duplication: checks the real
     Rust sidecar argv and ensures raw stdout is not forwarded as an organism ripple.
  5. test_hermetic_smoke_runs_and_verifies_akashic: runs the separate zero-network
     smoke entrypoint and checks its exit code and ledger verification.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest

from elora import overlay_bridge
from elora.organs.akashic import AkashicLedger


class TestTauriDesktopPackaging:

    def test_overlay_bridge_ripple_counter(self, tmp_path):
        ring_file = str(tmp_path / "overlay.ring")
        ledger = AkashicLedger(str(tmp_path / "akashic.db"))
        try:
            digest = ledger.append(
                organ="broker", kind="capability_result", message="git.status",
                payload={"rc": 0},
            )
            ev = overlay_bridge.emit_ripple("broker", "git.status", ring_path=ring_file)
            assert ev.checksum
            assert ev.epoch >= 1
            assert ledger.events[-1]["hash"] == digest

            data = overlay_bridge.read(ring_path=ring_file)
            assert data is not None
            assert data["organ"] == "broker"
            assert data["kind"] == "git.status"
            assert data["counter"] >= 1
            assert "ts" in data
            assert ledger.verify() == (True, None)
        finally:
            overlay_bridge.close_ring(ring_file)
            ledger.conn.close()

    def test_overlay_bridge_tamper_detection(self, tmp_path):
        ring_file = str(tmp_path / "overlay_tamper.ring")
        ledger = AkashicLedger(str(tmp_path / "akashic_tamper.db"))
        try:
            ledger.append(
                organ="broker", kind="capability_intent", message="git.status",
                payload={"tier": "CORE"},
            )
            ev = overlay_bridge.emit_ripple("broker", "git.status", ring_path=ring_file)
            assert ledger.verify() == (True, None)
            ring = overlay_bridge._get_ring(ring_file)

            # Corrupt payload byte in shared memory slot (starts at off + 4)
            corrupt_offset = ev.offset + 4
            ring.buf[corrupt_offset] ^= 0xFF

            with pytest.raises(RuntimeError) as exc_info:
                overlay_bridge.verify_and_read(ring_path=ring_file)
            assert "slot checksum failed" in str(exc_info.value)
        finally:
            overlay_bridge.close_ring(ring_file)
            ledger.conn.close()

    def test_tauri_conf_valid(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        conf_path = os.path.join(root, "src-tauri", "tauri.conf.json")
        assert os.path.exists(conf_path), f"Missing {conf_path}"

        with open(conf_path, "r", encoding="utf-8") as f:
            conf = json.load(f)

        tauri_sec = conf.get("tauri", {})
        bundle_sec = tauri_sec.get("bundle", {})
        windows = tauri_sec.get("windows", [])

        assert bundle_sec.get("identifier") == "com.elora.os"
        assert bundle_sec.get("active") is True
        assert len(windows) > 0
        assert windows[0].get("transparent") is True

    def test_tauri_sidecar_uses_bitnet_without_resident_duplication(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        source_path = os.path.join(root, "src-tauri", "src", "main.rs")
        with open(source_path, "r", encoding="utf-8") as handle:
            source = handle.read()

        assert 'let args = vec!["-u", "run.py", "--brain", "bitnet"];' in source
        assert "--resident" not in source
        assert 'window.emit("ripple"' not in source

    def test_hermetic_smoke_runs_and_verifies_akashic(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        run_py = os.path.join(root, "run.py")
        proc = subprocess.run(
            [sys.executable, run_py, "--smoke"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert proc.returncode == 0
        assert "smoke: GREEN" in proc.stdout
        assert "akashic chain verifies" in proc.stdout
