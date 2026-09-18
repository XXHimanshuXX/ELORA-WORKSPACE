# ELORA OS — TRUE BLUEPRINT v7 UPGRADE
## Slime OS v2: Absorbs Everything, Fakes Nothing, Free Forever, Wires Everything

**Version:** v7 UPGRADE | **Predecessor:** v6 FINAL (honest but unwired museum) | **Mission:** Close the loop — every claim reachable from `daemon.poll_inbox()` in one task iteration or it doesn't exist

> v6 fixed fakeness. v7 fixes wiring debt. v6 had 7 of 9 Next Steps as "wiring tasks." v7 Rule Zero: A subsystem not reachable from daemon.poll_inbox() within one task loop iteration does not exist and must not appear in Working tables.

---

## 1. THE CENTRAL DIAGNOSIS (What v6 Actually Got Wrong)

| Component | v6 State | Consequence | v7 Verdict |
|-----------|----------|-------------|------------|
| Scheduler SemanticScheduler | Working, not wired | Urgency is theater — FIFO in practice | Must be WIRE-1 |
| Perception UnifiedPerceptionStream | Code complete, not wired | OS is deaf/blind | Must be wired via Event model |
| computer_use Tier0 pywinauto UIA | Built, not wired | Token burn on every click — re-parses screen via LLM | WIRE-3 immediate token savings |
| Slime absorption absorption.py | Built, not wired | Flagship metaphor doesn't run in task loop — prose only | WIRE-4 proves slime is real |
| generation.py FastSD+ModelScope | Built, not wired | "Thinks itself" only in prose — no tool list entry | WIRE-5 |
| voice.py sherpa-onnx 110ms | Built, not wired | 400MB RAM idle for nothing | WIRE-6 heaviest last |
| Kernel router | Working, needs Ollama | No Ollama = no routing = no task | Airplane Test will force local fallback |

**Disease Name:** Wiring Debt. You can build real subsystems but 7 Next Steps are wiring tasks. The system reports "Working" but task loop can't reach it.

**v7 Rule Zero (Enforceable):** Introduce Wiring Milestone Gate before any new feature. `python run.py --task smoke --brain fake` must green or feature does not ship. No feature merges if rung red.

---

## 2. THE WIRING KERNEL — #1 Priority (Everything Else Secondary)

### Honest Dependency Order (Smallest diff, biggest behavioral win first)

```
WIRE-2: FakeBrain → daemon test harness   (1 day, unlocks CI without model) — HIGHEST LEVERAGE
WIRE-1: SemanticScheduler → daemon        (3 days, unlocks preemption)
Security gate v2: Allowlist AST + rlimits + quarantine tiers (2 days, security before growth)
Minimal Core / Fat Shell split (3 days, refactor before more shell grows)
WIRE-3: computer_use Tier0 → brain tools  (2 days, saves tokens immediately)
RAM budget enforcement in CI (1 day, protects trash-laptop target)
WIRE-4: absorption.py → URL handler       (3 days, proves slime is real)
WIRE-5: generation.py → tool list        (2 days)
WIRE-6: voice.py → perception.py         (5 days, heaviest — last)
Council/dual-ledger + Tauri overlay      (decoration until loop is wired — last)
```

### WIRE-2: ScriptedBrain — Highest Leverage Single Change (Do First)

**v6's own words:** "Injecting a fake Brain would make it testable without live model."

**Concrete:**

```python
# elora/brain_fake.py — Replays deterministic <mcp_call> scripts
# Enables full task-loop CI on 8GB laptop with no Ollama, no network, no GPU

from dataclasses import dataclass

@dataclass
class ScriptedBrain:
    """Replays deterministic <mcp_call> scripts. Enables full task-loop
    CI on an 8GB laptop with no Ollama, no network, no GPU."""
    script: list[str]  # each entry is full model reply with <mcp_call> blocks
    idx: int = 0

    def complete(self, prompt: str, context: dict) -> str:
        if self.idx >= len(self.script):
            return "DONE"
        out = self.script[self.idx]
        self.idx += 1
        return out

# Example script for smoke test
SMOKE_SCRIPT = [
    # Turn 1: LLM proposes shell command
    '''PLAN: list files
<mcp_call server="shell" tool="run_command">
{"command": "ls -la > /tmp/out.txt"}
</mcp_call>''',
    # Turn 2: LLM says DONE after seeing result
    "DONE: listed files"
]
```

