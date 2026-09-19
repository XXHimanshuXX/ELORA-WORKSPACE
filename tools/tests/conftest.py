"""
conftest.py — fixtures for Ring 0 tests.

AIRPLANE TEST: this entire suite must pass with networking disabled.
Any test that needs the network is a bug in the test.
"""
import os
import tempfile
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from elora.core.metabolism import Metabolism, State
from elora.core.broker import Broker, SkillToken
from elora.core.capabilities import Tier


class FakeLedger:
    """In-memory ledger that records appends for inspection."""
    def __init__(self):
        self.events = []
    def append(self, organ, kind, message, payload=None):
        self.events.append({"organ": organ, "kind": kind,
                            "message": message, "payload": payload})
    def recent_events(self, kind=None, n=50):
        evs = self.events if kind is None else [e for e in self.events if e.get("kind") == kind]
        return evs[-n:]


class FakeVault:
    def __init__(self):
        self.episodes = []
    def save_episode(self, content):
        self.episodes.append(content)
    def get_recent_episodes(self, n=10):
        return self.episodes[-n:]


@pytest.fixture
def ledger():
    return FakeLedger()

@pytest.fixture
def vault():
    return FakeVault()

@pytest.fixture
def metabolism(tmp_path):
    # ram_hard_cap set explicitly: tests must not depend on the
    # CI machine's actual RAM. Determinism is inspection.
    m = Metabolism(cache_dir=str(tmp_path), ram_hard_cap_mb=16000)
    return m

@pytest.fixture
def broker(metabolism, ledger, vault, tmp_path):
    consent_dir = tmp_path / "consent"
    b = Broker(metabolism=metabolism, ledger=ledger, vault=vault,
               consent_dir=str(consent_dir))
    yield b
    metabolism.shutdown()

def token(tier: Tier, workspace: str) -> SkillToken:
    return SkillToken(skill_id="test-skill", tier=tier,
                      workspace=workspace, issued_at=0.0)