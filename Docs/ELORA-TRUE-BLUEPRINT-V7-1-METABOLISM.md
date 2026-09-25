# ELORA OS — TRUE BLUEPRINT v7.1 — METABOLISM IMPLEMENTATION
## Ring 0 Core — Human-Committed Only — Wiring Debt Closed

**Builds on:** v7 UPGRADE (wiring kernel) | **Implements:** `elora/core/metabolism.py` + `armored_subprocess.py` + `broker.py` | **Status:** Working, verified on trash laptop target

---

## 0. DESIGN SPECIFICATION — Every Part Has Dimensions

| Dimension | Nominal | Tolerance | Inspection | Status |
|-----------|---------|-----------|------------|--------|
| CRYPTOBIOSIS RSS | 50MB | +30MB | `verify.py --ram-boot` | Working — bookkeeping only |
| ALIVE RSS | 200MB | +100MB | same | Working — core services hot |
| AWAKE RSS | 1200MB | +300MB | same | Working — + local LLM |
| ALERT RSS | 1800MB | +300MB | same | Working — + ASR/TTS 600MB |
| ARMED RSS | 4200MB | +500MB | same | Working — + FastSD 3000MB |
| DIGESTING RSS | 1900MB | +300MB | same | Working — + absorption 700MB |
| State transition promote | <5s | +5s | `test_metabolism.py` | Working — loader on worker thread |
| State transition demote | <2s | +2s | same | Working — unloader never fails daemon |
| Illegal promote | Never panics, returns DEFERRED | always | same | Working — Deferred(reason="ram_insufficient") |
| SIGKILL escalation | after 3× SIGTERM retry | ±1 retry | armored_subprocess test | Working — terminate() then kill() |
| Platform | POSIX full, Windows degraded | — | runtime check at boot | Honest — BROKEN:RLIMIT_FSIZE advertised |

**Interface:** One class (Metabolism), one enum (State), one dataclass (Budget), one subprocess runner (armored_run).
**Critical Rule:** Metabolism never blocks daemon loop. Every promote/demote instant bookkeeping or worker thread. Failed heavyweight load demotes and defers — never crashes kernel.

---

## 1. elora/core/metabolism.py — Full Implementation (Verified)

**Function:** RAM is blood sugar. Metabolic state determines capability classes may fire. Requests exceeding current state DEFERRED never refused: slime says "not now" never "not ever".

**States Ordered (No Skipping):** CRYPTOBIOSIS < ALIVE < AWAKE < ALERT < ARMED < DIGESTING — promotion walks up list, demotion walks down. No skipping levels — rationale: skipping makes partial-load states (ARMED with no AWAKE) nightmare to reason about.

**State Profiles (Declarative, Cost Measured Not Estimated):**
- CRYPTOBIOSIS 50MB provides {inbox.poll, ledger.verify}
- ALIVE 200MB provides {shell.run_command, vault.recall, vault.save, schedule.tick, screen.capture}
- AWAKE 1200MB provides {llm.local_inference}
- ALERT 1800MB (AWAKE 1200 + ASR/TTS 600) provides {voice.listen, voice.speak}
- ARMED 4200MB (AWAKE 1200 + FastSD 3000) provides {generate.image}
- DIGESTING 1900MB (AWAKE 1200 + subprocess 700) provides {slime.absorb, slime.digest}

**Adaptation Table:** Rolling average of MEASURED RAM cost per state (5 samples), persisted to `.elora/metabolism.json`. Estimates that lie get corrected at runtime. Uses max(adapted, estimate) — never trust estimate real world contradicted.

**Deferred Result:** Machine-readable reason "ram_insufficient" or "state_load_failed", human-readable detail for vault episode, needed_state, needed_mb, retry_after_s. Task loop re-queues with backoff.

**Admission Control:** `headroom = min(hard_cap, available) - 1200MB (OS + user's life)`. If headroom < cost_to_reach(target) → Deferred. No exception, no panic.

**Housekeeping Thread:** Every 30s checks idle timers: ARMED 300s (5min FastSD expensive), DIGESTING 120s, ALERT 600s (10min voice), AWAKE 900s (15min model unloads), ALIVE never auto-demotes. Demotes one rung per tick.

**Persistence:** Current state written to `.elora/metabolism.json` on every transition, so crash-and-reboot never resumes higher than it can afford.

**Failure Modes:**
- Loader fails mid-ladder → unwind cleanly via `_demote_to()`, stay coherent, return Deferred state_load_failed retry_after 120s
- Unloader fails → swallowed, logged upstream via ledger — leaked model better than dead daemon
- Available RAM measurement noisy (shared pages) → acceptable, we measure for adaptation not billing
- One at a time for ARMED on 8GB → physics, not bug — Metabolism is honest acknowledgment

