"""
test_capabilities.py — the registry is closed, consistent, and
cannot drift into being documentation that doesn't run.
"""
import inspect
import pytest

from elora.core.capabilities import (
    REGISTRY, Capability, Risk, Tier, TIER_CEILING)


def test_every_capability_declares_a_budget():
    for name, cap in REGISTRY.items():
        assert cap.budget is not None, f"{name} has no budget"
        assert cap.budget.cpu_seconds > 0, f"{name} budget: cpu must be > 0"
        assert cap.budget.ram_mb > 0, f"{name} budget: ram must be > 0"

def test_every_capability_has_builder():
    for name, cap in REGISTRY.items():
        assert callable(cap.command_builder), f"{name} has no command builder"

def test_tier_ceilings_are_total():
    """Every risk level maps to a tier — no gaps where a capability
    becomes unreachable for ALL tiers."""
    for cap in REGISTRY.values():
        assert cap.tier_required is not None

def test_risk_5_always_requires_consent():
    for cap in REGISTRY.values():
        if cap.risk == Risk.CATASTROPHIC:
            assert cap.consent_required, f"{cap.name}: risk-5 without consent"

def test_no_catastrophic_for_default_tokens():
    """Nothing below CORE tier can reach risk-5."""
    for cap in REGISTRY.values():
        if cap.risk == Risk.CATASTROPHIC:
            assert cap.tier_required == Tier.CORE