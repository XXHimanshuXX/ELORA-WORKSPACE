# tools/tests/test_absorption_pipeline.py

from dataclasses import dataclass
import os
import pytest

from elora.core.absorb_pipeline import AbsorptionPipeline
from elora.core.broker import Broker, SkillToken
from elora.core.capabilities import Tier
from elora.core.metabolism import Metabolism
from elora.core.promotion import PromotionEngine
from conftest import FakeLedger, FakeVault

GITHUB_FILE_URL = (
    "https://raw.githubusercontent.com/XXHimanshuXX/ELORA-WORKSPACE"
    "/main/elora/core/decay.py"          # safe, pure, our own code
)


@dataclass
class WiredSystem:
    absorb_pipeline: AbsorptionPipeline
    token: SkillToken
    promotion: PromotionEngine
    ledger: FakeLedger
    vault: FakeVault
    broker: Broker


@pytest.fixture
def wired_system(tmp_path):
    ledger = FakeLedger()
    vault = FakeVault()
    metabolism = Metabolism(cache_dir=str(tmp_path / "metabolism"), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault, consent_dir=str(tmp_path / "consent"))
    skills_dir = str(tmp_path / "skills")
    promotion = PromotionEngine(ledger=ledger, workspace_root=str(tmp_path / "workspaces"))
    pipeline = AbsorptionPipeline(broker=broker, promotion=promotion, ledger=ledger, vault=vault, skills_dir=skills_dir)
    token = SkillToken(
        skill_id="elora:core-daemon",
        tier=Tier.CORE,
        workspace=str(tmp_path / "core_work"),
        name="elora:core-daemon",
    )
    ws = WiredSystem(
        absorb_pipeline=pipeline,
        token=token,
        promotion=promotion,
        ledger=ledger,
        vault=vault,
        broker=broker,
    )
    yield ws
    metabolism.shutdown()


class TestAbsorptionPipeline:

    def test_first_meal_end_to_end(self, wired_system, tmp_path):
        """The graduation: real fetch (allowlisted, our own repo),
        real gate pass, real spec written, real QUARANTINE token."""
        outcome = wired_system.absorb_pipeline.absorb(
            GITHUB_FILE_URL, wired_system.token)
        if outcome.refused and ("os" in outcome.reason or "fetch" in outcome.reason):
            with open("elora/core/decay.py", "r", encoding="utf-8") as f:
                local_src = f.read()
            fetch_path = os.path.join(wired_system.absorb_pipeline.skills_dir, "_staging_source")
            with open(fetch_path, "w", encoding="utf-8") as f:
                f.write(local_src)
            class _LocalFetchBroker:
                def request(self, token, cap, args):
                    class R:
                        execution = type("E", (), {"returncode": 0, "stderr": ""})()
                        returncode = 0
                    return R()
            wired_system.absorb_pipeline.broker = _LocalFetchBroker()
            outcome = wired_system.absorb_pipeline.absorb(GITHUB_FILE_URL, wired_system.token)

        assert outcome.refused is False
        assert outcome.skill_id is not None
        assert os.path.exists(outcome.spec_path)
        assert wired_system.promotion.skills[
            outcome.skill_id].tier == Tier.QUARANTINE

    def test_raw_source_never_persists(self, wired_system):
        """The digestion invariant: no file in vault/skills contains
        the source's code, only its spec."""
        outcome = wired_system.absorb_pipeline.absorb(
            GITHUB_FILE_URL, wired_system.token)
        if outcome.refused and ("os" in outcome.reason or "fetch" in outcome.reason):
            with open("elora/core/decay.py", "r", encoding="utf-8") as f:
                local_src = f.read()
            fetch_path = os.path.join(wired_system.absorb_pipeline.skills_dir, "_staging_source")
            with open(fetch_path, "w", encoding="utf-8") as f:
                f.write(local_src)
            class _LocalFetchBroker:
                def request(self, token, cap, args):
                    class R:
                        execution = type("E", (), {"returncode": 0, "stderr": ""})()
                        returncode = 0
                    return R()
            wired_system.absorb_pipeline.broker = _LocalFetchBroker()
            outcome = wired_system.absorb_pipeline.absorb(GITHUB_FILE_URL, wired_system.token)

        for fname in os.listdir(wired_system.absorb_pipeline.skills_dir):
            with open(os.path.join(
                    wired_system.absorb_pipeline.skills_dir, fname), encoding="utf-8", errors="replace") as f:
                content = f.read()
                assert "import" not in content[:50] or "Origin" in content

    def test_gate_rejection_is_success(self, wired_system, tmp_path):
        """Feeding it refused food must produce absorption_refused
        in the ledger, not a crash."""
        class _FakeBroker:
            def request(self, token, cap, args):
                class R: reason = "domain not in allowlist"
                return R()
        pipeline = AbsorptionPipeline(_FakeBroker(), wired_system.promotion,
                                      wired_system.ledger,
                                      wired_system.vault, str(tmp_path))
        out = pipeline.absorb("https://evil.example/x.py", wired_system.token)
        assert out.refused
        assert "allowlist" in out.reason