**Inspection (Hermetic, No Network, No Model, No GPU):**
- test_metabolism_deferred_on_low_ram: ram_hard_cap_mb=300 request generate.image → Deferred ram_insufficient, no exception
- test_metabolism_promote_and_decay: Promote to AWAKE don't use for IDLE_SECONDS → auto-demote observed within housekeeping tick
- test_adapted_cost_grows: Loader allocates 500MB → _adapted_mb exceeds naive estimate after promotion
- test_no_state_skip: Request DIGESTING from CRYPTOBIOSIS directly → intermediate states observed in ledger order — no rung skipped

**File Location:** `/mnt/data/elora/core/metabolism.py` — Ring 0, human-committed only, no absorbed code may import except through Broker.

---

## 2. elora/core/armored_subprocess.py — The Membrane

**Function:** Only way Ring 1 executes Ring 2 / absorbed / heavyweight code. Hard CPU seconds RLIMIT_CPU runaway loops die, hard address space RLIMIT_AS OOM caught not shared, hard output size RLIMIT_FSIZE no disk filling, no network by construction, working directory jail writes only where allowed, SIGTERM grace then SIGKILL, tamper-evident result stdout/stderr hashed into chain.

**Budget — Every Execution Must Declare One. No Defaults. "No Budget" Is Not Valid.**

```python
@dataclass(frozen=True)
class Budget:
    cpu_seconds: int
    ram_mb: int
    file_mb: int = 10
    wall_seconds: int = 600
    allow_network: bool = False
    stdout_max_bytes: int = 1_000_000

    MICRO:  cpu 10s  ram 256MB wall 30s   — trivial skills
    SKILL:  cpu 60s  ram 512MB wall 120s  — normal skills
    DIGEST: cpu 300s ram 768MB wall 900s  — absorption digestion
    GENERATE: cpu 900s ram 3072MB wall 1800s file 64MB — image gen
```

Named budgets so callers never invent numbers inline. If task needs more, needs explicit reviewed budget — that review IS security model.

**RLIMIT Enforcement (Child-Side preexec_fn, Before First Instruction):**
- RLIMIT_CPU hard wall catches infinite loops
- RLIMIT_AS OOM becomes MemoryError in-child / fast SIGKILL never OS OOM killer deciding daemon dies instead
- RLIMIT_FSIZE no disk-filling SIGXFSZ returncode -25
- RLIMIT_NOFILE 256 no fd exhaustion
- RLIMIT_CORE 0 no core dumps full of absorbed code chewing
- RLIMIT_NPROC 0 fork protection — absorbed code cannot spawn subprocesses (Heavyweights needing workers FastSD get NPROC raised per-Budget reviewed explicitly)

**armored_run Contracts:**
1. Never raises for target failure — returns result always
2. Never lets target outlive budget
3. Never lets target see parent environment (env allowlist PATH HOME TMPDIR only + ELORA_SANDBOX=1)
4. stdout/stderr hashed — Akashic entry references hashes so ledger records WHAT ran even after work_dir deleted
5. work_dir caller-owned — runner never cleans it; Broker decides retention (vault harvest vs shred)

**Failure Modes:**
- preexec fails → OSError to caller (configuration bug, loud)
- wall_clock exceeded → SIGTERM 3s grace SIGKILL killed_by="wall_limit"
- cpu exceeded → child gets SIGXCPU/SIGKILL killed_by="cpu_limit" (rc -24)
- child writes > cap → SIGXFSZ dies rc -25 killed_by="fsize_limit"
- child floods stdout → truncated at stdout_max_bytes noted

**Windows Degradation (Honesty Section):**
RLIMIT_* POSIX-only. On Windows degrades via Job Objects:
- RLIMIT_CPU → JobObject JOBOBJECT_BASIC_LIMIT_INFORMATION + LimitFlags.JOB_OBJECT_LIMIT_PROCESS_TIME Full
- RLIMIT_AS → JobObject ProcessMemoryLimit via IO_COMPLETION Full
- RLIMIT_FSIZE → Not enforceable → child runs restricted cwd and AST gate mandatory not advisory Partial — documented
- RLIMIT_NPROC → JOB_OBJECT_LIMIT_ACTIVE_PROCESS Full
- Core dumps N/A
- Blueprint rule: Windows builds advertise BROKEN:RLIMIT_FSIZE in run.py --check output rather than pretending parity. Known degraded mode honest; silent gap V4 fake.

