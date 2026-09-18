"""
test_computer_use.py — WIRE-3 Tier0 perception and desktop actuation.

Four inspection rungs, no theater:
  1. capture writes file + SHA-256
  2. control refuses QUARANTINE on Windows
  3. click coordinates jail (must be within screen bounds)
  4. type_keys fuel-metered
"""

import hashlib
import json
import os
import pytest

from elora.core.broker import Rejected, Result
from elora.core.capabilities import Tier
from elora.core.armored_subprocess import armored_run
from elora.slime import computer_use


@pytest.fixture
def trusted_token(tmp_path):
    from conftest import token
    return token(Tier.TRUSTED, str(tmp_path / "ws"))


@pytest.fixture
def quarantine_token(tmp_path):
    from conftest import token
    return token(Tier.QUARANTINE, str(tmp_path / "ws"))


# ----------------------------------------------------------------------
# RUNG 1 — Capture writes file + SHA
# ----------------------------------------------------------------------

class TestRung1ScreenCapture:
    def test_capture_direct_writes_file_and_sha(self, tmp_path):
        out_file = str(tmp_path / "screen_test.png")
        res = computer_use.capture(out_path=out_file)

        assert os.path.exists(out_file)
        assert res["path"] == os.path.abspath(out_file)
        assert len(res["sha256"]) == 64

        # Digest must match actual file bytes
        with open(out_file, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        assert res["sha256"] == digest
        assert res["bytes"] > 0
        assert res["width"] > 0
        assert res["height"] > 0

    def test_capture_via_broker_quarantine_allowed(self, broker, quarantine_token, tmp_path):
        # screen.capture is Risk.TRIVIAL, so QUARANTINE tier is permitted
        out_file = os.path.join(quarantine_token.workspace, "perception.png")
        result = broker.request(quarantine_token, "screen.capture", {"out_path": out_file})

        assert isinstance(result, Result)
        assert result.ok
        payload = json.loads(result.stdout)
        assert os.path.exists(payload["path"])
        assert payload["sha256"] == result.execution.stdout_sha256

    def test_capture_path_jail_holds(self, broker, quarantine_token):
        # Attempts to write outside approved roots are rejected at schema step
        bad_path = "C:/Windows/System32/hacked.png" if os.name == "nt" else "/etc/hacked.png"
        result = broker.request(quarantine_token, "screen.capture", {"out_path": bad_path})
        assert isinstance(result, Rejected)
        assert "not inside approved roots" in result.reason


# ----------------------------------------------------------------------
# RUNG 2 — Control refuses QUARANTINE on Windows
# ----------------------------------------------------------------------

class TestRung2ControlRefusesQuarantine:
    def test_broker_refuses_quarantine_for_control(self, broker, quarantine_token, monkeypatch):
        # Even with environment consent active, tier ceiling blocks QUARANTINE
        monkeypatch.setenv("ELORA_ALLOW_CONTROL", "1")
        result = broker.request(
            quarantine_token, "screen.control",
            {"action": "click", "x": 100, "y": 100}
        )
        assert isinstance(result, Rejected)
        assert "tier" in result.reason.lower()

    def test_windows_armored_run_refuses_untrusted_tiers(self):
        if os.name == "nt":
            with pytest.raises(RuntimeError) as exc:
                armored_run(["cmd", "/c", "echo test"], tier=Tier.QUARANTINE)
            assert "Untrusted tiers require POSIX armor" in str(exc.value)


# ----------------------------------------------------------------------
# RUNG 3 — Click coordinates jail (must be within screen bounds)
# ----------------------------------------------------------------------

class TestRung3ClickCoordinatesJail:
    def test_click_direct_negative_coordinates_jailed(self):
        with pytest.raises(ValueError) as exc:
            computer_use.click(-15, 200)
        assert "out of screen bounds" in str(exc.value)

    def test_click_direct_overflow_coordinates_jailed(self):
        width, height = computer_use.get_screen_bounds()
        with pytest.raises(ValueError) as exc:
            computer_use.click(width + 500, height + 500)
        assert "out of screen bounds" in str(exc.value)

    def test_broker_rejects_out_of_bounds_click(self, broker, trusted_token, monkeypatch):
        monkeypatch.setenv("ELORA_ALLOW_CONTROL", "1")
        result = broker.request(
            trusted_token, "screen.control",
            {"action": "click", "x": -50, "y": 100}
        )
        assert isinstance(result, Rejected)
        assert "out of screen bounds" in result.reason


# ----------------------------------------------------------------------
# RUNG 4 — type_keys fuel-metered
# ----------------------------------------------------------------------

class TestRung4TypeKeysFuelMetered:
    def test_type_keys_direct_exceeds_fuel_limit(self):
        overflow_text = "A" * (computer_use.DEFAULT_FUEL_LIMIT + 1)
        with pytest.raises(ValueError) as exc:
            computer_use.type_keys(overflow_text)
        assert "fuel limit" in str(exc.value)

    def test_broker_rejects_excessive_type_keys_fuel(self, broker, trusted_token, monkeypatch):
        monkeypatch.setenv("ELORA_ALLOW_CONTROL", "1")
        overflow_text = "B" * 600
        result = broker.request(
            trusted_token, "screen.control",
            {"action": "type_keys", "text": overflow_text}
        )
        assert isinstance(result, Rejected)
        assert "fuel limit" in result.reason

    def test_type_keys_within_budget_passes_gate(self):
        # Within budget should not raise ValueError for fuel
        try:
            computer_use.type_keys("test input", max_fuel=100)
        except RuntimeError as e:
            # pywinauto absent on host is expected and graceful
            assert "pywinauto absent" in str(e)
