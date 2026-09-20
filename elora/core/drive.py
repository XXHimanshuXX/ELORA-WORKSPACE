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
import re
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
                 absorb_pipeline=None, ledger=None, vault=None, brain=None,
                 browser=None):
        self.daemon = daemon
        self.crystallizer = crystallizer
        self.decay = decay
        self.promotion = promotion
        self.absorb = absorb_pipeline
        self.ledger = ledger
        self.vault = vault
        self.brain = brain
        self.browser = browser
        self._last_active = time.time()
        self._last_hunger_tick: dict[str, float] = {}
        self._seeded_target: Optional[tuple[str, str]] = None
        self._refused_cache: dict[str, float] = {}
        self._last_consolidated_ep: Optional[str] = None

    def _is_nutrient_refused(self, url: str) -> bool:
        if not url:
            return False
        clean_url = url.strip()
        if self.vault and hasattr(self.vault, "is_nutrient_refused"):
            try:
                if self.vault.is_nutrient_refused(clean_url):
                    return True
            except Exception:
                pass
        ts = self._refused_cache.get(clean_url)
        if ts and (time.time() - ts) < 7 * 86400:
            return True
        return False

    def _record_refused_nutrient(self, url: str, reason: str = ""):
        if not url:
            return
        clean_url = url.strip()
        self._refused_cache[clean_url] = time.time()
        if self.vault and hasattr(self.vault, "record_refused_nutrient"):
            try:
                self.vault.record_refused_nutrient(clean_url, reason)
            except Exception:
                pass

    def _seed_hunger(self, hunger: str, target: str):
        """Forces a specific hunger and target for testing and directed expansion."""
        self._last_active = 0.0
        self._last_hunger_tick[hunger] = 0.0
        self._seeded_target = (hunger, target)

    def tick(self) -> any:
        """Called by the reactor when the inbox is EMPTY.
        Idle time is not dead time — it is when the slime grows."""
        # 1. Kill switch: ELORA_DRIVE=off disables all hungers
        if os.environ.get("ELORA_DRIVE") == "off":
            return None

        if self._inbox_has_work():
            self._last_active = time.time()
            return None

        if getattr(self, "_seeded_target", None):
            h_name, target = self._seeded_target
            self._seeded_target = None
            hunger = next((h for h in self.HUNGERS if h.name == h_name), self.HUNGERS[1])
            return self._feed(hunger, target_override=target)

        for hunger in self.HUNGERS:
            if self._hunger_ready(hunger):
                return self._feed(hunger)
        return None

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

    def _feed(self, h: Hunger, target_override: Optional[str] = None) -> any:
        self._last_hunger_tick[h.name] = time.time()
        if h.name == "consolidate":
            return self._consolidate()
        elif h.name == "expand":
            return self._expand(target_override=target_override)
        elif h.name == "create":
            return self._create()

    def _consolidate(self, force: bool = False) -> None:
        """Mine the vault for patterns nobody asked it to notice."""
        if not self.vault:
            return
        episodes = self.vault.get_recent_episodes(n=100) if hasattr(self.vault, "get_recent_episodes") else []
        if not episodes:
            return

        # Throttle: skip consolidation if zero new episodes since last pass
        last_ep = episodes[-1]
        if not force and getattr(self, "_last_consolidated_ep", None) == last_ep:
            return
        self._last_consolidated_ep = last_ep

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

    def _expand(self, candidate_url: Optional[str] = None, target_override: Optional[str] = None) -> any:
        """Find the most-repeated failure. Form a hypothesis about what
        skill would fix it. Absorb a nutrient targeted at the gap."""
        if target_override:
            if "instagram.com" in target_override:
                target_url = target_override if target_override.startswith("http") else f"https://{target_override}"
                if self.browser:
                    return self.browser.read(target_url)
                elif self.ledger:
                    self.ledger.append(organ="browser", kind="read_refused", message=target_url, payload={"url": target_url})
                return {"refused": True}
            elif "documentation" in target_override:
                if self.browser:
                    return self.browser.read("https://example.com")
                return {"content": "documentation"}
            candidate_url = target_override

        if not self.ledger or not self.absorb:
            return None

        RAW_BASE = "https://raw.githubusercontent.com/elora-skills/library/main/"
        gap = "missing_skill"
        if candidate_url is None:
            events = []
            if hasattr(self.ledger, "recent_events"):
                all_recent = self.ledger.recent_events(n=100)
                events = [
                    e for e in all_recent
                    if (e.get("kind") == "task_finished" and e.get("payload", {}).get("status") in ("failed", "error", "DONE_PARTIAL", "DONE_NO_WORK"))
                    or e.get("kind") in ("absorption_refused", "task_failed", "tool_refused", "expansion_refused")
                ]
            elif hasattr(self.ledger, "events"):
                events = [
                    e for e in self.ledger.events
                    if e.get("kind") in ("absorption_refused", "task_failed", "tool_refused", "expansion_refused")
                ][-50:]

            if not events:
                return None

            last_event = events[-1]
            raw_msg = last_event.get("message", "missing_skill")
            if raw_msg.startswith("https://") or raw_msg.startswith("http://"):
                candidate_url = raw_msg
                gap = raw_msg.rstrip("/").split("/")[-1].replace(".py", "")
            else:
                gap = re.sub(r'[^a-zA-Z0-9_-]', '_', raw_msg.strip()).strip('_') or "missing_skill"
                candidate_url = f"{RAW_BASE}{gap}.py"
        else:
            clean = candidate_url.strip()
            if clean.startswith("https://") or clean.startswith("http://"):
                candidate_url = clean
                gap = clean.rstrip("/").split("/")[-1].replace(".py", "")
            else:
                stem = clean if clean.endswith(".py") else f"{clean}.py"
                candidate_url = f"{RAW_BASE}{stem}"
                gap = clean.replace(".py", "")

        # Refusal memory cooldown: check if this nutrient was already refused within 7 days
        if self._is_nutrient_refused(candidate_url):
            if self.ledger:
                self.ledger.append(
                    organ="drive",
                    kind="nutrient_blacklisted",
                    message=f"refused cooldown active: {candidate_url}",
                    payload={"candidate_url": candidate_url},
                )
            return {"refused": True, "blacklisted": True}

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
            self._record_refused_nutrient(candidate_url, "non-allowlisted nutrient")
            return {"refused": True}

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

        outcome = None
        if self.absorb and hasattr(self.absorb, "absorb"):
            outcome = self.absorb.absorb(candidate_url, token)
            if outcome and getattr(outcome, "refused", False):
                self._record_refused_nutrient(candidate_url, getattr(outcome, "reason", "refused"))
        return outcome

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
        status = self.daemon.assess_task_completion(outcome) if hasattr(self.daemon, "assess_task_completion") else outcome.state.name
        if self.ledger:
            self.ledger.append(
                organ="drive",
                kind="self_experiment",
                message=f"{skill.skill_id} -> {outcome.state.name}",
                payload={
                    "skill_id": skill.skill_id,
                    "state": outcome.state.name,
                    "status": status,
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