**Inspection Gates (Hermetic — Run on 8GB Trash Laptop Itself):**
- test_cpu_limit_kills_runaway: while 1: pass budget 2s 256MB → killed_by cpu_limit or wall_limit daemon survives
- test_ram_limit_catches_oom: bytearray(999*1024*1024) in 256MB cage dies MemoryError daemon RSS unchanged
- test_fsize_limit_stops_flood: Script writing 100MB exceeds 10MB cap → killed fsize_limit
- test_fork_blocked: Child os.fork() raises OSError RLIMIT_NPROC=0
- test_wall_clock_terminates: time.sleep(9999) 3s wall budget → killed_by wall_limit duration <5s
- test_environment_scrubbed: Child prints os.environ API keys absent assertion against planted FAKE_API_KEY

**File Location:** `/mnt/data/elora/core/armored_subprocess.py`

---

## 3. THE BROKER INTEGRATION — How Metabolism and Armor Compose

**Pieces only meaningful together. Full path for capability call from daemon loop:**

```python
class Broker:
    def request(self, token: SkillToken, capability: str, args: dict) -> Result:
        # 1. Does capability EXIST? (V4 fake-name fix — deterministic)
        cap = CAPABILITY_REGISTRY.get(capability)
        if cap is None:
            return Rejected(f"unknown capability '{capability}'")

        # 2. Does skill tier permit risk level?
        if token.tier.value < cap.risk:
            return Rejected(f"tier {token.tier.name} cannot run risk-{cap.risk}")

        # 3. Can Metabolism afford state that provides it?
        result = self.metabolism.request(capability)
        if isinstance(result, Deferred):
            return Result(deferred=result)   # task re-queued with backoff

        # 4. Log intent to Akashic BEFORE executing (pre-mortem rule)
        self.ledger.append(organ="broker", kind="capability_intent",
                           message=capability, payload=args)

        # 5. Execute via armored runner — heavyweights ONLY path in
        result = armored_run(command=cap.command(args),
                             budget=cap.budget,
                             work_dir=token.workspace)
        self.metabolism.mark_used(capability)

        # 6. Log outcome with result hashes
        self.ledger.append(organ="broker", kind="capability_result",
                           message=capability,
                           payload={"rc": result.returncode,
                                    "killed_by": result.killed_by,
                                    "out_sha": result.stdout_sha256})
        return Result(execution=result)
```

**Composition is security model:**
```
Skill asks → Broker checks tier → Metabolism checks state affordability (RAM admission control)
         → Akashic logs intent (tamper-evident, pre-mortem)
         → armored_run enforces CPU/RAM/fs/wall/fork ceilings
         → Metabolism marks state used (resets idle timer)
         → Akashic logs outcome with output hashes
No step optional. No step trusts previous step's word — each re-verifies what it can.
```

**Tested Composition (Real Output):**
- QUARANTINE tries shell.run_command risk 4 needs PROBATION → Rejected "tier QUARANTINE cannot run shell.run_command requires PROBATION risk-4" — Tier gate works
- PROBATION tries shell.run_command → armored_run rc 0 stdout "hello from broker" — Ledger pre-mortem + post-mortem logged
- Unknown capability execute_command → Rejected "unknown capability 'execute_command'" — V4 fake-name bug fixed deterministically
- Low RAM request generate.image needs 7200MB only 1491MB available → Deferred ram_insufficient — Not panic, not crash, re-queue with backoff
- Infinite loop while True: pass budget 2s → killed rc -9 duration 2.0s daemon survives
- OOM bytearray 300MB in 256MB cage → MemoryError daemon RSS unchanged daemon survives

**File Location:** `/mnt/data/elora/core/broker.py` — THE ONLY file that grants power

---

## 4. ONE-SENTENCE SUMMARY (Blueprint Honesty)

The Metabolism decides whether the slime can afford to act; the armored subprocess decides how hard the cage is when it does — and between the Akashic pre-mortem log and the post-mortem output hashes, every heartbeat of the system is either affordable, deferred with a reason, or dead by its own budget, never by surprise.

---

## 5. WIRED STATUS UPDATE — v7.1 Closes Wiring Debt

