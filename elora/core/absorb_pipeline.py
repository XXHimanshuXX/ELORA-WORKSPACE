"""
absorb_pipeline.py — the slime eats.

The complete lifecycle, each step ledger-recorded:

    1. FETCH   net.fetch capability (allowlist: raw.githubusercontent.com)
    2. GATE    absorption_gate.digest() — AST allowlist, NEVER executes
    3. SPEC    synthesize spec.md from the DigestedCode contracts
    4. BIND    PromotionEngine.register() — QUARANTINE, like everything
    5. REMEMBER vault episode + akashic chain

Design rules:
  * Every rejection is a Deferred or Rejected with the gate's reason —
    the pipeline never crashes on bad food, it refuses it.
  * The original source is NEVER written to vault/skills. Only the
    spec survives. The code is digested, not kept.
  * Gate rejection is a SUCCESS for the pipeline: the membrane worked.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass

from .absorption_gate import digest, DigestedCode, GateReject


@dataclass
class AbsorptionOutcome:
    skill_id: str | None
    spec_path: str | None
    refused: bool
    reason: str
    source_sha256: str


class AbsorptionPipeline:

    def __init__(self, broker, promotion, ledger, vault,
                 skills_dir: str = "vault/skills"):
        self.broker = broker
        self.promotion = promotion
        self.ledger = ledger
        self.vault = vault
        self.skills_dir = skills_dir
        os.makedirs(skills_dir, exist_ok=True)

    def absorb(self, url: str, token) -> AbsorptionOutcome:
        """The full meal. Returns the outcome — never raises for
        bad content; raises only for infrastructure failure."""
        self.ledger.append(organ="absorb", kind="absorption_started",
                           message=url[:120])

        # -- 1. FETCH via the Broker (allowlist + budget enforced) --
        fetch_path = os.path.join(self.skills_dir, "_staging_source")
        result = self.broker.request(token, "net.fetch",
                                     {"url": url, "out_path": fetch_path})
        if not hasattr(result, "execution") or (result.execution and result.execution.returncode != 0) or getattr(result, "returncode", 0) != 0:
            reason = getattr(result, "reason", "")
            if not reason and hasattr(result, "execution") and result.execution:
                reason = result.execution.stderr or "fetch failed"
            elif not reason:
                reason = getattr(result, "stderr", "fetch failed")
            self._refused(url, f"fetch rejected: {reason}")
            return AbsorptionOutcome(None, None, True,
                                     f"fetch rejected: {reason}", "")

        try:
            with open(fetch_path, encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as e:
            self._refused(url, f"staging read error: {e}")
            return AbsorptionOutcome(None, None, True, f"staging read error: {e}", "")
        finally:
            if os.path.exists(fetch_path):
                try:
                    os.remove(fetch_path)          # never persist raw absorbed code
                except OSError:
                    pass

        sha = hashlib.sha256(source.encode("utf-8")).hexdigest()

        # -- 2. GATE --
        digested = digest(source, origin=url)
        if isinstance(digested, GateReject):
            self._refused(url, f"gate: {digested.reason}")
            return AbsorptionOutcome(None, None, True,
                                     digested.reason, sha)

        # -- 3. SPEC -- deterministic, zero tokens, survives decay --
        # -- 4. BIND -- QUARANTINE, like everything --
        skill_token = self.promotion.register(origin=f"absorbed:{url}")
        spec_path = os.path.join(self.skills_dir,
                                 f"{skill_token.skill_id}.md")
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(self._render_spec(url, digested, skill_token.skill_id))

        self.ledger.append(organ="absorb", kind="skill_absorbed",
                           message=skill_token.skill_id,
                           payload={"url": url, "source_sha256": sha,
                                    "functions": len(digested.functions)})
        self.vault.save_episode(
            f"Absorbed {url} → skill {skill_token.skill_id} "
            f"({len(digested.functions)} functions, "
            f"{len(digested.imports)} imports)")
        return AbsorptionOutcome(skill_token.skill_id, spec_path,
                                 False, "", sha)

    def _refused(self, url: str, reason: str):
        self.ledger.append(organ="absorb", kind="absorption_refused",
                           message=url[:120], payload={"reason": reason})
        self.vault.save_episode(f"Refused absorption of {url}: {reason}")

    def _render_spec(self, url, d: DigestedCode, skill_id: str) -> str:
        lines = [
            f"# Absorbed Skill {skill_id}",
            "",
            f"**Origin:** {url}",
            f"**Source SHA-256:** `{d.sha256}`",
            f"**Digested:** {time.strftime('%Y-%m-%d %H:%M')}",
            f"**Tier:** QUARANTINE (earned promotion, never granted)",
            "",
            "## Function contracts",
        ]
        for fn in d.functions:
            lines += [
                f"### `{fn['name']}({', '.join(fn['args'])})`",
                fn["doc"] or "*no docstring*",
                f"- calls: {', '.join(fn['calls']) or 'none'}",
                "",
            ]
        if d.imports:
            lines.append("## Imports requested")
            lines += [f"- `{i}`" for i in d.imports]
        lines += ["", "---", "The original source was digested and "
                   "discarded. This spec is the knowledge that remains."]
        return "\n".join(lines)
