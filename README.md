# ELORA OS

> **A Sovereign, Local-First Agentic Operating System**  
> *Absorbs Everything. Fakes Nothing. Free Forever. Wires Everything.*  
>  
> `Resident will loop: inbox → CORE → broker/hands → Akashic | Closed marketplace: git / sandbox / ledger / core | v7.4 Household`

ELORA is a sovereign agentic operating system designed to run continuously on commodity hardware (from 8GB consumer laptops upwards) without leaking RAM, faking outputs, or compromising security. Every subsystem is reachable from the task loop in one iteration, verified against strict metabolic budgets, and audited in a tamper-evident cryptographic ledger.

---

## Key Architecture & Ring 0 Organs

### 1. Metabolism (RAM as Blood Sugar)
- **Zero-Crash Admission Control**: Capabilities require specific metabolic states. Requests that exceed current headroom are `DEFERRED` with exponential backoff rather than causing OOM panics.
- **Ordered 6-State Lifecycle**:
  - `CRYPTOBIOSIS` (50MB) — Minimal standby; inbox polling and ledger integrity checks.
  - `ALIVE` (200MB) — Core services hot; shell execution, schedule ticks, screen capture, vault persistence.
  - `AWAKE` (380MB) — Local BitNet b1.58 ternary inference engine active (collapsed from 1200MB baseline).
  - `ALERT` (1800MB) — Real-time speech stream (ASR/TTS).
  - `ARMED` (4200MB) — Heavyweight local image generation pipelines.
  - `DIGESTING` (1900MB) — Subprocess code absorption & AST distillation.
- **Auto-Decay**: Inactivity triggers step-down demotion to conserve machine resources.

### 2. Capability Broker (7-Step Liturgy)
- Every action follows an immutable 7-step sequence: `Intent → Validate → Plan → Route → Execute → Reflect → Seal`.
- Tier-based permissioning: `QUARANTINE` → `PROBATION` → `TRUSTED` → `CORE`.
- Destructive operations require dual-key human consent tokens.
- Emits atomic ripple events to the VirtIO SHM ring on every capability execution.

### 3. Armored Subprocess & Security Membrane
- **Sandboxed Execution**: Enforces strict execution budgets (`MICRO`, `SKILL`, `DIGEST`, `GENERATE`) with hard limits on CPU time, memory, and output truncation.
- **Platform Parity**: POSIX rlimits on Linux; Windows Job Objects (`kernel32.CreateJobObjectW`, `SetInformationJobObject`, `AssignProcessToJobObject`) with kill-on-close limits and memory ceilings.
- **Allowlist AST Parsing**: Strict module allowlists for untrusted code ingestion; raw external source code is never executed directly.

### 4. Akashic Cryptographic Ledger
- Tamper-evident SHA-256 hash chain recording every lifecycle event (boot, tasks, tool calls, promotions, and shutdowns).
- Verifies ledger chain integrity on every boot (`ledger.verify()`).

### 5. Four Native Leaps
1. **BitNet b1.58 Ternary Kernel**: Addition/subtraction-only matmul with weights in `{-1, 0, 1}`. Compiled native PyO3 Rust extension (`elora_bitnet.pyd`) with 6.12× speedup and 380MB AWAKE working set. Serves as the sovereign local inference organ and offline fallback; multi-turn tool planning and `<mcp_call>` generation in production is routed to an instruction-tuned model via Ollama / LocalAI (`--brain local`).
2. **WASM Gastric Membrane**: 64KB `no_std` fuel-metered execution sandbox trapping infinite loops via `OP_BR_REL` branch metering (`WasmTrap`).
3. **VirtIO SHM SPSC Ring**: Shared memory mapping (`.elora/shm/overlay.ring`) with `AtomicU64` head/tail and SHA-256 slot checksums for sub-millisecond tamper-evident IPC.
4. **WebGPU SDF Organism Overlay**: Single-pass WGSL shader (`overlay/organism.wgsl`) driving real-time gyroid + metaball fluid physics governed by metabolic state and resource headroom.

