"""
test_voice.py — WIRE-6 ASR/TTS speech organ.
State.ALERT: 1800MB budget.

Four inspection rungs, no theater:
  1. test_voice_listen_degrades_loudly — no sherpa -> returns degraded field, not exception
  2. test_voice_speak_path_jail — text tries to write outside .elora/voice/
  3. test_voice_budget_gated — RAM 1000MB -> DEFERRED
  4. test_voice_alert_auto_decay — ALERT demotes to ALIVE after idle
"""

import json
import os
import time
import pytest

from elora.core.broker import Rejected, Deferred, Result, Broker
from elora.core.capabilities import Tier
from elora.core.metabolism import Metabolism, State, STATE_ORDER
from elora.slime import voice
from elora.slime.voice import VoiceOrgan


@pytest.fixture
def probation_token(tmp_path):
    from conftest import token
    return token(Tier.PROBATION, str(tmp_path / "ws"))


# ----------------------------------------------------------------------
# RUNG 1 — Listen degrades loudly when sherpa-onnx absent
# ----------------------------------------------------------------------

def test_voice_listen_degrades_loudly(broker, probation_token):
    # Direct organ call
    organ = VoiceOrgan()
    res = organ.listen(seconds=3)
    assert "degraded" in res
    assert res["degraded"] == "sherpa-onnx absent"
    assert res["transcript"] == ""

    # Broker invocation
    result = broker.request(probation_token, "voice.listen", {"seconds": 2})
    assert isinstance(result, Result)
    assert result.ok
    payload = json.loads(result.stdout)
    assert payload["degraded"] == "sherpa-onnx absent"


# ----------------------------------------------------------------------
# RUNG 2 — Speak path jail holds
# ----------------------------------------------------------------------

def test_voice_speak_path_jail(broker, probation_token):
    # Attempting to escape the voice root is rejected at schema step
    traversal_path = "../../etc/shadow.wav"
    result = broker.request(
        probation_token, "voice.speak",
        {"text": "intruder alert", "out_path": traversal_path}
    )
    assert isinstance(result, Rejected)
    assert "approved roots" in result.reason or "not inside" in result.reason

    sys_path = "C:/Windows/System32/speech.wav" if os.name == "nt" else "/etc/speech.wav"
    result2 = broker.request(
        probation_token, "voice.speak",
        {"text": "intruder alert 2", "out_path": sys_path}
    )
    assert isinstance(result2, Rejected)
    assert "approved roots" in result2.reason or "not inside" in result2.reason


# ----------------------------------------------------------------------
# RUNG 3 — Budget gated by metabolism (RAM 1000MB -> Deferred)
# ----------------------------------------------------------------------

def test_voice_budget_gated(tmp_path, ledger, vault, probation_token):
    # Simulated 1000MB RAM cap: headroom is max(0, 1000 - 1200) = 0MB.
    # ALERT needs 1800MB (cost to reach from ALIVE is 1600MB), so it must DEFER.
    low_ram_metabolism = Metabolism(cache_dir=str(tmp_path / "meta"), ram_hard_cap_mb=1000)
    b = Broker(metabolism=low_ram_metabolism, ledger=ledger, vault=vault,
               consent_dir=str(tmp_path / "consent"))
    try:
        outcome = b.request(probation_token, "voice.listen", {"seconds": 5})
        assert isinstance(outcome, Deferred)
        assert outcome.reason == "ram_insufficient"
        assert outcome.needed_state == State.ALERT
    finally:
        low_ram_metabolism.shutdown()


# ----------------------------------------------------------------------
# RUNG 4 — ALERT state auto-demotes after idle decay
# ----------------------------------------------------------------------

def test_voice_alert_auto_decay(metabolism):
    # Promote to ALERT state
    metabolism.promote_to(State.ALERT)
    assert metabolism.current_state() == State.ALERT

    # Fast-forward ALERT idle expiration
    metabolism.IDLE_DEMOTION_S[State.ALERT] = 0
    metabolism._last_use[State.ALERT] = time.time() - 1
    metabolism._housekeeping_once()

    # Must demote at least one rung below ALERT
    assert STATE_ORDER.index(metabolism.current_state()) < STATE_ORDER.index(State.ALERT)

    # Continue decay to ALIVE
    metabolism.IDLE_DEMOTION_S[State.AWAKE] = 0
    metabolism._last_use[State.AWAKE] = time.time() - 1
    metabolism._housekeeping_once()
    assert metabolism.current_state() == State.ALIVE
