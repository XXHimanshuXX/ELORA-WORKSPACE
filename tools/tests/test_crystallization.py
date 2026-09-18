# tools/tests/test_crystallization.py

import time
import pytest

from elora.core.crystallization import Crystallizer, CRYSTALLIZE_THRESHOLD
from elora.core.decay import DecayEngine
from elora.core.promotion import PromotionEngine
from elora.core.capabilities import Tier
from conftest import FakeLedger, FakeVault


class _Evt:
    def __init__(self, text):
        self.payload = {"text": text}


class _Task:
    def __init__(self, text, tools):
        self.event = _Evt(text)
        self.trace = [{"tool": t, "args": {}} for t in tools]
        self.id = "t1"


@pytest.fixture
def sys_(tmp_path):
    ledger, vault = FakeLedger(), FakeVault()
    promotion = PromotionEngine(ledger)
    skills_dir = tmp_path / "skills"
    cryst = Crystallizer(promotion, ledger, vault, str(skills_dir))
    decay = DecayEngine(promotion, ledger, vault, str(skills_dir),
                        str(tmp_path / "cold"))
    return {"c": cryst, "d": decay, "p": promotion, "l": ledger,
            "v": vault, "dir": skills_dir}


class TestCrystallization:

    def test_skill_born_after_threshold(self, sys_):
        task = _Task("generate a sunset image",
                     ["generate.image", "fs.write"])
        for _ in range(CRYSTALLIZE_THRESHOLD):
            sys_["c"].observe(task)
        # A spec file now exists and the ledger recorded the birth
        specs = list(sys_["dir"].glob("*.md"))
        assert len(specs) == 1
        kinds = [e["kind"] for e in sys_["l"].events]
        assert "skill_crystallized" in kinds

    def test_below_threshold_no_skill(self, sys_):
        task = _Task("t", ["shell.run_command"])
        for _ in range(CRYSTALLIZE_THRESHOLD - 1):
            sys_["c"].observe(task)
        assert list(sys_["dir"].glob("*.md")) == []

    def test_phase1_match_skips_llm(self, sys_):
        task = _Task("generate a sunset image",
                     ["generate.image", "fs.write"])
        for _ in range(CRYSTALLIZE_THRESHOLD):
            sys_["c"].observe(task)
        # The reborn trigger should match similar incoming text
        spec = sys_["c"].match("generate a sunset image please")
        assert spec is not None
        assert spec.capability_sequence == ["generate.image", "fs.write"]

    def test_unknown_capability_not_crystallized(self, sys_):
        task = _Task("t", ["telepathy.send"])
        for _ in range(CRYSTALLIZE_THRESHOLD):
            sys_["c"].observe(task)
        assert list(sys_["dir"].glob("*.md")) == []


class TestDecay:

    def test_stale_skill_archived_spec_survives(self, sys_):
        task = _Task("generate a sunset image",
                     ["generate.image", "fs.write"])
        for _ in range(CRYSTALLIZE_THRESHOLD):
            sys_["c"].observe(task)
        # Force staleness: age the record
        for rec in sys_["p"].skills.values():
            rec.last_transition = time.time() - 999 * 86400
            rec.total_tasks = 0
        sys_["d"].sweep()
        cold = (sys_["dir"].parent / "cold").glob("*.md")
        assert len(list(cold)) == 1     # spec retained, binding gone

    def test_rebirth_from_cold_spec(self, sys_):
        task = _Task("generate a sunset image",
                     ["generate.image", "fs.write"])
        for _ in range(CRYSTALLIZE_THRESHOLD):
            sys_["c"].observe(task)
        for rec in sys_["p"].skills.values():
            rec.last_transition = time.time() - 999 * 86400
            rec.total_tasks = 0
        sys_["d"].sweep()
        # Trigger fires again → revive
        skill_id = [r for r in sys_["p"].skills][0]
        assert sys_["d"].revive_from_spec(skill_id) is True
        assert len(list(sys_["dir"].glob("*.md"))) == 1   # back home
        kinds = [e["kind"] for e in sys_["l"].events]
        assert "skill_revived" in kinds

    def test_success_collapse_demotes(self, sys_):
        token = sys_["p"].register("test:skill")
        for _ in range(10):
            sys_["p"].report_success(token.skill_id)
        for _ in range(20):
            sys_["p"].report_success(token.skill_id)
            sys_["p"].report_failure(token.skill_id)
        rec = sys_["p"].skills[token.skill_id]
        rec.total_tasks = 40
        rec.failures = 25                 # >30% failure
        sys_["d"].sweep()
        assert rec.tier == Tier.QUARANTINE   # demoted by decay
# Daemon wiring — three lines, as everything in this system turns out to be:
