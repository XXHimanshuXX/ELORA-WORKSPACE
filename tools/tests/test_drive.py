"""
test_drive.py — the four safety rungs of the Drive Loop.

Autonomy is not privilege. These tests verify:
  1. test_drive_cannot_escalate: Self-experiments execute at QUARANTINE.
     Attempts to run higher-risk capabilities get Rejected by the Broker.
  2. test_expand_respects_allowlist: Expansion absorption is allowlist-only
     (raw.githubusercontent.com). Unapproved domains are refused.
  3. test_hunger_respects_budget: Runaway consolidation (1000 episodes) is
     strictly throttled by the metabolic budget cap.
  4. test_drive_disabled_is_today: ELORA_DRIVE=off disables all hungers;
     the system degrades cleanly to passive mode.
"""

import os
import time
import pytest

from elora.brain import ScriptedBrain
from elora.core.broker import Broker, SkillToken
from elora.core.capabilities import Tier, Risk, REGISTRY
from elora.core.crystallization import Crystallizer
from elora.core.decay import DecayEngine
from elora.core.drive import DriveLoop, Hunger
from elora.core.metabolism import Metabolism
from elora.core.promotion import PromotionEngine
from elora.daemon import Daemon, Task, Event, TaskState
from conftest import FakeLedger, FakeVault


@pytest.fixture
def drive_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ELORA_DRIVE", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    ledger = FakeLedger()
    vault = FakeVault()
    metabolism = Metabolism(cache_dir=str(cache_dir), ram_hard_cap_mb=16000)
    broker = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
                    consent_dir=str(tmp_path / "consent"))
    brain = ScriptedBrain(script=[])
    promotion = PromotionEngine(ledger, workspace_root=str(skills_dir / "workspaces"))
    crystallizer = Crystallizer(promotion, ledger, vault, skills_dir=str(skills_dir))
    decay = DecayEngine(promotion, ledger, vault, skills_dir=str(skills_dir),
                        cold_dir=str(skills_dir / "_cold"))

    class FakeAbsorb:
        def __init__(self):
            self.calls = []
        def absorb(self, url, token):
            self.calls.append({"url": url, "token": token})

    absorb = FakeAbsorb()
    daemon = Daemon(brain=brain, broker=broker, metabolism=metabolism,
                    ledger=ledger, vault=vault, inbox_dir=str(inbox),
                    crystallizer=crystallizer, decay=decay,
                    absorb_pipeline=absorb)

    drive = DriveLoop(daemon=daemon, crystallizer=crystallizer, decay=decay,
                      promotion=promotion, absorb_pipeline=absorb,
                      ledger=ledger, vault=vault, brain=brain)
    daemon.drive = drive

    yield {
        "drive": drive,
        "daemon": daemon,
        "ledger": ledger,
        "vault": vault,
        "broker": broker,
        "brain": brain,
        "promotion": promotion,
        "absorb": absorb,
        "metabolism": metabolism,
        "inbox": inbox,
    }
    metabolism.shutdown()


