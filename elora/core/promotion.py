"""
promotion.py — the engine that earns trust.

A skill's tier is never given; it is earned:
    QUARANTINE  → PROBATION  → TRUSTED      (never CORE from here)

The ladder is deliberately one-way and evidence-driven:

    QUARANTINE  — enters with zero privileges (risk-1 only)
    PROBATION   — requires 10 consecutive clean quarantine tasks
    TRUSTED     — requires 20 more clean tasks AND success >= 90%
    Demotion    — automatic on any failure. One strike from TRUSTED
                  drops to PROBATION; one strike from PROBATION drops
                  to QUARANTINE. Trust is rebuilt, never begged.

Every transition is written to the Akashic ledger, so the tier of
every skill at every moment in history is verifiable.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

from .broker import SkillToken
from .capabilities import Tier


_NEXT_TIER = {
    Tier.QUARANTINE: Tier.PROBATION,
    Tier.PROBATION: Tier.TRUSTED,
    Tier.TRUSTED: Tier.TRUSTED,
    Tier.CORE: Tier.CORE,
}


@dataclass
class SkillRecord:
    skill_id: str
    tier: Tier
    clean_streak: int
    total_tasks: int
    failures: int
    created_at: float
    last_transition: float


class PromotionEngine:
    """
    Issues SkillTokens and tracks the evidence for each tier.

    Ring 1. The ONLY object in the system authorized to create a
    SkillToken with tier > QUARANTINE.
    """

    PROMOTION_CLEAN_STREAK = 10
    TRUST_CLEAN_STREAK = 20
    TRUST_SUCCESS_RATE = 0.90

    def __init__(self, ledger, workspace_root: str = ".elora/skills"):
        self.ledger = ledger
        self.workspace_root = workspace_root
        self.skills: dict[str, SkillRecord] = {}
        os.makedirs(workspace_root, exist_ok=True)

    def register(self, origin: str) -> SkillToken:
        """Register a new skill. It starts at QUARANTINE. Everyone does."""
        skill_id = f"skl_{uuid.uuid4().hex[:10]}"
        record = SkillRecord(
            skill_id=skill_id,
            tier=Tier.QUARANTINE,
            clean_streak=0,
            total_tasks=0,
            failures=0,
            created_at=time.time(),
            last_transition=time.time(),
        )
        self.skills[skill_id] = record
        self.ledger.append(
            organ="promotion", kind="skill_registered",
            message=skill_id, payload={"origin": origin},
        )
        return self.token_for(record)

    def token_for(self, record: SkillRecord) -> SkillToken:
        workspace = os.path.join(self.workspace_root, record.skill_id)
        os.makedirs(workspace, exist_ok=True)
        return SkillToken(
            skill_id=record.skill_id,
            tier=record.tier,
            workspace=workspace,
            issued_at=time.time(),
        )

    def report_success(self, skill_id: str):
        rec = self.skills.get(skill_id)
        if rec is None:
            return
        rec.clean_streak += 1
        rec.total_tasks += 1
        self._maybe_promote(rec)

    def report_failure(self, skill_id: str, reason: str = ""):
        rec = self.skills.get(skill_id)
        if rec is None:
            return
        rec.failures += 1
        rec.total_tasks += 1
        old_tier = rec.tier

        if rec.tier == Tier.TRUSTED:
            rec.tier = Tier.PROBATION
        elif rec.tier == Tier.PROBATION:
            rec.tier = Tier.QUARANTINE
        rec.clean_streak = 0
        rec.last_transition = time.time()
        if rec.tier != old_tier:
            self.ledger.append(
                organ="promotion", kind="skill_demoted",
                message=skill_id,
                payload={"from": old_tier.name, "to": rec.tier.name,
                         "reason": reason},
            )

    def _maybe_promote(self, rec: SkillRecord):
        if rec.tier == Tier.QUARANTINE:
            if rec.clean_streak >= self.PROMOTION_CLEAN_STREAK:
                self._promote(rec, Tier.PROBATION)
        elif rec.tier == Tier.PROBATION:
            success_rate = 1.0 - (rec.failures / max(1, rec.total_tasks))
            if (rec.clean_streak >= self.TRUST_CLEAN_STREAK
                    and success_rate >= self.TRUST_SUCCESS_RATE):
                self._promote(rec, Tier.TRUSTED)

    def _promote(self, rec: SkillRecord, target: Tier):
        old = rec.tier
        rec.tier = target
        rec.clean_streak = 0
        rec.last_transition = time.time()
        self.ledger.append(
            organ="promotion", kind="skill_promoted",
            message=rec.skill_id,
            payload={"from": old.name, "to": target.name},
        )

    def rebuild_from_ledger(self, events: list[dict]):
        """Crash recovery: replay promotion events to restore tiers."""
        for ev in events:
            if ev.get("kind") == "skill_promoted":
                rec = self.skills.setdefault(
                    ev["message"],
                    SkillRecord(ev["message"], Tier.QUARANTINE, 0, 0, 0,
                                time.time(), time.time()),
                )
                rec.tier = Tier[ev["payload"]["to"]]
            elif ev.get("kind") == "skill_demoted":
                rec = self.skills.setdefault(
                    ev["message"],
                    SkillRecord(ev["message"], Tier.PROBATION, 0, 0, 0,
                                time.time(), time.time()),
                )
                rec.tier = Tier[ev["payload"]["to"]]
