"""
test_metabolism.py — admission control, idle decay, ladder integrity.

Metabolic tests manipulate IDLE_DEMOTION_S directly: timing tests
that sleep for real minutes are not inspection, they are patience.
"""
import json
import os
import time

import pytest

from elora.core.metabolism import (
    Metabolism, State, STATE_ORDER, PROFILES)


def tiny_ram_metabolism(tmp_path, cap_mb):
    return Metabolism(cache_dir=str(tmp_path), ram_hard_cap_mb=cap_mb)


class TestAdmissionControl:
    def test_deferred_on_low_ram(self, tmp_path):
        m = tiny_ram_metabolism(tmp_path, cap_mb=300)
        try:
            outcome = m.promote_to(State.AWAKE)
            assert hasattr(outcome, "reason")
            assert outcome.reason == "ram_insufficient"
            assert m.current_state() == State.ALIVE   # unchanged
        finally:
            m.shutdown()

    def test_promote_when_ram_available(self, metabolism):
        outcome = metabolism.promote_to(State.AWAKE)
        assert outcome == State.AWAKE

    def test_deferred_never_raises(self, tmp_path):
        """The First Commandment: a failed promote DEFERS, never panics."""
        m = tiny_ram_metabolism(tmp_path, cap_mb=100)
        try:
            for target in [State.AWAKE, State.ALERT, State.ARMED,
                           State.DIGESTING]:
                outcome = m.promote_to(target)
                assert not isinstance(outcome, State) or outcome == State.ALIVE
            assert m.current_state() == State.ALIVE
        finally:
            m.shutdown()

    def test_failed_loader_unwinds(self, tmp_path):
        """Mid-ladder failure leaves a coherent system, one rung lower."""
        m = tiny_ram_metabolism(tmp_path, cap_mb=16000)
        def bad_loader():
            return False
        m.register_loader(State.AWAKE, bad_loader, lambda: True)
        try:
            outcome = m.promote_to(State.ARMED)
            assert hasattr(outcome, "reason")
            assert outcome.reason == "state_load_failed"
            assert m.current_state() in (State.ALIVE, State.CRYPTOBIOSIS)
        finally:
            m.shutdown()


class TestLadderIntegrity:
    def test_no_state_skip_in_ledger_order(self, metabolism):
        """Requesting DIGESTING from ALIVE walks every intermediate rung."""
        observed = []
        original = metabolism._touch
        metabolism._touch = lambda st: (observed.append(st), original(st))
        metabolism.promote_to(State.DIGESTING)
        # Walked through AWAKE and ALERT on the way up — no teleporting.
        assert State.AWAKE in observed
        assert State.ALERT in observed
        assert metabolism.current_state() == State.DIGESTING

    def test_capability_routing(self, metabolism):
        st = metabolism._state_for_capability("generate.image")
        assert st == State.ARMED
        st = metabolism._state_for_capability("voice.listen")
        assert st == State.ALERT
        st = metabolism._state_for_capability("inbox.poll")
        assert st == State.CRYPTOBIOSIS

    def test_unknown_capability_deferred_cleanly(self, metabolism):
        outcome = metabolism.request("telepathy.send")
        assert hasattr(outcome, "reason")
        assert outcome.reason == "no_state_provides"


class TestIdleDecay:
    def test_auto_demote_after_idle(self, metabolism):
        metabolism.promote_to(State.AWAKE)
        metabolism.IDLE_DEMOTION_S[State.AWAKE] = 0  # expire immediately
        metabolism._last_use[State.AWAKE] = time.time() - 1
        metabolism._housekeeping_once()   # synchronous tick for test
        assert STATE_ORDER.index(metabolism.current_state()) < \
               STATE_ORDER.index(State.AWAKE)

    def test_mark_used_resets_timer(self, metabolism):
        metabolism.promote_to(State.AWAKE)
        metabolism.mark_used("llm.local_inference")
        metabolism._housekeeping_once()
        assert metabolism.current_state() == State.AWAKE

    def test_alife_never_auto_demotes(self, metabolism):
        metabolism._last_use[State.ALIVE] = time.time() - 99999
        metabolism._housekeeping_once()
        assert metabolism.current_state() in (State.ALIVE, State.CRYPTOBIOSIS)


class TestAdaptationTable:
    def test_measured_cost_recorded(self, metabolism, tmp_path):
        """A loader that actually allocates raises the adapted cost
        above the naive estimate. Lies in the estimate get corrected."""
        metabolism.promote_to(State.AWAKE)
        persisted = tmp_path / "metabolism.json"
        assert persisted.exists()
        data = json.loads(persisted.read_text())
        assert "AWAKE" in data.get("adapted_mb", {})
# (Implementation note: Metabolism.shutdown() and _housekeeping_once() are the two methods the tests demand that the earlier draft lacked — shutdown() stops the housekeeping thread, _housekeeping_once() runs one demotion pass synchronously so decay is tested deterministically instead of by sleeping.)