**Why this de-risks everything:**
- `tools/verify.py` grows from 21 checks to covering daemon end-to-end: task claim → tool call → shell execution → vault save → akashic append → DONE
- Inspection plan becomes automated instead of "manual end-to-end runs"
- Enables Airplane Test: `run.py --check --offline` must pass 100% with networking disabled
- Enables Wiring Gate: `python run.py --task smoke --brain fake` full loop green with zero network, zero model

**Inspection:** `pytest tests/test_daemon_loop.py --brain fake` — must green before WIRE-1.

---

## 3. SECURITY HARDENING (v6's Biggest Blind Spot)

v6 admits shell guard is "guardrail not sandbox." Good honesty. Bad engineering posture for agent that injects absorbed GitHub code into live RAM via `importlib._bootstrap._exec()` with banned-list. Banned-lists fail; allowlists survive.

### 3.1 Allowlist the AST (not banlist)

```python
# elora/core/safety_gate.py — Allowlist, not banlist

ALLOWED_NODES = {
    ast.Expr, ast.Assign, ast.AnnAssign, ast.AugAssign,
    ast.Call, ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp,
    ast.FunctionDef, ast.Return, ast.If, ast.For, ast.While, ast.Try,
    ast.ExceptHandler, ast.With, ast.List, ast.Dict, ast.Tuple,
    ast.Subscript, ast.Attribute, ast.Compare, ast.BoolOp,
    ast.ListComp, ast.DictComp, ast.Import, ast.ImportFrom  # but filtered
}

BANNED_IMPORTS = {
    "os", "sys", "subprocess", "socket", "shutil", "ctypes",
    "importlib", "builtins", "pathlib", "requests", "urllib",
    "http", "ftplib", "pty", "posix", "pwd", "grp"
}

BANNED_ATTRS = {
    "__import__", "__builtins__", "__class__", "__bases__", "__subclasses__",
    "open", "exec", "eval", "compile", "__dict__", "__globals__", "mro"
}

# Also: deny attribute chains — x.__class__.__bases__ escapes are classic hole
def check_attr_chain(node: ast.Attribute) -> bool:
    chain = []
    cur = node
    while isinstance(cur, ast.Attribute):
        chain.append(cur.attr)
        cur = cur.value
    # If chain contains any banned attr at any depth → reject
    return not any(b in chain for b in BANNED_ATTRS)
```

### 3.2 Resource Limits on Subprocess (Quantified, Blueprint-Style)

| Dimension | Nominal | Tolerance | Enforcement | Inspection |
|-----------|---------|-----------|-------------|------------|
| Absorbed-code CPU | 10s | hard kill | `resource.setrlimit(RLIMIT_CPU, (10,10))` | `test_escape` subprocess killed, ledger records |
| Absorbed-code RAM | 512MB | hard kill | `RLIMIT_AS` 512MB | OOM killed, daemon survives |
| Filesystem writes | `vault/skills/` only | fail if outside | seccomp / `RLIMIT_FSIZE` + chroot jail to `.elora/quarantine/` | attempt write to `/etc/` → refused + logged |
| Network | zero | fail | subprocess with no proxy env + `RLIMIT_NOFILE` + `unshare -n` | attempt socket → killed |
| Process spawn | zero | fail | `RLIMIT_NPROC` 0 + seccomp filter | attempt fork → killed |

### 3.3 Multi-sig for Dangerous Skills

Any skill marked `capability: shell-destructive` or `capability: net-write` requires two approvals:
1. Curator GC passes it (automated)
2. Human consents via `inbox/consent.txt` (human)

This makes "consent protocol" a real dimension, not a phrase. Implementation: skill file has frontmatter `risk: 5`, broker checks tier + consent file existence + timestamp <24h.

### 3.4 Quarantine Tier, Not Binary

Absorbed skills enter lifecycle:

```
QUARANTINE (subprocess-only, 10 tasks) → PROBATION (sandbox + logging) → TRUSTED (direct)
```