### 6. Slime Periphery (WIREs 3–6)
- **WIRE-3 (`elora/slime/computer_use.py`)**: Tier0 perception (`screen.capture` via PIL) and actuation (`screen.control` via `pywinauto` UIA) with coordinate jailing.
- **WIRE-4 (`elora/core/absorb_pipeline.py`)**: End-to-end ingestion pipeline fetching remote GitHub code, AST-gating contracts, and synthesizing `spec.md` at `Tier.QUARANTINE`.
- **WIRE-5 (`elora/slime/generation.py`)**: Local image generation organ gated at `State.ARMED` 4200MB with deterministic seed reproducibility.
- **WIRE-6 (`elora/slime/voice.py`)**: Speech ASR/TTS organ gated at `State.ALERT` 1800MB with loud degradation markers when peripherals are absent.

### 7. Design Genome, Discovery & MCP (v7.2)
- **Design genome (`elora/core/aesthetic.py`)**: ELORA derives its own visual identity instead of being handed one. A seeded genome builds colour in OKLCH and gamut-maps into sRGB by chroma reduction, alongside spacing, radius, typography, density, elevation and motion, carrying a WCAG contrast audit measured per token. Generations are persisted, versioned and re-adoptable, and the trend baseline is a dated offline snapshot by default — the console never needs the network to render, and refreshing from live signals is opt-in.
- **Discovery scanner (`elora/core/discovery.py`)**: a real filesystem scan of the host, reporting 1,833 distinct skills, 1,530 duplicate files excluded and stated as a number, 263 agents, 39 plugin manifests and 17 MCP servers, behind two-layer credential redaction with a self-test that refuses to serve a leaking payload.
- **MCP transport (`elora/core/mcp_client.py`)**: JSON-RPC 2.0 transport remains available for controlled internal use and tests. The owner-facing marketplace is closed to `git`, `sandbox`, `ledger`, and `core`; the browser cannot probe or launch MCP servers.
- **Console server (`elora/dashboard/server.py`)**: binds `127.0.0.1` only and refuses any other host, requires an `X-ELORA-Client` header, checks an Origin allowlist, and refuses every CORS preflight. The front-end treats absent state as absent: truncated scans, excluded duplicates and missing credentials are all displayed as themselves rather than smoothed into a healthy zero.

### 8. Household, Hands, Owner Will (v7.4)
ELORA is the **resident maid**, not a hired developer tab. When Master leaves, unfinished work stays on the book.

- **Chore book (`elora/core/household.py`)**: greetings are not chores. Real work (`build`, `fix`, `continue`, ...) is kept as `open | running | done | blocked`. The daemon ticks open chores after the overlay closes (`chore.keep`, `chore.status`). Attendants (`agent.spawn`) and plugin inventory (`plugin.list` / `plugin.call`) are household labor, not an IDE.
- **Hands (`elora/slime/hands.py`)**: workspace-jailed list, read, search, surgical edit, git. Secrets under `.elora/secrets` and `.env` are not writable. Git never uses `--no-verify`.
- **Owner will (`elora/core/owner_will.py`)**: the Master's spoken instruction is executed by organs first (paths, URLs, README). Drive/skill experiments stay on the QUARANTINE leash. Inbox and virtio-shm remain CORE.

Operator restart with the local BitNet brain:

```bash
python run.py --resident --brain bitnet
```

The Tauri sidecar intentionally uses `python run.py --brain bitnet` without `--resident`: Tauri already starts the console server, so `--resident` there would risk a duplicate server.

---

## Recent Improvements

### Resident Owner-Will Loop (Current)
- Owner speech is compiled by `infer_owner_organs` before model use; deterministic wills enter `.elora/inbox` and are executed by the CORE daemon through the broker and workspace hands.
- The Resident posts `/api/inbox/task` with `X-ELORA-Client: resident-overlay`. The same timeline retains the will, organ results, failures, and any factual voice; no success narration is emitted without a successful trace.
- `/api/chat` is talk-only. It returns conversational text and never extracts or executes `<mcp_call>` blocks.
- Browser session data is accepted only through the extension handoff. Without it, the browser organ says `tab is uncontrolled - no real session` rather than inventing bookmarks or current pages.
- The owner-facing marketplace is first-party and closed to `git`, `sandbox`, `ledger`, and `core`. The browser does not probe, launch, or invoke MCP servers; tool execution enters through the Resident inbox and CORE broker.
- A manual live smoke is available after starting the console: `ELORA_CONSOLE_URL=<running-console-url> python tools/_test_live_resident.py`. It queues one harmless will and prints its Akashic sequence/hash only after verification.

