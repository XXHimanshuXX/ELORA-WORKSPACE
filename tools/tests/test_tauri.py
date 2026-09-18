"""
test_tauri.py — Inspection rungs for Tauri Desktop Packaging & SHM Ripple Bridge.

Pass criteria:
  1. test_overlay_bridge_ripple_counter: emit_ripple writes to SPSC ring, read() returns
     matching organ, kind, and incremented counter; checksum valid.
  2. test_overlay_bridge_tamper_detection: flipping a byte in payload raises RuntimeError
     ("slot checksum failed").
  3. test_tauri_conf_valid: parses src-tauri/tauri.conf.json and verifies identifier
     com.elora.os, transparent window, and active bundle.
  4. test_tauri_sidecar_spawn_mock: mocks/runs sidecar command (python run.py --smoke)
     verifying exit code 0, GREEN smoke, and valid Akashic chain without flakes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest

from elora import overlay_bridge


class TestTauriDesktopPackaging:

    def test_overlay_bridge_ripple_counter(self, tmp_path):
        ring_file = str(tmp_path / "overlay.ring")
        try:
            ev = overlay_bridge.emit_ripple("broker", "capability_intent", ring_path=ring_file)
            assert ev.checksum
            assert ev.epoch >= 1

            data = overlay_bridge.read(ring_path=ring_file)
            assert data is not None
            assert data["organ"] == "broker"
            assert data["kind"] == "capability_intent"
            assert data["counter"] >= 1
            assert "ts" in data
        finally:
            overlay_bridge.close_ring(ring_file)

    def test_overlay_bridge_tamper_detection(self, tmp_path):
        ring_file = str(tmp_path / "overlay_tamper.ring")
        try:
            ev = overlay_bridge.emit_ripple("broker", "capability_intent", ring_path=ring_file)
            ring = overlay_bridge._get_ring(ring_file)

            # Corrupt payload byte in shared memory slot (starts at off + 4)
            corrupt_offset = ev.offset + 4
            ring.buf[corrupt_offset] ^= 0xFF

            with pytest.raises(RuntimeError) as exc_info:
                overlay_bridge.verify_and_read(ring_path=ring_file)
            assert "slot checksum failed" in str(exc_info.value)
        finally:
            overlay_bridge.close_ring(ring_file)

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

    def test_tauri_sidecar_spawn_mock(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        run_py = os.path.join(root, "run.py")

        # Mock the Tauri sidecar spawn by executing the sidecar entrypoint
        proc = subprocess.run(
            [sys.executable, run_py, "--smoke"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0
        assert "smoke: GREEN" in proc.stdout
        assert "akashic chain verifies" in proc.stdout