- Promotion automatic only if all 10 quarantine tasks pass inspection
- Demotion is one ledger event: success rate <70% over 20 uses → demote to QUARANTINE
- Akashic chain records tier transitions, so skill provenance is tamper-evident
- Decay: unused 30 days → archive to `vault/skills/_cold/`, invocation cost >2s → flag for optimization in journal

---

## 4. HONEST DIMENSION CORRECTIONS (v6 Numbers That Won't Survive 8GB Laptop)

| v6 Claim | Reality Check | v7 Correction | Blueprint Principle |
|----------|---------------|---------------|---------------------|
| ModelScope 1.7b video, "8GB RAM" | ModelScope 1.7b needs ~8GB for model alone + ffmpeg + OS = >12GB | Mark as **16GB-only feature**. On 8GB: image-slideshow + TTS + ffmpeg path only. Gate behind `--capability-check` at boot | Dimension tables must be measured on 8GB trash laptop, or labeled dev-machine-only |
| FastSD CPU "10s 512x512" | True on i7-12700. On trash laptop Celeron N4020: 30-90s | Tolerance: **30s +90s on trash hardware**. Inspection must run on target, not dev machine | Target-machine measurement mandate |
| Voice loop 110ms | VAD 10ms + ASR 50ms + TTS 60ms ignores model load, VAD windowing, audio buffer jitter | Nominal **250ms end-to-end**, tolerance +150ms. Don't load ASR until wakeword fires — saves ~400MB idle RAM critical on 8GB | RAM budget written before wiring |
| Idle RAM <500MB | Currently true because perception/voice/scheduler aren't wired | Post-wiring budget: **700MB nominal, 900MB hard cap**. Write it down now so wiring decisions are made under real constraint | Write budget before wiring |

**v7 Blueprint Principle:** Dimension tables must be measured on 8GB trash laptop, or labeled dev-machine-only. No dev-machine numbers in final spec.

**Post-Wiring RAM Budget (Enforced in CI):**
- ALIVE Core daemon + SQLite + ledger: 200MB Always
- AWAKE + Ollama 3B model: +1GB (total 1.2GB)
- ALERT + ASR/TTS loaded: +600MB (total 1.8GB — exceeds 8GB laptop, must queue)
- ARMED + FastSD: +3GB (total 4.2GB — 8GB laptop can do this alone, not with AWAKE)
- DIGESTING + absorption subprocess: +700MB
- CRYPTOBIOSIS Core only event polling: 50MB (shed fat shell, wakes on inbox event)

---

## 5. THE BOOTSTRAP PARADOX FIX (Slime Needs a Slime)

**Problem:** v6 says seed is "3K lines" and slime grows by absorbing. But who absorbs into ELORA the ability to absorb? If absorption.py has bug, system can't self-repair.

**v7 Solution: Minimal Core / Fat Shell Architecture**

```
╔══════════════════════════════════════════════════╗
║  RING 0 — CORE (immutable, human-committed only)  ║
║  daemon loop · capability broker · ledger · vault ║
║  ~1,500 lines. Frozen. Tested to death.          ║
║  Rule: core cannot absorb; only modified by human ║
║  pull requests. git diff --stat elora/core/ must ║
║  match signed commit or CI fails.                ║
╠══════════════════════════════════════════════════╣
║  RING 1 — KERNEL SERVICES (wired, cap-gated)       ║
║  scheduler · router · shell MCP · safety gate     ║
║  memory · perception pipeline                     ║
╠══════════════════════════════════════════════════╣
║  RING 2 — SLIME (absorbed, quarantined, mutating)  ║
║  skills · generation · computer use · absorbed code║
║  Enters QUARANTINE → PROBATION → TRUSTED          ║
╚══════════════════════════════════════════════════╝
```

This kills "malicious skill corrupts safety gate" attack class structurally instead of heuristically. Core is boring, small, heavily tested. Fat shell is where slime growth lives.

---

## 6. SKILL CRYSTALLIZATION — Add Decay Half (Metabolism)

v6 has Curator GC for bad skills. Missing: entropic decay for unused ones. v7 adds per-skill ledger statistics:

