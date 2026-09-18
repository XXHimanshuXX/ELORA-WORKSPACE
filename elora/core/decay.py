"""
decay.py — the metabolic half of skills.

Skills that aren't used are archived, not deleted. The spec moves to
vault/skills/_cold/ and the binding (token, tier) is revoked via the
Promotion Engine. If the trigger fires again, the Crystallizer reads
the cold spec and rebuilds the binding — at QUARANTINE, as always.

Decay rules (per the v7 skill-statistics table):
  * success rate < 70% over last 20 uses  → demote one tier
  * unused for STALENESS_DAYS             → archive (binding revoked)
  * archive NEVER deletes the spec.md

Ring 1. Runs in the metabolism housekeeping pass — decay is
metabolism, so it lives where metabolism lives.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .crystallization import STALENESS_DAYS


@dataclass
class DecayDecision:
    skill_id: str
    action: str          # "archive" | "tier_demote" | "keep"
    reason: str


class DecayEngine:
    """The garbage collector that is also a librarian."""

    def __init__(self, promotion_engine, ledger, vault,
                 skills_dir: str = "vault/skills",
                 cold_dir: str = "vault/skills/_cold"):
        self.promotion = promotion_engine
        self.ledger = ledger
        self.vault = vault
        self.skills_dir = skills_dir
        self.cold_dir = cold_dir
        os.makedirs(cold_dir, exist_ok=True)

    def sweep(self) -> list[DecayDecision]:
        """One decay pass over all registered skills."""
        decisions = []
        now = time.time()

        for skill_id, rec in list(self.promotion.skills.items()):
            if now - rec.last_transition > STALENESS_DAYS * 86400 \
                    and rec.total_tasks == 0:
                decisions.append(self._archive(skill_id,
                    f"unused since {STALENESS_DAYS} days"))
            elif (rec.total_tasks >= 20
                  and rec.failures / max(1, rec.total_tasks) > 0.30):
                self.promotion.report_failure(skill_id, "decay: success<70%")
                decisions.append(DecayDecision(
                    skill_id, "tier_demote", "success rate below 70%"))
            else:
                decisions.append(DecayDecision(skill_id, "keep", ""))

        for d in decisions:
            if d.action == "archive":
                self.ledger.append(
                    organ="decay", kind="skill_archived",
                    message=d.skill_id, payload={"reason": d.reason},
                )
        return decisions

    def _archive(self, skill_id: str, reason: str) -> DecayDecision:
        """Move spec to cold storage, revoke binding. Spec survives."""
        src = os.path.join(self.skills_dir, f"{skill_id}.md")
        if os.path.exists(src):
            os.rename(src, os.path.join(self.cold_dir, f"{skill_id}.md"))
        rec = self.promotion.skills.get(skill_id)
        if rec:
            from elora.core.capabilities import Tier
            rec.tier = Tier.QUARANTINE
            rec.clean_streak = 0
        self.vault.save_episode(
            f"Skill {skill_id} archived: {reason}. Spec retained in _cold/."
        )
        return DecayDecision(skill_id, "archive", reason)

    def revive_from_spec(self, skill_id: str) -> bool:
        """
        The rebirth path: a cold skill's trigger fired again.
        Spec moves back from _cold/, binding re-registered fresh
        at QUARANTINE. The slime remembers WHAT, re-earns WHETHER.
        """
        cold = os.path.join(self.cold_dir, f"{skill_id}.md")
        if not os.path.exists(cold):
            return False
        os.rename(cold, os.path.join(self.skills_dir, f"{skill_id}.md"))
        self.promotion.register(origin=f"revived:{skill_id}")
        self.ledger.append(
            organ="decay", kind="skill_revived", message=skill_id,
        )
        return True
