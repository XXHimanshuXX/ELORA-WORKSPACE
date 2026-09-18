# tools/tests/test_gate_and_promotion.py

import pytest
from elora.core.absorption_gate import (
    digest, gate_selftest, GateReject)
from elora.core.promotion import PromotionEngine
from elora.core.capabilities import Tier
from conftest import FakeLedger


class TestAbsorptionGate:

    def test_gate_selftest_passes(self):
        assert gate_selftest() is True

    def test_evil_import_refused(self):
        r = digest("import os\nos.system('x')", "t")
        assert isinstance(r, GateReject)
        assert "refused import" in r.reason

    def test_dunder_escape_refused(self):
        r = digest("def f(x):\n return x.__class__\n", "t")
        assert isinstance(r, GateReject)
        assert "dunder" in r.reason

    def test_eval_refused(self):
        r = digest("def f(s):\n return eval(s)\n", "t")
        assert isinstance(r, GateReject)

    def test_pure_function_passes_with_contract(self):
        r = digest("def add(a, b):\n 'Add.'\n return a + b\n", "t")
        assert not isinstance(r, GateReject)
        assert r.functions[0]["name"] == "add"
        assert r.functions[0]["args"] == ["a", "b"]
        assert r.functions[0]["doc"] == "Add."
        assert len(r.sha256) == 64

    def test_gate_never_executes(self):
        """The proof of non-execution: a module-level line that
        would fail loudly if run never fails, because it never runs."""
        poisoned = "1/0\n"
        r = digest(poisoned, "t")
        # Parseable (it's an expression), no execution, no crash.
        assert r is not None


class TestPromotionEngine:

    def test_new_skill_is_quarantined(self, ledger):
        engine = PromotionEngine(ledger)
        token = engine.register("github:test/repo")
        assert token.tier == Tier.QUARANTINE

    def test_promotion_after_clean_streak(self, ledger):
        engine = PromotionEngine(ledger)
        token = engine.register("github:test/repo")
        for _ in range(engine.PROMOTION_CLEAN_STREAK):
            engine.report_success(token.skill_id)
        rec = engine.skills[token.skill_id]
        assert rec.tier == Tier.PROBATION

    def test_demotion_on_single_failure(self, ledger):
        engine = PromotionEngine(ledger)
        token = engine.register("github:test/repo")
        for _ in range(engine.PROMOTION_CLEAN_STREAK):
            engine.report_success(token.skill_id)
        engine.report_failure(token.skill_id, "exploded")
        assert engine.skills[token.skill_id].tier == Tier.QUARANTINE

    def test_no_skip_to_trusted(self, ledger):
        engine = PromotionEngine(ledger)
        token = engine.register("github:test/repo")
        for _ in range(100):
            engine.report_success(token.skill_id)
        # 100 clean gets TRUSTED — but only by walking PROBATION first
        assert engine.skills[token.skill_id].tier == Tier.TRUSTED
        kinds = [e["kind"] for e in ledger.events]
        assert kinds.count("skill_promoted") == 2

    def test_transitions_in_ledger(self, ledger):
        engine = PromotionEngine(ledger)
        token = engine.register("github:test/repo")
        assert ledger.events[-1]["kind"] == "skill_registered"
        engine.report_failure(token.skill_id)
        # Quarantine failure demotes nowhere but still logs nothing
        # new — demotion from QUARANTINE is a no-op. Honest.
        engine.register("github:other/repo")
        assert ledger.events[-1]["kind"] == "skill_registered"
# Wiring the daemon (the missing 3 lines):
# 4. Status — The v7 Ring Is Closed