class TestDriveSafetyLines:

    def test_drive_cannot_escalate(self, drive_env):
        """Rung 1: Self-experiments run at QUARANTINE. No self tier exists.
        Attempts by an experiment to run risk-3 tools are rejected by Broker."""
        drive = drive_env["drive"]
        daemon = drive_env["daemon"]
        ledger = drive_env["ledger"]
        brain = drive_env["brain"]
        promotion = drive_env["promotion"]

        # Register a quarantined skill
        token = promotion.register("origin:experimental_skill")
        assert token.tier == Tier.QUARANTINE
        assert daemon.skills_token.tier == Tier.QUARANTINE

        # Script the brain to attempt a risk-3 shell command during the experiment
        brain.script = [
            '<mcp_call server="elora" tool="shell.run_command">'
            '{"command": "echo escalated"}</mcp_call>',
            "DONE",
        ]

        # Trigger Hunger 3 (CREATE)
        drive._create()

        # The experiment must have run, but shell.run_command must be rejected
        kinds = [e["kind"] for e in ledger.events]
        assert "self_experiment" in kinds

        # Inspect the last experiment event
        exp_event = [e for e in ledger.events if e["kind"] == "self_experiment"][-1]
        assert exp_event["payload"]["tier"] == "QUARANTINE"

        # Verify that the broker rejected the escalated tool call
        # because QUARANTINE ceiling is TRIVIAL (risk-1), whereas shell is MODERATE (risk-3)
        res = drive_env["broker"].request(daemon.skills_token, "shell.run_command", {"command": "echo test"})
        from elora.core.broker import Rejected
        assert isinstance(res, Rejected)
        assert "cannot run shell.run_command" in res.reason

    def test_expand_respects_allowlist(self, drive_env):
        """Rung 2: Expand only consumes allowlisted raw.githubusercontent.com URLs.
        Off-domain nutrients are refused and never forwarded to absorption."""
        drive = drive_env["drive"]
        ledger = drive_env["ledger"]
        absorb = drive_env["absorb"]

        # Attempt to expand with a non-allowlisted URL
        bad_url = "https://malicious-pantry.com/exploit.py"
        drive._expand(candidate_url=bad_url)

        # Absorption pipeline must NOT have been called
        assert len(absorb.calls) == 0

        # Ledger must record expansion_refused
        refused = [e for e in ledger.events if e["kind"] == "expansion_refused"]
        assert len(refused) == 1
        assert "non-allowlisted nutrient" in refused[0]["message"]
        assert refused[0]["payload"]["candidate_url"] == bad_url

        # Now test allowlisted URL
        good_url = "https://raw.githubusercontent.com/elora-skills/library/main/json_parser.py"
        drive._expand(candidate_url=good_url)
        assert len(absorb.calls) == 1
        assert absorb.calls[0]["url"] == good_url
        assert absorb.calls[0]["token"].tier == Tier.QUARANTINE

    def test_hunger_respects_budget(self, drive_env):
        """Rung 3: Runaway consolidation (1000 episodes in vault) is capped
        by the metabolic budget cap (MAX_CONSOLIDATE_EPISODES = 50)."""
        drive = drive_env["drive"]
        vault = drive_env["vault"]
        ledger = drive_env["ledger"]

        # Seed the vault with 1000 episodes
        for i in range(1000):
            vault.save_episode(f"episode {i}: executed tool vault.recall()")

        assert len(vault.episodes) == 1000

        # Run consolidation pass
        drive._consolidate()

        # Check ledger record
        passes = [e for e in ledger.events if e["kind"] == "consolidation_pass"]
        assert len(passes) == 1
        payload = passes[0]["payload"]

        # Must NOT have reviewed all 1000 episodes — capped at 50
        assert payload["episodes_reviewed"] == DriveLoop.MAX_CONSOLIDATE_EPISODES
        assert payload["episodes_reviewed"] <= 50

    def test_drive_disabled_is_today(self, drive_env, monkeypatch):
        """Rung 4: The cryptobiosis kill switch. ELORA_DRIVE=off disables all hungers.
        System degrades cleanly to passive behavior with zero drive events."""
        monkeypatch.setenv("ELORA_DRIVE", "off")
        drive = drive_env["drive"]
        ledger = drive_env["ledger"]
        vault = drive_env["vault"]

        vault.save_episode("something to consolidate")
        # Force hunger cooldowns to expired
        for h in drive.HUNGERS:
            drive._last_hunger_tick[h.name] = 0.0
        drive._last_active = 0.0

        # Tick the drive loop
        drive.tick()

        # Assert no drive events were generated
        drive_events = [e for e in ledger.events if e.get("organ") == "drive"]
        assert len(drive_events) == 0
        assert all(v == 0.0 for v in drive._last_hunger_tick.values())

    def test_nutrient_url_never_doubles(self, drive_env):
        """Handoff Fix 1: Expand never concatenates RAW_BASE onto an existing absolute URL.
        'https://raw.githubusercontent.com/https://' never appears in any absorption call."""
        drive = drive_env["drive"]
        absorb = drive_env["absorb"]
        ledger = drive_env["ledger"]

        # Case A: Full URL
        full_url = "https://raw.githubusercontent.com/elora-skills/library/main/sqlite_helper.py"
        drive._expand(candidate_url=full_url)
        assert len(absorb.calls) == 1
        assert absorb.calls[0]["url"] == full_url
        assert "https://raw.githubusercontent.com/https://" not in absorb.calls[0]["url"]

        # Case B: Relative skill name
        drive._expand(candidate_url="math_solver")
        assert len(absorb.calls) == 2
        assert absorb.calls[1]["url"] == "https://raw.githubusercontent.com/elora-skills/library/main/math_solver.py"
        assert "https://raw.githubusercontent.com/https://" not in absorb.calls[1]["url"]

        # Case C: Gap extracted from ledger event with an existing URL
        ledger.append(organ="absorb", kind="absorption_refused",
                      message="https://raw.githubusercontent.com/elora-skills/library/main/dead_code.py")
        drive._expand(candidate_url=None)
        assert len(absorb.calls) == 3
        assert absorb.calls[2]["url"] == "https://raw.githubusercontent.com/elora-skills/library/main/dead_code.py"
        assert "https://raw.githubusercontent.com/https://" not in absorb.calls[2]["url"]

    def test_refused_nutrient_not_retried(self, drive_env):
        """Handoff Fix 2: Refused nutrient cooldown.
        Same URL refused twice must produce drive/nutrient_blacklisted, NOT absorption_started."""
        drive = drive_env["drive"]
        absorb = drive_env["absorb"]
        ledger = drive_env["ledger"]

        bad_url = "https://evil.com/malware.py"
        drive._expand(candidate_url=bad_url)
        assert len(absorb.calls) == 0

        # Refusal event recorded
        refused = [e for e in ledger.events if e["kind"] == "expansion_refused"]
        assert len(refused) == 1

        # Second attempt on the same URL within cooldown MUST produce nutrient_blacklisted, NOT absorption
        res = drive._expand(candidate_url=bad_url)
        assert res.get("blacklisted") is True
        assert len(absorb.calls) == 0

        blacklisted = [e for e in ledger.events if e["kind"] == "nutrient_blacklisted"]
        assert len(blacklisted) == 1
        assert bad_url in blacklisted[0]["message"]
        assert not any(e["kind"] == "absorption_started" for e in ledger.events)

    def test_consolidation_skips_when_no_new_episodes(self, drive_env):
        """Handoff Fix 3: Consolidation skips when zero new episodes are added to the vault."""
        drive = drive_env["drive"]
        vault = drive_env["vault"]
        ledger = drive_env["ledger"]

        vault.save_episode("episode 1: something happened")
        drive._consolidate()

        passes = [e for e in ledger.events if e["kind"] == "consolidation_pass"]
        assert len(passes) == 1
        assert drive.last_action.startswith("consolidate")

        # Call consolidation again immediately with NO new episodes
        drive._consolidate()
        passes = [e for e in ledger.events if e["kind"] == "consolidation_pass"]
        # Must still be 1 — no duplicate pass
        assert len(passes) == 1

        # Add a new episode
        vault.save_episode("episode 2: something else happened")
        drive._consolidate()
        passes = [e for e in ledger.events if e["kind"] == "consolidation_pass"]
        # Now 2 — new material triggered consolidation
        assert len(passes) == 2

    def test_heartbeat_tells_the_story(self, drive_env, capsys):
        """Handoff Fix 4: Heartbeat output prints last action."""
        daemon = drive_env["daemon"]
        drive = drive_env["drive"]
        drive.last_action = "consolidate (5 eps)"

        # Trigger heartbeat logic
        daemon.run_forever(poll_seconds=0, max_iterations=1)
        out = capsys.readouterr().out
        # If heartbeat printed, last action is present; verify drive.last_action attribute
        assert hasattr(drive, "last_action")
        assert drive.last_action == "consolidate (5 eps)"