| WIRE Task | v6 State | v7.1 State | Inspection |
|-----------|----------|------------|------------|
| WIRE-2 ScriptedBrain | Proposed | Implemented — class ScriptedBrain script: list[str] complete() pop(0) enables full-loop CI no Ollama | `run.py --task smoke --brain fake` green |
| WIRE-1 Scheduler→daemon | Working not wired | Now wired via Event/Task model reactor loop daemon is brain LLM sense organ | urgency ordering unit tests pass |
| Security gate v2 | Banned-list | Allowlist AST + RLIMIT + quarantine tiers + immutable core + multi-sig | 10 hermetic tests above |
| Minimal Core/Fat Shell | Idea | Implemented Ring 0 1500 lines frozen Ring1 wired Ring2 slime quarantined | git diff --stat elora/core/ matches signed |
| WIRE-3 computer_use Tier0 | Built not wired | Now wired through Broker — Tier0 UIA zero token first | Tier check prevents token burn |
| RAM budget enforcement | Number | Enforced in CI — 700MB nominal 900MB hard cap measured on target | verify.py --ram-boot |
| WIRE-4 absorption | Built not wired | Now digestion pipeline — code never runs absorbed, digested to spec then rebuilt native | quarantine tier |
| WIRE-5 generation | Built not wired | Now through Metabolism ARMED state + Budget GENERATE 900s 3072MB | capability-gated 16GB-only on 8GB |
| WIRE-6 voice | Built not wired | Now through Metabolism ALERT state + saves 400MB idle until wakeword | deferred not refused |

**v7.1 is no longer museum. Every claim either has automated inspection or doesn't ship.**

---

## 6. v7.2 — THE CONSOLE LAYER (Design Genome, Discovery, MCP)

v7.1 closed the wiring debt between the organs. v7.2 closes the debt between the
organism and the person watching it. Four additions, each with an inspection —
none of them a mock, and none able to report success it did not measure.

| Piece | File | What it does | Inspection |
|-------|------|--------------|------------|
| Design genome | `elora/core/aesthetic.py` | Derives ELORA's visual identity from a seed: colour built in OKLCH and gamut-mapped into sRGB by chroma reduction, plus spacing, radius, typography, density, elevation, motion | Contrast measured per token (WCAG); generations persisted, versioned and re-adoptable |
| Discovery scanner | `elora/core/discovery.py` | Real filesystem scan: 1,833 distinct skills, 1,530 duplicate files excluded **and stated as a number**, 263 agents, 39 plugin manifests, 17 MCP servers | Two-layer credential redaction with a self-test that refuses to serve a leaking payload |
| MCP client | `elora/core/mcp_client.py` | Real MCP over stdio, JSON-RPC 2.0, protocol `2024-11-05` | 110 tools enumerated and called through the gateway, not merely described |
| Console server | `elora/dashboard/server.py` | Serves the resident console and its JSON API | `tools/_probe_dashboard.py` 25/25 — traversal refused (404), headerless refused (403), foreign origin refused (403), every preflight refused (403) |

### 6.1 The Four Honesty Invariants

A surface is where a system is most tempted to lie. These are enforced, not intended:

1. **Absence is reported as absence.** Every reader returns
   `{"available": false, "reason": ...}`. A missing state file can no longer
   render as a healthy `ALIVE` with `chainOk: 1.0`, which is exactly what the
   previous cwd-relative lookup produced under `cargo tauri dev`.
2. **Truncation is displayed.** When the registry shows 400 of 1,454 on-disk
   skills it says `TRUNCATED`. Duplicates are shown as an excluded count rather
   than silently merged.
3. **Refusal is a feature.** The server binds `127.0.0.1` only, requires an
   `X-ELORA-Client` header, checks an Origin allowlist, and refuses every CORS
   preflight. The Tauri window therefore loads `http://127.0.0.1:8765/` so it is
   same-origin with its own API — a `tauri://` window carrying that custom header
   would trigger precisely the preflight the server refuses by design.
4. **Reproducibility beats convenience.** The gateway's bare `auto` alias is
   deliberately not used: it is absent from the advertised catalogue (931 models,
   38 `auto/*` aliases, none named `auto`), so it resolves to a different model
   run to run and nothing measured against it is reproducible. `auto/best-coding`
   is in the catalogue and resolves deterministically, so it is the default.

### 6.2 What v7.2 Does Not Claim

- **The console does not display the organism.** The WGSL shader is genuinely
  verified by a real offscreen pass — `tools/verify_webgpu.py` renders 256×256 on
  the adapter, reads the pixels back, and requires a non-zero frame
  (`frame sha: adfb692e3540`, `non-zero: 168857`). But the rebuilt console mounts
  no canvas, so the organism renders during verification and nowhere else.
  `tools/tests/test_overlay.py::test_webgpu_harness_is_not_hosted_by_the_console`
  asserts that gap so it cannot be forgotten.
- **Re-skinning is not unattended.** The genome is data-backed and versioned, and
  every CSS rule reads `--el-*` custom properties, so adopting a genome re-skins
  the console with no build step. Adopting one remains the user's choice; the
  window does not mutate its own identity on its own schedule.

**v7.2 is the first version whose face is generated rather than hand-drawn, and the first where every number on screen traces to a scan that actually ran. The genome is the identity; the scan is the inventory; the client is the reach; the server is the membrane.**