| Metric | Source | Decay Rule | Slime Analogy |
|--------|--------|------------|---------------|
| Success rate | akashic events | <70% over 20 uses → demote to QUARANTINE | Indigestion |
| Usage recency | vault episodes | unused 30 days → archive to vault/skills/_cold/ | Excretion |
| Invocation cost | router | skill consistently >2s → flag for optimization in journal | Slow metabolism |
| RAM peak | broker | skill >256MB → require ARMED state | Heavy meal |

**Skills aren't just collected — they're metabolized. Real slime digestion: absorb → use → keep what works → excrete the rest.**

- Skill file annotated with decay rationale: "Skill 'blender-headless' unused 60d, success rate 40%. Demoted."
- Code archived, not deleted
- Spec retained even when code gone — next time task appears, slime remembers spec and rebuilds. Slime knows what it used to know.

---

## 7. PHILOSOPHICAL FOUNDATION v7 — First Principles

### 7.1 First Law: The Daemon is Brain, LLM is Sense Organ

**Every AI OS fails at same place:** They treat LLM as OS. Model is kernel! LLM thinks! LLM routes! LLM decides!

**Why this is deepest mistake:** LLM is stateless function approximator with 2-second memory. Making it OS means:
- Forgets everything every 200 tokens
- Hallucinates own API ("execute_command" not "run_command" — V4 bug)
- Burns tokens (money) to think about what to do
- No realtime guarantee (scheduler can't preempt if preemption requires 3-second inference)

**Correct Architecture:** LLM is peripheral. Slow, expensive, brilliant-but-amnesiac consultant that actual OS (deterministic Python code) consults only when needed.

**v7 First Law:** The model is not the brain. The daemon is the brain. The model is a sense organ — expensive, brilliant, unreliable one. You don't let your eyes do arithmetic.

**V4 disaster through this lens:** Fake Blender launch happened because system treated LLM output as ground truth. elora.py trusted what model said. Fix isn't just verify outputs — fix is LLM never has authority in first place. It proposes; deterministic core disposes. Every decision model makes is suggestion that daemon validates, executes, measures, judges.

### 7.2 Slime Metaphor, Taken Seriously

| Slime Property | ELORA v7 Implementation |
|----------------|-------------------------|
| Decentralized nervous system (no brain, nerve net) | Daemon is nerve net; LLM is chemosensor consulted occasionally |
| Enthusiastic pseudopod contact | Absorption: everything system touches it first extends probe (safe subprocess) at |
| Osmotically driven | Skills flow along concentration gradients — from high need (failing task) to low need (archive). Memory flows same way |
| Consumes only what fits its membrane | Capability membrane — hard, small, audited API surface between core and everything else |
| Regenerates from fragments | Entire system state is SQLite + git + ledger. Destroy any two subsystems; rebuild from journal replay |
| Suspends (cryptobiosis) when starved | RAM-starvation mode: shed fat shell, core sleeps in 50MB, wakes on inbox event |
| Digestion = destruction + rebuilding | Skill digestion: absorbed code never run as-is. Transformed into skill document + validated callable, original discarded |

Last one changes absorption design fundamentally.

### 7.3 Second Law: Free Forever Is Protocol, Not Budget Line

**v6:** Free forever = no API keys.
**v7:** Free forever = provable to work with network cable unplugged.

**v7 Second Law (Airplane Test):** `python run.py --check --offline` and `tools/verify.py` must pass 100% with networking disabled. Anything needing network is plugin that degrades gracefully, never dependency.

This cascades: forces local models, forces offline-first skills, forces absorption pipeline to cache, forces test harnesses to be hermetic. Makes system unjammable. Anyone can run ELORA on plane, bunker, country with internet shutdown. Not feature — political statement.

---

## 8. KERNEL REDESIGN v7 — Capability Membrane

### 8.1 Three Rings (Formal Capability System)

```python
# elora/core/broker.py — THE ONLY file that grants power

from dataclasses import dataclass

@dataclass(frozen=True)
class Capability:
    name: str
    risk: int  # 1=trivial, 5=catastrophic
    tier_required: str  # QUARANTINE, PROBATION, TRUSTED
    budget: dict  # {cpu_s, ram_mb, net: bool}
    inspection: str  # test that proves it

class Broker:
    """All Ring-2 code receives Token, never real objects."""
    def request(self, token, capability: Capability, args):
        # 1. Check skill tier (QUARANTINE/PROBATION/TRUSTED)
        # 2. Check risk threshold for tier
        # 3. Check RAM/CPU budget remaining (Metabolism)
        # 4. Log to Akashic BEFORE executing (pre-mortem)
        # 5. Execute via Ring-1 handler with resource limits
        # 6. Log result
        ...

# Example capability definitions — Documentation that runs, refuses to let docs lie
CAPABILITIES = {
    "shell.run_command": Capability(
        name="shell.run_command",
        risk=4,
        tier_required="PROBATION",
        budget={"cpu_s": 30, "ram_mb": 256, "net": False},
        inspection="tools/verify.py::test_shell_guard"
    ),
    "fs.write": Capability(
        name="fs.write",
        risk=3,
        tier_required="PROBATION",
        budget={"cpu_s": 5, "ram_mb": 64, "net": False},
        inspection="tools/verify.py::test_fs_jail"
    ),
    "generate.image": Capability(
        name="generate.image",
        risk=2,
        tier_required="QUARANTINE",
        budget={"cpu_s": 90, "ram_mb": 3072, "net": False},
        inspection="tools/verify.py::test_image_gen_cpu"
    ),
}
```

Shell server, instead of being security boundary, becomes just one handler behind broker. Broker becomes unit of documentation. Blueprint's material column and runtime enforcement are same artifact.

### 8.2 Universal Event-Task Model (Fixes "Task" Overload)

v6 word "task" overloaded: inbox items, tool calls, scheduled events. Muddle why scheduler hard to wire.

```python
from dataclasses import dataclass

@dataclass
class Event:
    id: str
    kind: str  # "inbox_file" | "wake_word" | "schedule_tick" | "skill_result" | "inbox_complete"
    payload: dict
    received_at: float
    urgency: float  # 0-1, computed by FAST heuristic (no LLM)

@dataclass
class Task:
    event: Event
    state: str  # PENDING → CLAIMED → RUNNING → (DONE | FAILED | DEFERRED)
    skill_tier: str
    budget: dict  # ResourceBudget
    traceback: list  # audit trail LLM will never give you

# Daemon primary loop becomes reactor — LLM not in loop

def run_forever(self):
    while True:
        # 1. Perception pushes Events (inbox files, voice, screen changes)
        # 2. Scheduler sorts pending queue by urgency, budget available
        # 3. Executor claims highest urgency task that fits budget (Metabolism check)
        # 4. Handler runs task (deterministic path OR consults LLM only if no deterministic handler)
        # 5. Every state transition → vault episode + Akashic append
        # 6. Crystallization pass every N tasks → write skill.md
```

Key change: LLM not in loop. Called inside handlers only when deterministic handler doesn't exist or hits ambiguity. Cuts token burn 10-100x on routine work — which is most work.

### 8.3 Two-Brain Problem Solved — Resource Governor Metabolism

v7 biggest practical problem 8GB RAM: can't run router, useful local model, FastSD, video at once. v6 hand-waves "slime thinks!" v7 makes explicit.

```python
class MetabolicState:
    ALIVE = 200       # Core daemon + SQLite + ledger — Always
    AWAKE = 1200      # + Ollama 3B loaded — Task needs reasoning
    ALERT = 1800      # + ASR/TTS loaded — Voice task active
    ARMED = 4200      # + FastSD image gen — Generation task
    DIGESTING = 1900  # + absorption subprocess — URL absorption
    CRYPTOBIOSIS = 50 # Core only event polling — No input 30min

class Metabolism:
    """RAM is blood sugar. Slime's metabolic state determines what can fire.
    Task requests exceeding current state are queued, not refused — slime says
    'not now', never 'not ever'."""
    def request(self, state_needed: int) -> Task:
        if current < needed:
            # Promote (load resources) — demote lower-priority first if needed
            # If can't: DEFER task with reason, log to vault
            pass
```

This is how you get video generation "on" 8GB laptop — by being honest only one heavyweight process can be hot at a time. Metabolism is where v7 honesty meets ambition. Cryptobiosis solves problem v6 doesn't name: free forever agent should run 24/7 while you use laptop, must sometimes go dormant. Metabolic cycling is how you run OS on hardware normal OS would choke on.

### 8.4 Council Done Right — Magisterium as Self-Inspection

v4 had "MAGI Trinity Voting + Sibyl Consensus." v6 demoted to last. v7 rehabilitates — not for better decisions (can't — same model voting 3 times) but as inspection tool. How system knows when it's failing:

- Verdict pass: Same model evaluates own plan at temp=1 three times. If all three verdicts differ → uncertainty detected → flag for human review or fallback to skill library.
- Anti-mode: When about to execute risk-4 or risk-5 capability, one extra pass: "What could go wrong here?" — veto question catches vast majority self-harm (rm -rf typos, wrong directory).

Cheap (one extra model call at decision boundaries only), honest (no pretend committee), directly serves no-fake mandate.

---

## 9. SLIME PROPERLY BUILT — Digestion Not Absorption

### 9.1 Absorption Wrong Metaphor for Code. Digestion Right.

v6 absorption runs absorbed code in subprocess. That's not absorption — tolerating parasite. True slime digestion:

```
GitHub URL detected
    ↓
1. FETCH        raw.githubusercontent.com (no clone, no keys) ✓ (v6 had)
    ↓
2. GASTRIC      AST-parse. Extract: functions, classes, calls, docstrings, external deps. DISCARD source — never run it.
    ↓
3. INVESTIGATE  LLM reads documentation, not code. Asks: What does this do? What inputs? What failure modes? What caps?
    ↓
4. SYNTHESIZE   LLM (or template) writes skill.md — SPEC, not code
    ↓
5. REBUILD      Slime writes OWN code implementing skill.md, using only Broker capabilities, in own style
    ↓
6. CHALLENGE    Generated code runs against tests slime writes first
    ↓
7. ASSIMILATE   Skill enters QUARANTINE tier with decay timer
```

**Why better than v6 execute-in-sandbox:**
- Security: Can't backdoor code that never runs
- Compatibility: Rewritten skill automatically Broker-native, capability-gated from birth
- Honesty: Digested skill is known quantity — declares capabilities explicitly

Slower than v6 once, costs more tokens once, but each digest permanent — one-time cost per skill crystallized forever. Free-forever demands: when tokens are free (local model), spend lavishly on one-time digestion; never spend on routine operation.

**Spec-First Alternative for Small Code:** For small safe utilities (formatting script, regex), skip synthesis and just extract function contract — inputs, outputs, invariants — as skill.md deterministic handler implements. Slime metabolizes at different intensities.

---

## 10. THREE-TIMESCALE BRAIN — Full Memory Architecture

v6 has episodic, semantic, akashic, Obsidian. Good pieces, no unified model. v7:

| Timescale | Store | Decay | Analogy | Retrieval Budget |
|-----------|-------|-------|---------|------------------|
| Milliseconds | Daemon state in-RAM Task objects | Process death | Working memory | Unlimited (RAM) |
| Hours-Days | SQLite episodic vault | Pragmatic decay by score | Autobiographical memory | 2K tokens max — deterministic cheap |
| Years | Akashic chain + skill tree + Obsidian brain | Never — append-only | Long-term memory / identity | 2K tokens max — scored, packed |

Key insight v6 misses: memory only useful if retrieval budget. Free recall of everything is what makes LLMs hallucinate. v7 enforces token budget per memory recall: retrieval layer queries semantic + episodic + skill memory, scores results, packs only what fits 2K tokens. Makes recall deterministic cheap — exactly what OS needs, exactly what LLM lacks.

---

## 11. END-TO-END BLUEPRINT — One Task's Journey (Real Task)

**Task:** "Generate an image of a sunset, save to my desktop"

**Phase 1 — Perception (deterministic, 0 tokens)**
Inbox watcher sees file. Parses intent without LLM (matches known skill trigger: image_gen). Skill exists in vault → skip Phase 2 entirely → 0 token path. If no skill, go Phase 2.

**Phase 2 — Planning (LLM consulted, ~300 tokens)**
No known skill. Metabolism promotes ALIVE → AWAKE (loads 3B local model, +1GB). LLM receives: recent episodes (vault), top-scoring relevant skills (2K token budget), real capability list (real names injected — V4 lesson).

Returns structured plan:
```
PLAN:
  1. capability: generate.image (risk 2) — args: {prompt: "sunset over water", size: 512x512}
  2. capability: fs.write (risk 3) — args: {path: "~/Desktop/sunset.png"}
```

Validation (deterministic, not trusted):
- Do capability names exist? (V4 fake-name hallucination dies here deterministically)
- Does current skill tier permit risk levels? QUARANTINE can request risk-2 but not risk-4
- Does Metabolism have budget for ARMED state (FastSD needs ~3GB)? If not, DEFER with reason "not now" not "not ever"
- Will execution exceed task's resource budget?
If any fails → task DEFERRED machine-readable reason, logged vault + Akashic. LLM never authority. Proposal generator.

**Phase 3 — Execution (deterministic, 0 tokens)**
Metabolism promotes AWAKE → ARMED. If RAM won't allow, demotes idle subsystems first (voice ASR sleeps first — cheapest to wake).
Broker receives two capability requests, logs intent to Akashic BEFORE executing (pre-mortem logging — if system dies mid-execution, ledger shows what it was doing).
FastSD subprocess runs under resource.setrlimit caps: CPU 90s, RAM 3072MB, fs jail ~/Desktop only, net false. Output written via constrained fs.write handler that refuses paths outside approved roots (~/Desktop allowed; /etc/ not; ~/.ssh/ not — hardcoded Ring 0).
Result measured: wall time, RAM peak, output hash.

**Phase 4 — Consolidation (mostly deterministic, ~50 tokens)**
Vault episode saved: task, plan, result, timings.
Akashic append: hash-chained record every capability invocation.
Council verdict pass (only because risk ≥2): "Did plan have plausible failure mode? Should path be crystallized?" — if task recurs 3+ times, slime proposes skill: sunset_image_to_desktop enters QUARANTINE, auto-firing next time skipping Phase 2 entirely.
Metabolism demotes: ARMED → ALIVE after cooldown, then toward CRYPTOBIOSIS if idle.
Total token cost: ~350 first encounter. ~0 every subsequent. That's slime learning curve made concrete.

---

## 12. INSPECTION PLAN v7 — Ladder (Not Rows) — Hard Gates

| Rung | Gate | Command | Fails If | Ship Rule |
|------|------|---------|----------|-----------|
| 0 | Hermetic | `run.py --check --offline` | Any dependency on network | No code merges if any rung red |
| 1 | Unit | `pytest elora/` | Any test red | Same |
| 2 | Loop | `run.py --task smoke --brain fake` | Full task loop can't run scriptable-brainless | Same — This is Wiring Gate |
| 3 | Ledger | `verify.py --tamper-test` | Chain doesn't detect injected edit | Same |
| 4 | Isolation | `verify.py --escape-test` | Absorbed skill reaches banned import / escapes rlimits | Same |
| 5 | Budget | `verify.py --ram-boot` | Full boot >900MB RSS | Same |
| 6 | Metabolism | `verify.py --degrade` | ARMED request on 8GB machine doesn't queue + degrade gracefully | Same |
| 7 | Tier | `verify.py --tiers` | QUARANTINE skill can obtain risk-4 capability | Same |
| 8 | Regression | `grep -r "Blender.*launched" --include="*.py"` | Any hardcoded action-description string survives | Same |
| 9 | Trusted-core immutability | `git diff --stat elora/core/` | Core matches signed commit; absorbed-code attempt to touch core refused + logged | Same |

Blueprint claims and CI are same artifact. Documentation that runs. Documentation that refuses to let documentation lie.

---

## 13. WHAT TO BUILD, IN WHAT ORDER — Honest Roadmap

| Phase | Deliverable | Why First | Est. Effort | Wiring Gate |
|-------|-------------|-----------|-------------|-------------|
| 0 | Ring 0 extraction: broker.py, capability YAML, frozen core ~1,500 lines | Foundation — everything gates through it | 1 wk | Rung 0-1 |
| 1 | ScriptedBrain + Rung 2 gate | Makes everything testable forever after | 3 days | Rung 2 |
| 2 | Wire scheduler via Event/Task model | First real payoff — preemptive urgency | 3 days | Rung 2 |
| 3 | Broker enforcement on shell MCP | Security before growth | 2 days | Rung 4,7 |
| 4 | Metabolism governor | Makes 8GB viable before heavy features land | 1 wk | Rung 5,6 |
| 5 | Digestion pipeline v1 (spec-first for small code) | Slime becomes real — code never runs absorbed | 1 wk | Rung 4 |
| 6 | Tier transitions + decay + Akashic provenance | Skill metabolism | 4 days | Rung 7 |
| 7 | computer_use Tier0 through broker | Immediate token savings | 3 days | Rung 2 |
| 8 | Generation + voice through Metabolism gates | Heavy features last — RAM-hungriest | 2 wks | Rung 5,6 |
| 9 | Council/dual-ledger deliberation + Tauri overlay | Decoration until loop is wired — last | 2 wks | Rung 8 |

Notice what's last: everything v6 listed as "New in v6 Slime." That's not demotion — it's order real engineer builds in. Foundations, then walls, then decorations.

---

## 14. TL;DR — v7 Delta

| Area | v6 | v7 Upgrade |
|------|----|------------|
| Fakeness | Solved via real MCP calls | Keep — grep regression gate |
| Unwired subsystems | 6 "working, not wired" | Wiring Milestone Gate — 6 ordered WIRE tasks, harness first |
| Testability | Manual end-to-end | ScriptedBrain → automated full-loop CI — Airplane Test |
| Slime safety | Banned-import list | Allowlist AST + resource limits + tiered quarantine + immutable core + multi-sig |
| Dimensions | Dev-machine numbers | Target-machine measurement mandate + RAM budget 700MB nominal 900MB hard cap written before wiring |
| Skill lifecycle | Collect + GC | Metabolic decay: success-rate <70% → QUARANTINE, recency 30d → _cold/, cost >2s → journal flag |
| Video on 8GB | Claimed 8GB | Corrected — capability-gated, slideshow-only on 8GB, 16GB-only for ModelScope 1.7b |
| LLM role | Brain | Sense organ — daemon is brain, LLM is peripheral consulted only when no deterministic handler |
| Absorption | Execute in sandbox (tolerate parasite) | Digestion: AST-parse → extract docs → synthesize spec → rebuild native via Broker → challenge via tests → assimilate QUARANTINE — absorbed code never executes |
| Memory | Episodic, semantic, akashic, Obsidian pieces | Three-timescale brain: ms daemon state, hours-days SQLite episodic, years Akashic+skill tree+Obsidian — 2K token retrieval budget deterministic cheap |
| Free Forever | No API keys | Protocol: Airplane Test — fully offline or doesn't ship, network plugin degrades gracefully never dependency |
| Council | Pretend committee | Self-inspection: verdict pass 3x temp=1 detects uncertainty, anti-mode veto catches self-harm risk-4/5 |

---

## 15. FIVE LAWS v7 — The Deep Move

**First Law:** Daemon is brain. LLM is sense organ.
**Second Law:** Passes Airplane Test — fully offline or doesn't ship.
**Third Law:** No code runs absorbed. Code digested into specs, then rebuilt native.
**Fourth Law:** RAM is blood sugar — Metabolism governs what can fire, no is always "not now," never "not ever."
**Fifth Law:** Documentation that doesn't run is lie. Every dimension = one CI gate.

**Deep move in v7:** Stop building features and start building thing that makes features cheap to build. Broker, Metabolism, ScriptedBrain, digestion pipeline are four tools that make every future subsystem natively honest, natively testable, natively constrained — so next V4-style fake becomes structurally impossible rather than merely forbidden.

---

**This is v7 UPGRADE. Wires everything v6 left as "working, not wired." Fixes fakeness structurally, not heuristically. Makes honesty enforceable via ladder gates. Makes slime real via digestion not execution. Makes 8GB laptop viable via Metabolism. Build in order 0→9 or don't build at all.**