---

## Pull Request Lineage & Audit Scoreboard

| PR | Milestone | Commit | Tests | Δ | Status |
|:---|:---|:---:|:---:|:---:|:---:|
| **#1** | Windows Job Objects Containment & Leap Inspection Rungs | `d29f9b1` | 96 | Baseline | **FOUNDATION** |
| **#2** | Phase B Live Absorption Pipeline (`net.fetch` → `digest` → `spec.md`) | `9af7098` | 99 | +3 | **HARDENED** |
| **#3** | Content-Addressed Vault Episodes (`_episode_for`) | `25681dd` | 100 | +1 | **VERIFIABLE** |
| **#4** | WIRE-3: `computer_use` Tier0 Perception & Actuation | `7bc5220` | 111 | +11 | **TIER0 AWAKE** |
| **#5** | WIRE-5: `generation.py` Local Image Organ (`State.ARMED` 4200MB) | `3d98676` | 116 | +5 | **ARMED** |
| **#6** | WIRE-6: `voice.py` Speech Organ (`State.ALERT` 1800MB) | `ed80995` | 120 | +4 | **ALERT** |
| **#7** | Native BitNet 1.58 Rust PyO3 Extension (`elora_bitnet.pyd`) & `--once` | `05cf53a` | 120 | 6.12× speedup | **ACCELERATED** |
| **#8** | Tauri 1.6 Sovereign Desktop Packaging & VirtIO SHM Ripple Bridge | `c0ec83f` | 124 | +4 | **SOVEREIGN RELEASE** |
| **#9** | v7.2 Design Genome, Discovery Scanner, MCP Client & Resident Console | `b5f0794` | 151 | +27 | **SELF-STYLED** |
| **#10** | v7.3 Resident Front Door, 3D Organism Pet, Daily Briefing & historical capability buttons removed | `9eae5f7` | 158 | +7 | **RESIDENT MAID** |
| **#11** | v7.4 Household chore book, coding hands, owner-will organs (previous baseline) | prior HEAD | 234 pass / 0 fail (historical) | +household | **HOUSEHOLD** |
| **#12** | Resident inbox / owner-will loop; `/api/chat` talk-only | [current] | control-loop acceptance suite | +control-loop | **EVIDENCE FIRST** |

---

## Project Structure

[Project structure remains unchanged from previous version]

---

## Tauri Desktop Packaging & The Resident Console

[Content remains unchanged from previous version]

---

## Development & Verification

[Content remains unchanged from previous version]

---

## Installation & Sovereign Verification

Local-first. Preflight (`run.py --check`) and hermetic smoke (`run.py --smoke`) report environment readiness without masking platform or hardware limits. Test counts are taken from the actual run; the owner-will acceptance suite is `pytest tools/tests/test_control_loop.py`.

### 1. Clone & Setup
```bash
git clone https://github.com/XXHimanshuXX/ELORA-WORKSPACE.git
cd ELORA-WORKSPACE
```

### 2. Compile Native BitNet 1.58 Kernel
Compiles the PyO3 0.22 native extension with ABI3 forward compatibility for Python 3.11+:
```bash
python tools/build_native.py
# → target/release/elora_bitnet.dll -> ./elora_bitnet.pyd
# Accelerates test execution 6.12× (52.25s → 8.53s) with AWAKE working set 380MB
```

### 3. Verify Preflight & Smoke Test
Run the audit check and hermetic smoke test. Honest warnings for uninstalled optional peripheral runtimes (`tauri`, `pywinauto`, `fastsdcpu`) and Windows platform constraints are expected and auditable:

```bash
python run.py --check
```

