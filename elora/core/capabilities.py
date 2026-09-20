"""
capabilities.py — The complete, closed list of what ELORA can do.

Blueprint rule: every capability declares Function, Dimensions,
Tolerance, Interface, Failure Mode, and Inspection — as code.

A model hallucinating a capability name gets a Rejected with the
real names in the message. The daemon injects this list into every
prompt (V4 lesson), AND the Broker re-validates. Belt and suspenders.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Sequence

from .armored_subprocess import Budget


class Risk(IntEnum):
    """1=trivial, 5=catastrophic. Tiers gate on this."""
    TRIVIAL = 1      # reading own vault, ledger verify
    LOW = 2          # writing to approved roots, local generation
    MODERATE = 3     # arbitrary shell (non-destructive), screen control
    HIGH = 4         # network egress
    CATASTROPHIC = 5 # destructive shell — dual-key consent


class Tier(IntEnum):
    """Skill trust ladder. QUARANTINE skills can only do trivial things."""
    QUARANTINE = 1
    PROBATION = 2
    TRUSTED = 3
    CORE = 4   # Ring 0/1 itself — never granted to absorbed code


# Tier ceilings: the highest Risk a tier may execute.
TIER_CEILING = {
    Tier.QUARANTINE: Risk.TRIVIAL,
    Tier.PROBATION: Risk.LOW,
    Tier.TRUSTED: Risk.MODERATE,
    Tier.CORE: Risk.CATASTROPHIC,
}


def _shell_argv(args: dict) -> list[str]:
    command = args.get("command", "true")
    if os.name == "nt":
        # Git/WSL bash cwd mapping is not the armored work_dir. cmd is native.
        return ["cmd", "/c", command]
    bash = shutil.which("bash") or "bash"
    return [bash, "-c", command]


@dataclass(frozen=True)
class Capability:
    name: str
    risk: Risk
    budget: Budget
    description: str
    command_builder: Callable[[dict], list[str]]
    env_gate: str | None = None
    consent_required: bool = False
    allowed_roots: tuple[str, ...] = ()
    net_allowlist: tuple[str, ...] = ()

    @property
    def tier_required(self) -> Tier:
        for tier, ceiling in sorted(TIER_CEILING.items()):
            if self.risk <= ceiling:
                return tier
        return Tier.CORE


@dataclass
class SkillToken:
    """Unified skill token. `id` aliases `skill_id` for older call sites."""
    skill_id: str
    tier: Tier
    workspace: str
    name: str = ""
    issued_at: float = 0.0
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = self.skill_id
        if not self.skill_id:
            self.skill_id = self.id
        if not self.name:
            self.name = self.skill_id or self.id


REGISTRY: dict[str, Capability] = {}


def _register(cap: Capability) -> Capability:
    assert cap.name not in REGISTRY, f"duplicate capability: {cap.name}"
    REGISTRY[cap.name] = cap
    return cap


def _py(*parts: str) -> list[str]:
    return [sys.executable, "-m", *parts]


# --- Risk 1: Trivial ---------------------------------------------------

_register(Capability(
    name="vault.recall",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Recall recent episodic memory from the vault",
    command_builder=lambda a: _py("elora.vault", "--recall", str(a.get("n", 5))),
))

_register(Capability(
    name="rag.recall",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Recall semantic memory chunks matching query from RAG index",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.rag",
        "--query", a.get("query", a.get("q", a.get("text", a.get("prompt", a.get("arg", ""))))),
        "--n", str(a.get("n", 5)),
    ],
))

_register(Capability(
    name="vault.save",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Persist an episodic memory into the vault",
    command_builder=lambda a: _py("elora.vault", "--save", a.get("content", "")),
))

_register(Capability(
    name="ledger.verify",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Verify the Akashic hash chain integrity",
    command_builder=lambda a: _py("elora.organs.akashic", "--verify"),
))

_register(Capability(
    name="inbox.poll",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Poll the inbox for new tasks (CRYPTOBIOSIS-safe)",
    command_builder=lambda a: _py("elora.daemon", "--poll"),
))

_register(Capability(
    name="schedule.tick",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Advance the scheduler one tick",
    command_builder=lambda a: _py("elora.core.schedule", "--tick"),
))

_register(Capability(
    name="screen.capture",
    risk=Risk.TRIVIAL,
    budget=Budget.MICRO(),
    description="Capture a screenshot for perception (no control)",
    command_builder=lambda a: _py(
        "elora.slime.computer_use", "--action", "capture",
        "--out", a.get("out_path", "")),
    allowed_roots=(".elora/screenshots", os.path.abspath(".elora/screenshots"),
                   os.path.abspath("vault"), "/tmp/.elora"),
))

# --- Risk 2: Low -------------------------------------------------------

_register(Capability(
    name="fs.write",
    risk=Risk.LOW,
    budget=Budget.MICRO(),
    description="Write a file to an approved root (/tmp/.elora, vault/, .elora/)",
    command_builder=lambda a: _py(
        "elora.core.fs_writer", "--dest", a["path"], "--mode", "0644"),
    allowed_roots=("/tmp/.elora", os.path.abspath(".elora"),
                   os.path.abspath("vault")),
))

_register(Capability(
    name="generate.image",
    risk=Risk.LOW,
    budget=Budget.GENERATE(),
    description="Generate an image via local model or paid API",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.generation_api",
        "--prompt", a.get("prompt", ""),
        "--out", a.get("path", a.get("out_path", "out.png")),
    ],
    allowed_roots=(".elora/generations", os.path.abspath(".elora/generations"),
                   os.path.abspath("vault"), "/tmp/.elora"),
))

_register(Capability(
    name="net.read",
    risk=Risk.TRIVIAL,
    budget=Budget.SKILL(),
    description="Read a webpage into structured memory. Respects robots.txt. Never solves CAPTCHAs.",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.browser",
        "--action", "read", "--url", a.get("url", a.get("link", a.get("uri", ""))),
    ],
))

_register(Capability(
    name="net.search",
    risk=Risk.LOW,
    budget=Budget.SKILL(),
    description="Web search via bot-friendly HTML endpoints",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.browser",
        "--action", "search", "--query", a.get("query", ""),
    ],
))

_register(Capability(
    name="doc.ingest",
    risk=Risk.TRIVIAL,
    budget=Budget.DIGEST(),
    description="Ingest a local file (pdf/image/video/text) into memory",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.ingest",
        "--path", a.get("path", a.get("file_path", a.get("file", a.get("filepath", "")))),
    ],
))

# --- Risk 3: Moderate --------------------------------------------------

_register(Capability(
    name="shell.run_command",
    risk=Risk.MODERATE,
    budget=Budget.SKILL(),
    description=(
        "Execute a shell command through the guarded MCP shell server. "
        "Destructive patterns are refused by pattern guard. This is a "
        "guardrail, not a sandbox — the armored runner provides the cage."
    ),
    command_builder=_shell_argv,
))

_register(Capability(
    name="screen.control",
    risk=Risk.MODERATE,
    budget=Budget.SKILL(),
    description="Tier0 UIA/pywinauto click and type — zero token UIA rectangles",
    command_builder=lambda a: [
        sys.executable, "-m", "elora.slime.computer_use",
        "--action", a.get("action", "click"),
        "--x", str(a.get("x", 0)),
        "--y", str(a.get("y", 0)),
        "--text", a.get("text", ""),
        "--target", a.get("target", ""),
    ],
    env_gate="ELORA_ALLOW_CONTROL",
))

_register(Capability(
    name="llm.local_inference",
    risk=Risk.MODERATE,
    budget=Budget.SKILL(),
    description="Local LLM completion via the AWAKE organ (Ollama / BitNet)",
    command_builder=lambda a: _py("elora.brain", "--complete"),
))

_register(Capability(
    name="voice.listen",
    risk=Risk.LOW,
    budget=Budget.ALERT(),
    description="ASR listen via the ALERT organ",
    command_builder=lambda a: _py("elora.slime.voice", "--listen", "--seconds", str(a.get("seconds", 5))),
))

_register(Capability(
    name="voice.speak",
    risk=Risk.LOW,
    budget=Budget.ALERT(),
    description="TTS speak via the ALERT organ",
    command_builder=lambda a: _py(
        "elora.slime.voice", "--speak", a.get("text", ""),
        "--out", a.get("out_path", a.get("path", ""))),
    allowed_roots=(".elora/voice", os.path.abspath(".elora/voice"),
                   os.path.abspath("vault"), "/tmp/.elora"),
))

_register(Capability(
    name="slime.absorb",
    risk=Risk.MODERATE,
    budget=Budget.DIGEST(),
    description="Absorb foreign source into the gastric gate (never executes it)",
    command_builder=lambda a: _py(
        "elora.core.absorption_gate", "--origin", a.get("origin", "")),
))

_register(Capability(
    name="slime.digest",
    risk=Risk.MODERATE,
    budget=Budget.DIGEST(),
    description="Digest absorbed source into a skill spec (AST gastric gate)",
    command_builder=lambda a: _py("elora.core.absorption_gate", "--digest"),
))

# --- Risk 4: High ------------------------------------------------------

_register(Capability(
    name="net.fetch",
    risk=Risk.HIGH,
    budget=Budget.MICRO(),
    description=(
        "Fetch a URL. Used by absorption (raw.githubusercontent.com). "
        "Domain allowlist enforced in the handler, not by convention."
    ),
    command_builder=lambda a: _py(
        "elora.core.net_fetch", "--url", a.get("url", ""),
        "--out", a.get("out_path", "")),
    net_allowlist=("raw.githubusercontent.com",),
))

# --- Risk 5: Catastrophic ----------------------------------------------

_register(Capability(
    name="shell.run_destructive",
    risk=Risk.CATASTROPHIC,
    budget=Budget.SKILL(),
    description="Shell with destructive-pattern guard disabled. Dual-key consent.",
    command_builder=_shell_argv,
    consent_required=True,
    env_gate="ELORA_ALLOW_DESTRUCTIVE",
))


def capability_names() -> list[str]:
    """Injected into every system prompt. Real names, one line each."""
    return [f"{c.name} (risk {int(c.risk)}, {c.description[:60]})"
            for c in REGISTRY.values()]
