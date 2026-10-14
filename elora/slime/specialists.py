"""
elora.slime.specialists — Absorbed runtime specialists for ELORA OS.
Ported from NAVA-Agent (nava.agents.runtime) and ForgeOS kernel techniques.

Provides bounded, typed execution specialists:
  - CodingSpecialist: AST analysis, file manipulation, git operations, test repair.
  - TerminalSpecialist: DevOps shell execution, pytest execution, compiler diagnostics.
  - VerifierSpecialist: Invariant auditing, pre/post state delta verification, receipt signing.
  - ResearchSpecialist: Vault semantic memory RAG, document synthesis, web grounding.
  - BrowserSpecialist: DOM analysis, sanitization, page extraction, perception.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from elora.core.capabilities import Tier, Risk


@dataclass
class SpecialistTemplate:
    specialist_id: str
    name: str
    role: str
    tier: Tier
    risk_level: Risk
    permission_scope: List[str]
    system_prompt: str
    description: str
    icon: str = "chip"


SPECIALISTS: Dict[str, SpecialistTemplate] = {
    "coding": SpecialistTemplate(
        specialist_id="coding",
        name="Coding Specialist",
        role="Autonomous code synthesis, AST refactoring, and test-driven implementation",
        tier=Tier.TRUSTED,
        risk_level=Risk.LOW,
        permission_scope=[
            "fs.read", "fs.write", "git.status", "git.diff",
            "git.commit", "test.run", "ast.inspect"
        ],
        system_prompt=(
            "You are ELORA's Coding Specialist. Your goal is high-precision, production-grade "
            "code modifications. Never hallucinate functions or packages. Adhere to strict typing, "
            "comprehensive error handling, and existing workspace conventions. Always verify "
            "syntax and run tests before claiming success."
        ),
        description="High-precision code modifications, AST safety checks, and repo mutations.",
        icon="code",
    ),
    "terminal": SpecialistTemplate(
        specialist_id="terminal",
        name="Terminal Specialist",
        role="DevOps, environment diagnostics, test rungs, and build execution",
        tier=Tier.CORE,
        risk_level=Risk.MODERATE,
        permission_scope=[
            "proc.armored", "git.status", "test.run", "fs.read"
        ],
        system_prompt=(
            "You are ELORA's Terminal Specialist. You execute sandboxed shell operations, "
            "inspect process exit codes, run test suites, and diagnose environment or compiler "
            "failures with zero hallucination."
        ),
        description="Sandboxed terminal rungs, test execution, and compilation diagnostics.",
        icon="terminal",
    ),
    "verifier": SpecialistTemplate(
        specialist_id="verifier",
        name="Verifier Specialist",
        role="Invariant verification, pre/post state delta auditing, and ledger seal validation",
        tier=Tier.CORE,
        risk_level=Risk.TRIVIAL,
        permission_scope=[
            "fs.read", "ledger.inspect", "invariants.verify", "git.diff"
        ],
        system_prompt=(
            "You are ELORA's Verifier Specialist. Your role is adversarial invariant auditing. "
            "Inspect pre-execution snapshots against post-execution state deltas. Ensure no "
            "unauthorized files were touched, test rungs pass without warnings, and cryptographic "
            "receipts match Akashic ledger event chains."
        ),
        description="Adversarial invariant auditing, pre/post execution verification, and receipts.",
        icon="shield",
    ),
    "research": SpecialistTemplate(
        specialist_id="research",
        name="Research Specialist",
        role="Semantic memory retrieval, Obsidian vault search, and knowledge synthesis",
        tier=Tier.TRUSTED,
        risk_level=Risk.HIGH,
        permission_scope=[
            "net.fetch", "vault.read", "memory.rag", "fs.read"
        ],
        system_prompt=(
            "You are ELORA's Research Specialist. Synthesize factual knowledge across the "
            "Obsidian vault, downloaded papers, and verified network endpoints. Ground every "
            "claim with verifiable file paths and source citations."
        ),
        description="Hybrid RAG across vault skills, academic papers, and memory stores.",
        icon="search",
    ),
    "browser": SpecialistTemplate(
        specialist_id="browser",
        name="Browser Specialist",
        role="DOM analysis, content extraction, and perception feed grounding",
        tier=Tier.TRUSTED,
        risk_level=Risk.HIGH,
        permission_scope=[
            "net.fetch", "dom.sanitize", "browser.read", "fs.read"
        ],
        system_prompt=(
            "You are ELORA's Browser Specialist. Ingest and sanitize web content, extract "
            "structured documentation, and strip tracker scripts or malicious payload injections."
        ),
        description="Safe DOM ingestion, web page summarization, and content extraction.",
        icon="eye",
    ),
}


def list_specialists() -> List[Dict[str, Any]]:
    """Return serializable roster of all available runtime specialists."""
    result = []
    for s_id, s in SPECIALISTS.items():
        result.append({
            "id": s.specialist_id,
            "name": s.name,
            "role": s.role,
            "tier": s.tier.name,
            "risk_level": int(s.risk_level),
            "permission_scope": s.permission_scope,
            "description": s.description,
            "icon": s.icon,
        })
    return result


def route_will_to_specialist(will_text: str) -> SpecialistTemplate:
    """Intelligently map an incoming user will to the most appropriate runtime specialist."""
    text = (will_text or "").lower()

    if any(k in text for k in ["verify", "audit", "check invariant", "assert", "validate"]):
        return SPECIALISTS["verifier"]
    elif any(k in text for k in ["code", "refactor", "bug", "implement", "write file", "edit", "patch"]):
        return SPECIALISTS["coding"]
    elif any(k in text for k in ["run test", "pytest", "terminal", "bash", "shell", "compile", "build"]):
        return SPECIALISTS["terminal"]
    elif any(k in text for k in ["search", "find", "research", "paper", "arxiv", "vault", "memory"]):
        return SPECIALISTS["research"]
    elif any(k in text for k in ["http", "url", "web", "fetch", "scrape", "browse", "website"]):
        return SPECIALISTS["browser"]

    # Default to Coding Specialist for general task execution
    return SPECIALISTS["coding"]