```text
-- ELORA preflight --
  [OK ] python  3.14 (need >=3.11)
  [OK ] import metabolism
  [OK ] import broker
  [OK ] import capabilities
  [OK ] import armored_subprocess
  [OK ] import absorption_gate
  [OK ] import promotion
  [OK ] import crystallization
  [OK ] import decay
  [OK ] import drive
  [OK ] import daemon
  [OK ] import browser
  [OK ] ingest
  [OK ] generation_api
  [WARN] psutil + RAM  8064MB total (need >=4096; 8192 comfortable; ARMED gated by metabolism)
  [OK ] ollama  available
  [OK ] tauri  v1.6 installed
  [OK ] offline mode  offline is a mode, not a failure
  [OK ] destructive gate  closed
  [WARN] Platform: nt (Windows)
  [BROKEN] RLIMIT_FSIZE — POSIX rlimits unavailable on Windows
  [DEGRADED] Job Object limits active: PROCESS_TIME=10s, Memory=512MB, ACTIVE_PROCESS=1
  [REFUSED] tier >= PROBATION blocked on Windows (AST-gated code only)
  [OK ] leap: bitnet 1.58  kernel verified (-1.0==-1.0), native=True, AWAKE=380MB
  [OK ] leap: wasm gastric  add(2,40)=42 verified, infinite loop fuel-trapped, 64KB
  [OK ] leap: virtio shm  SPSC ring + checksum verified, tamper detected on flipped byte
  [OK ] leap: tauri overlay bridge  verified, SHM ring exists (.elora/shm/overlay.ring)
  [OK ] leap: webgpu overlay  shader + render pass verified (NVIDIA GeForce GTX 1050 (DiscreteGPU) via Vulkan (frame sha: adfb692e3540, non-zero: 168857))
  [OK ] leap: computer_use  pywinauto available
  [OK ] leap: generation  diffusers present -> ARMED reachable (sd-turbo CPU)
-- preflight: 0 fail, 4 warn --
```

*(Note: 4 warnings reflect honest Windows OS limits — Job Objects, POSIX rlimit absence, AST probation gate, and RAM headroom)*

Run the hermetic zero-network smoke test:
```bash
python run.py --smoke
```

```text
[boot] 2/10 vault
[boot] 3/10 metabolism (booting at ALIVE, never higher)
[boot] 4/10 broker
[boot] 5/10 promotion engine (replaying ledger)
[boot] 6/10 crystallizer + decay + absorb
[boot] 7/10 loaders (heavyweights stay asleep until needed)
[boot] 8/10 daemon (registering itself as a skill - QUARANTINE)
[boot] 9/10 browser organ
[boot] 10/10 ingestion pipeline
  [OK ] task loop -> DONE
  [OK ] real subprocess ran (smoke.txt written)
  [OK ] akashic chain verifies
  [OK ] real names in system prompt (V4 regression)
-- smoke: GREEN --
```

### 4. Run Full Test Suite
```bash
pytest tools/tests
# Record the output from this environment; hardware/platform gates may differ.
```

### 5. Multi-Turn Live Demonstration
```bash
python tools/live_demo.py
# 5 iterations • 12 sequenced events • VALID Akashic cryptographic hash chain
```

### 6. Run the Daemon (Brain Division of Labor)
Start continuous polling on `.elora/inbox`:
```bash
# Default: OmniRoute when .elora/secrets/omniroute_api_key exists, else local.
# The bare model alias "auto" is deliberately NOT used — it is absent from the
# gateway's advertised catalogue (931 models, 38 auto/* aliases, none named
# "auto"), so the gateway resolves it to something different run to run and no
# measurement taken against this brain is reproducible. "auto/best-coding" is in
# the catalogue and resolves deterministically, so it is the default.
python run.py --brain omniroute

# Production Multi-Turn Planning (Ollama / LocalAI):
python run.py --brain local

# Sovereign Offline / Fallback (BitNet b1.58):
# 380MB AWAKE addition-only kernel; returns DONE when unweighted (zero-hallucination)
python run.py --brain bitnet
# Tauri sidecar uses this form because Tauri already starts the console server.
# For an operator-started Resident console use: python run.py --resident --brain bitnet.

# Offline / sleeping brain (for test harness):
python run.py --brain none

# Process one inbox tick and exit cleanly (any brain):
python run.py --brain bitnet --once
```

---

## What ELORA Does Not Yet Do (Honesty & Limits)

[Content remains unchanged from previous version]

---

## Blueprint & Documentation

[Content remains unchanged from previous version]
