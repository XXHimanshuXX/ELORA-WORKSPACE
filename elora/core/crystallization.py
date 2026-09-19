"""
crystallization.py — traces become skills.

The pattern-recognition rule: when a task's execution trace shows
the same capability sequence 3+ times, the slime has learned a
habit. Habits, once named, become skills — and next time, Phase 1
(deterministic matching) skips the LLM entirely.

Zero tokens on second encounter is the entire economic thesis of
v7. This module is where that thesis is enforced.

Ring 1. Never raises to the daemon. Crystallization is an
optimization, not a dependency — if it fails, tasks run as before.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .capabilities import capability_names, REGISTRY


CRYSTALLIZE_THRESHOLD = 3     # occurrences before a pattern becomes a skill
STALENESS_DAYS = 30          # for decay (imported by decay.py)


@dataclass
class SkillCandidate:
    """A repeated capability sequence observed in real tasks."""
    signature: str                 # canonical: "shell.run_command|fs.write"
    occurrences: int
    example_args: dict            # last-seen args, for the spec doc
    first_seen: float
    last_seen: float


@dataclass
class SkillSpec:
    """The written skill — the artifact that survives decay."""
    skill_id: str
    trigger: str                  # the inbox-text pattern that fires it
    capability_sequence: list[str]
    spec_path: str
    sha256: str


class Crystallizer:
    """
    Watches task traces for repeated capability sequences and,
    when the threshold is crossed, writes the skill spec and
    registers a new skill with the Promotion Engine.

    Deliberately dumb: no LLM in this module. Pattern recognition
    is counting; counting is deterministic; deterministic is free.
    An LLM pass may LATER enrich the spec.md (fill in prose,
    failure modes) — but the birth of a skill never requires it.
    """

    def __init__(self, promotion_engine, ledger, vault,
                 skills_dir: str = "vault/skills"):
        self.promotion = promotion_engine
        self.ledger = ledger
        self.vault = vault
        self.skills_dir = skills_dir
        os.makedirs(skills_dir, exist_ok=True)

        # signature -> candidate
        self._candidates: dict[str, SkillCandidate] = {}

        # normalized trigger text -> signature, for Phase-1 matching
        self._trigger_index: dict[str, str] = {}

        # persisted skills we've already crystallized
        self._known: set[str] = set(self._load_known_signatures())
        self._specs: dict[str, SkillSpec] = {}

    # ------------------------------------------------------------------
    # Observation: called by the daemon after every task
    # ------------------------------------------------------------------

    def observe(self, task) -> None:
        """
        Feed a finished task's trace into the pattern counter.

        The trace format is whatever the daemon appended: a list of
        dicts with 'tool' keys in execution order. Malformed traces
        are skipped silently — crystallization must never be the
        reason a task fails.
        """
        try:
            self._observe_unsafe(task)
        except Exception:
            pass  # logged upstream in real build; never propagate

    def observe_text(self, text: str) -> None:
        """Observe episodic text directly for pattern consolidation."""
        words = re.findall(r"\b([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)\b", text)
        caps = [w for w in words if w in REGISTRY]
        if not caps:
            return
        class _PseudoEvent:
            payload = {"text": text}
        class _PseudoTask:
            event = _PseudoEvent()
            trace = [{"tool": c, "args": {}} for c in caps]
        try:
            self._observe_unsafe(_PseudoTask())
        except Exception:
            pass

    def _observe_unsafe(self, task) -> None:
        # Extract the ordered capability sequence from the trace
        sequence = []
        for step in task.trace:
            if isinstance(step, dict) and "tool" in step:
                name = step["tool"]
                if name in REGISTRY:               # real capabilities only
                    sequence.append(name)

        if not sequence:
            return

        signature = "|".join(sequence)

        # A skill for this signature already exists? Just note it.
        if signature in self._known:
            return

        cand = self._candidates.get(signature)
        now = time.time()
        if cand is None:
            self._candidates[signature] = SkillCandidate(
                signature=signature, occurrences=1,
                example_args=task.trace[-1].get("args", {}) if task.trace
                            and isinstance(task.trace[-1], dict) else {},
                first_seen=now, last_seen=now,
            )
        else:
            cand.occurrences += 1
            cand.last_seen = now

        if self._candidates[signature].occurrences >= CRYSTALLIZE_THRESHOLD:
            self._crystallize(signature, task)

    # ------------------------------------------------------------------
    # Birth: write the spec, register the skill
    # ------------------------------------------------------------------

    def _crystallize(self, signature: str, task) -> None:
        candidate = self._candidates[signature]
        trigger = self._derive_trigger(task)

        # Register with the Promotion Engine — QUARANTINE, like everything
        token = self.promotion.register(origin=f"crystallized:{signature}")

        # Write the spec — the part that survives decay
        spec_path = os.path.join(self.skills_dir, f"{token.skill_id}.md")
        spec_md = self._render_spec(trigger, signature, candidate, token)
        with open(spec_path, "w") as f:
            f.write(spec_md)
        try:
            from .wasm_gastric import compile_pure_add, write_skill_wasm
            write_skill_wasm(spec_path[:-3] + ".wasm", compile_pure_add())
        except Exception:
            pass

        spec = SkillSpec(
            skill_id=token.skill_id,
            trigger=trigger,
            capability_sequence=signature.split("|"),
            spec_path=spec_path,
            sha256=hashlib.sha256(spec_md.encode()).hexdigest(),
        )

        # Index for Phase-1 deterministic matching
        self._trigger_index[trigger] = signature
        self._known.add(signature)
        self._specs[signature] = spec

        self.ledger.append(
            organ="crystallizer", kind="skill_crystallized",
            message=token.skill_id,
            payload={
                "signature": signature,
                "trigger": trigger,
                "occurrences": candidate.occurrences,
                "spec_sha256": spec.sha256,
            },
        )
        self.vault.save_episode(
            f"Skill {token.skill_id} crystallized from pattern: {signature}"
        )

        # Candidate consumed; a new variant would need re-counting
        del self._candidates[signature]

    def _derive_trigger(self, task) -> str:
        """
        Derive a normalized trigger from the task text. v1 is honest
        and simple: lowercase, strip punctuation, keep content words.
        A trigger is a *match hint*, not a security boundary —
        the Broker still enforces everything on execution.
        """
        text = task.event.payload.get("text", "").lower()
        words = re.findall(r"[a-z0-9]+", text)
        return " ".join(words[:6]) or "unknown"

    def _render_spec(self, trigger, signature, candidate, token) -> str:
        lines = [
            f"# Skill {token.skill_id}",
            "",
            f"**Born:** {time.strftime('%Y-%m-%d %H:%M')} from "
            f"{candidate.occurrences} observed executions.",
            "",
            f"**Trigger pattern:** `{trigger}`",
            "",
            "**Capability sequence:**",
        ]
        for cap in signature.split("|"):
            desc = REGISTRY[cap].description if cap in REGISTRY else ""
            lines.append(f"1. `{cap}` — {desc}")
        lines += [
            "",
            "**Example args (last observed):**",
            "```json",
            repr(candidate.example_args),
            "```",
            "",
            "---",
            "Specs survive decay. Bindings do not. If this skill was "
            "archived, it can be rebuilt from this file.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Phase-1 matching: does a known skill fire for this inbox text?
    # ------------------------------------------------------------------

    def match(self, text: str) -> Optional[SkillSpec]:
        """
        Given incoming inbox text, return the skill whose trigger
        matches — or None, meaning the LLM must plan (Phase 2).

        This is the zero-token fast path. Deterministic. Free.
        """
        words = re.findall(r"[a-z0-9]+", text.lower())
        window = " ".join(words[:6])
        signature = self._trigger_index.get(window)
        matched = window
        if signature is None:
            for n in range(len(words), 0, -1):
                cand = " ".join(words[:n])
                signature = self._trigger_index.get(cand)
                if signature:
                    matched = cand
                    break
        if signature is None:
            return None
        if signature in self._specs:
            return self._specs[signature]
        for fname in os.listdir(self.skills_dir):
            path = os.path.join(self.skills_dir, fname)
            if not os.path.isfile(path):
                continue
            with open(path) as f:
                content = f.read()
            if f"**Trigger pattern:** `{matched}`" in content or \
               signature in content:
                skill_id = fname[:-3]
                return SkillSpec(
                    skill_id=skill_id,
                    trigger=matched,
                    capability_sequence=signature.split("|"),
                    spec_path=path,
                    sha256=hashlib.sha256(content.encode()).hexdigest(),
                )
        return None

    def _load_known_signatures(self) -> list[str]:
        """Rebuild the trigger index from disk at boot — cold-start
        recovery so crystallized skills survive daemon restarts."""
        signatures = []
        if not os.path.isdir(self.skills_dir):
            return signatures
        for fname in os.listdir(self.skills_dir):
            path = os.path.join(self.skills_dir, fname)
            try:
                with open(path) as f:
                    content = f.read()
                m = re.search(r"\*\*Capability sequence\*\*.*", content)
                sig_m = re.findall(r"`(\w+\.\w+)(?:\|)`", content)
                if sig_m:
                    signatures.append("|".join(sig_m))
            except OSError:
                continue
        return signatures