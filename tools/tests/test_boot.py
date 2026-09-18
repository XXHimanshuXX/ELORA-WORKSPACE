# tools/tests/test_boot.py

import pytest
from run import preflight, smoke, build, stage_config
from elora.brain import ScriptedBrain
from elora.organs.akashic import AkashicLedger
from conftest import FakeLedger, FakeVault


def test_preflight_green_on_minimal_machine():
    """Preflight with heavyweights ABSENT must still pass — a slime
    without food is dormant, not broken. Absence = warning, never
    failure. This is the offline-first law made executable."""
    rc = preflight()
    assert rc == 0


def test_boot_assembles_with_fake_brain(tmp_path):
    brain = ScriptedBrain(script=["DONE"])
    ledger = FakeLedger()
    config = stage_config()
    assembled = build(config, ledger, brain)
    assembled.metabolism.shutdown()
    # Every subsystem exists and is wired
    for attr in ("ledger", "vault", "metabolism", "broker",
                 "promotion", "crystallizer", "decay", "daemon"):
        assert getattr(assembled, attr) is not None


def test_daemon_boots_as_quarantine_skill():
    """The daemon is not above its own laws: its token starts at
    QUARANTINE, proven by assembly, not by assertion."""
    brain = ScriptedBrain(script=["DONE"])
    assembled = build(stage_config(), FakeLedger(), brain)
    assembled.metabolism.shutdown()
    assert assembled.daemon.skills_token.tier.name == "QUARANTINE"


def test_boot_never_resumes_higher_than_alive():
    """Crash-recovery humility: even if metabolism.json says ARMED,
    boot demotes to ALIVE. Adapted costs persist; state does not."""
    brain = ScriptedBrain(script=["DONE"])
    assembled = build(stage_config(), FakeLedger(), brain)
    from elora.core.metabolism import State
    assert assembled.metabolism.current_state() == State.ALIVE
    assembled.metabolism.shutdown()