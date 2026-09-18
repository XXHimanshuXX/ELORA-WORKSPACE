"""
test_generation.py — WIRE-5 local image generation organ.
State.ARMED: 4200MB budget.

Five inspection rungs, no theater:
  1. test_generate_writes_file_and_hash — prompt "red circle" -> file exists + SHA recorded in ledger
  2. test_generate_budget_gated_by_metabolism — mock RAM 3000MB -> DEFERRED(ram_insufficient) not crash
  3. test_generate_mock_when_fastsd_absent — mock backend returns deterministic 1x1 png, backend=="mock"
  4. test_generate_path_jail — prompt tries ../../etc/passwd -> Broker schema rejects (path jail)
  5. test_generate_deterministic_seed — same prompt+seed -> same SHA, different seed -> different SHA
"""

import hashlib
import json
import os
import pytest
from PIL import Image

from elora.core.broker import Rejected, Deferred, Result, Broker
from elora.core.capabilities import Tier
from elora.core.metabolism import Metabolism, State
from elora.slime import generation
from elora.slime.generation import GenerationOrgan, MockBackend


@pytest.fixture
def probation_token(tmp_path):
    from conftest import token
    return token(Tier.PROBATION, str(tmp_path / "ws"))


@pytest.fixture
def quarantine_token(tmp_path):
    from conftest import token
    return token(Tier.QUARANTINE, str(tmp_path / "ws"))


# ----------------------------------------------------------------------
# RUNG 1 — Generate writes file and hash recorded in ledger
# ----------------------------------------------------------------------

def test_generate_writes_file_and_hash(broker, probation_token, ledger):
    result = broker.request(
        probation_token, "generate.image",
        {"prompt": "red circle", "seed": 42}
    )
    assert isinstance(result, Result)
    assert result.ok

    payload = json.loads(result.stdout)
    out_path = payload["path"]
    assert os.path.exists(out_path)

    with open(out_path, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()

    assert payload["sha256"] == actual_sha
    assert result.execution.stdout_sha256 == actual_sha

    # Check that Akashic ledger recorded capability_result with matching SHA
    result_event = next(e for e in ledger.events if e["kind"] == "capability_result" and e["message"] == "generate.image")
    assert result_event["payload"]["stdout_sha256"] == actual_sha


# ----------------------------------------------------------------------
# RUNG 2 — Budget gated by metabolism (mock RAM 3000MB -> Deferred)
# ----------------------------------------------------------------------

def test_generate_budget_gated_by_metabolism(tmp_path, ledger, vault, probation_token):
    # Simulated 3000MB RAM cap: headroom is 3000 - 1200 = 1800MB.
    # ARMED needs 4200MB (cost to reach is 4000MB), so it must DEFER.
    low_ram_metabolism = Metabolism(cache_dir=str(tmp_path / "meta"), ram_hard_cap_mb=3000)
    b = Broker(metabolism=low_ram_metabolism, ledger=ledger, vault=vault,
               consent_dir=str(tmp_path / "consent"))
    try:
        outcome = b.request(
            probation_token, "generate.image",
            {"prompt": "sunset on the horizon", "seed": 1}
        )
        assert isinstance(outcome, Deferred)
        assert outcome.reason == "ram_insufficient"
        assert outcome.needed_state == State.ARMED
    finally:
        low_ram_metabolism.shutdown()


# ----------------------------------------------------------------------
# RUNG 3 — Mock backend when fastsdcpu absent
# ----------------------------------------------------------------------

def test_generate_mock_when_fastsd_absent(tmp_path):
    organ = GenerationOrgan()
    res = organ.generate("glowing slime organism", seed=100)

    # When fastsdcpu is absent, MockBackend activates
    assert res["backend"] == "mock"
    assert os.path.exists(res["path"])
    assert len(res["sha256"]) == 64

    # Verify that the generated image is a valid 1x1 PNG
    with Image.open(res["path"]) as img:
        assert img.format == "PNG"
        assert img.size == (1, 1)


# ----------------------------------------------------------------------
# RUNG 4 — Path jail holds against traversal attacks
# ----------------------------------------------------------------------

def test_generate_path_jail(broker, probation_token):
    # Attempting to escape the generation root into arbitrary paths is rejected
    traversal_path = "../../etc/passwd"
    result = broker.request(
        probation_token, "generate.image",
        {"prompt": "malicious render", "path": traversal_path}
    )
    assert isinstance(result, Rejected)
    assert "approved roots" in result.reason or "not inside" in result.reason

    # Absolute system path also rejected
    sys_path = "C:/Windows/System32/hacked.png" if os.name == "nt" else "/etc/hacked.png"
    result2 = broker.request(
        probation_token, "generate.image",
        {"prompt": "malicious render 2", "path": sys_path}
    )
    assert isinstance(result2, Rejected)
    assert "approved roots" in result2.reason or "not inside" in result2.reason


# ----------------------------------------------------------------------
# RUNG 5 — Deterministic seed
# ----------------------------------------------------------------------

def test_generate_deterministic_seed():
    organ = GenerationOrgan()
    res1 = organ.generate("cybernetic organism", seed=42)
    res2 = organ.generate("cybernetic organism", seed=42)
    res3 = organ.generate("cybernetic organism", seed=99)

    # Same prompt + same seed must produce exact same SHA
    assert res1["sha256"] == res2["sha256"]
    # Different seed must produce different SHA
    assert res1["sha256"] != res3["sha256"]
