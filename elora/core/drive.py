"""
drive.py — the slime decides what to do when nobody is asking.

Hunger model: hunger accumulates while idle. Hunger is spent on
self-directed tasks. The three hungers, in priority order:

  HUNGER 1 — CONSOLIDATE (eat what it already caught)
      Review recent episodes. Find repeated patterns. Crystallize
      skills. Prune dead ones. Zero external input required.

      This is the slime growing in the dark.

  HUNGER 2 — EXPAND (eat what it knows it lacks)
      Read its own failed task records. Every Rejected/Deferred is
      a nutrient: 'I could not X'. Pick the failure most repeated,
      search its own skill library, and absorb a targeted nutrient.

  HUNGER 3 — CREATE (the fantasy, made operational)
      Pick a skill at QUARANTINE/PROBATION. Design a small
      self-experiment: a task whose success is self-verifiable,
      run through the Broker like any other task. Skills that
      succeed in self-experiments accrue evidence for promotion.
      The ten clean tasks are no longer human-supplied — the
      organism runs itself through its own curriculum.

Autonomy law: every self-directed task goes through the SAME
broker liturgy, the SAME tier ceilings, the SAME ledger. The slime
is a citizen of its own laws. Autonomy is not privilege.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Optional

from elora.core.capabilities import Tier, Risk, TIER_CEILING


@dataclass
class Hunger:
    name: str
    accumulate_rate: float      # per idle hour
    weight: float
    cooldown_s: int


class DriveLoop:
    HUNGERS = [
        Hunger("consolidate", accumulate_rate=1.0, weight=0.3, cooldown_s=300),
        Hunger("expand",      accumulate_rate=0.8, weight=0.5, cooldown_s=1800),
        Hunger("create",      accumulate_rate=0.5, weight=0.7, cooldown_s=3600),
    ]
    MAX_CONSOLIDATE_EPISODES = 50  # Hard metabolism limit per pass

    def __init__(self, daemon, crystallizer=None, decay=None, promotion=None,
                 absorb_pipeline=None, ledger=None, vault=None, brain=None):
        self.daemon = daemon
        self.crystallizer = crystallizer
        self.decay = decay
        self.promotion = promotion
        self.absorb = absorb_pipeline
        self.ledger = ledger
        self.vault = vault
        self.brain = brain
        self._last_active = time.time()
        self._last_hunger_tick: dict[str, float] = {}

    def tick(self) -> None:
        """Called by the reactor when the inbox is EMPTY.
        Idle time is not dead time — it is when the slime grows."""
        # 1. Kill switch: ELORA_DRIVE=off disables all hungers
        if os.environ.get("ELORA_DRIVE") == "off":
            return

        if self._inbox_has_work():
            self._last_active = time.time()
            return

        for hunger in self.HUNGERS:
            if self._hunger_ready(hunger):
                self._feed(hunger)
                break

    def _inbox_has_work(self) -> bool:
        if not hasattr(self.daemon, "inbox_dir") or not self.daemon.inbox_dir:
            return False
        if not os.path.exists(self.daemon.inbox_dir):
            return False
        try:
            return any(
                f.endswith(".txt") and not f.startswith(".")
                for f in os.listdir(self.daemon.inbox_dir)
            )
        except OSError:
            return False

    def _hunger_ready(self, h: Hunger) -> bool:
        now = time.time()
        if now - self._last_hunger_tick.get(h.name, 0) < h.cooldown_s:
            return False
        idle_hours = (now - self._last_active) / 3600
        prob = idle_hours * h.accumulate_rate * h.weight
        return random.random() < prob

    def _feed(self, h: Hunger) -> None:
        self._last_hunger_tick[h.name] = time.time()
        if h.name == "consolidate":
            self._consolidate()
        elif h.name == "expand":
            self._expand()
        elif h.name == "create":
            self._create()

    def _consolidate(self) -> None:
        """Mine the vault for patterns nobody asked it to notice."""
        if not self.vault:
            return
        episodes = self.vault.get_recent_episodes(n=100) if hasattr(self.vault, "get_recent_episodes") else []
        if not episodes:
            return

        # Metabolism cap: budget restricts runaway mining
        episodes_to_review = episodes[-self.MAX_CONSOLIDATE_EPISODES:]

        if self.crystallizer is not None:
            for ep in episodes_to_review[-10:]:
                if hasattr(self.crystallizer, "observe_text"):
                    self.crystallizer.observe_text(ep)

        if self.decay is not None and hasattr(self.decay, "sweep"):
            self.decay.sweep()

        if self.ledger is not None:
            self.ledger.append(
                organ="drive",
                kind="consolidation_pass",
                message=f"{len(episodes_to_review)} episodes reviewed",
                payload={
                    "episodes_reviewed": len(episodes_to_review),
                    "total_episodes": len(episodes),
                    "budget_cap": self.MAX_CONSOLIDATE_EPISODES,
                },
            )

    def _expand(self, candidate_url: Optional[str] = None) -> None:
        """Find the most-repeated failure. Form a hypothesis about what
        skill would fix it. Absorb a nutrient targeted at the gap."""
        if not self.ledger or not self.absorb:
            return

        gap = "missing_skill"
        if candidate_url is None:
            events = []
            if hasattr(self.ledger, "recent_events"):
                events = self.ledger.recent_events(kind="absorption_refused", n=50)
            elif hasattr(self.ledger, "events"):
                events = [
                    e for e in self.ledger.events
                    if e.get("kind") in ("absorption_refused", "task_failed", "tool_refused")
                ][-50:]

            if not events:
                return

            last_event = events[-1]
            gap = last_event.get("message", "missing_skill")
            candidate_url = f"https://raw.githubusercontent.com/elora-skills/library/main/{gap}.py"

        # Leash on eating: check allowlist
        # Must be strictly raw.githubusercontent.com
        if not candidate_url.startswith("https://raw.githubusercontent.com/"):
            if self.ledger:
                self.ledger.append(
                    organ="drive",
                    kind="expansion_refused",
                    message=f"non-allowlisted nutrient: {candidate_url}",
                    payload={"candidate_url": candidate_url},
                )
            return

        token = getattr(self.daemon, "skills_token", None)
        if token is None:
            token = getattr(self.daemon, "core_token", None)

        self.ledger.append(
            organ="drive",
            kind="expansion_target",
            message=f"hunting nutrient for: {gap}",
            payload={
                "candidate_url": candidate_url,
                "token_tier": token.tier.name if token else "UNKNOWN",
            },
        )

        if self.absorb and hasattr(self.absorb, "absorb"):
            self.absorb.absorb(candidate_url, token)

    def _create(self) -> None:
        """Pick an under-tiered skill. Design ONE self-verifiable task
        that uses it. Run it. Success accrues promotion evidence."""
        if not self.promotion or not hasattr(self.promotion, "skills"):
            return
        candidates = [
            s for s in self.promotion.skills.values()
            if s.tier.value < Tier.TRUSTED.value
        ]
        if not candidates:
            return

        skill = random.choice(candidates)
        experiment = self._design_experiment(skill)
        outcome = self.daemon.handle_task(experiment)
        if self.ledger:
            self.ledger.append(
                organ="drive",
                kind="self_experiment",
                message=f"{skill.skill_id} -> {outcome.state.name}",
                payload={
                    "skill_id": skill.skill_id,
                    "state": outcome.state.name,
                    "tier": skill.tier.name,
                },
            )

    def _design_experiment(self, skill) -> "Task":
        from elora.daemon import Task, Event
        text = f"Verify skill {skill.skill_id} self-check and reply with DONE"
        return Task(
            id=f"self-exp-{skill.skill_id}-{int(time.time()*1000)}",
            event=Event.from_text(text, source="drive:self_experiment"),
        )
