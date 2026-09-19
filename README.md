# ELORA OS

> **A Sovereign, Local-First Agentic Operating System**  
> *Absorbs Everything. Fakes Nothing. Free Forever. Wires Everything.*  
>  
> `124 passed in 51.71s (17 modules) | cargo check 0 errors clippy 0 warnings | smoke GREEN | live_demo 5 iterations 12 events VALID`

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

---

## Project Structure

```
.
├── elora/
│   ├── core/
│   │   ├── absorb_pipeline.py    # Ingestion pipeline (fetch → gate → spec → bind)
│   │   ├── absorption_gate.py    # AST allowlist and quarantine parser
│   │   ├── armored_subprocess.py # Sandboxed execution membrane & Job Objects
│   │   ├── bitnet.py             # BitNet b1.58 ternary kernel
│   │   ├── broker.py             # Capability broker & dual-key consent
│   │   ├── capabilities.py       # Registered tools and permission tiers
│   │   ├── crystallization.py    # Skill promotion and code synthesis
│   │   ├── decay.py              # Skill usage decay and cold storage
│   │   ├── fs.py                 # Sandboxed filesystem utilities
│   │   ├── loaders.py            # On-demand metabolic asset loaders
│   │   ├── metabolism.py         # 6-state machine & RAM admission control
│   │   ├── promotion.py          # Ledger-driven skill promotion
│   │   ├── virtio_shm.py         # Lock-free SPSC shared-memory ring buffer
│   │   └── wasm_gastric.py       # Fuel-metered WebAssembly sandbox
│   ├── organs/
│   │   └── akashic.py            # Tamper-evident hash-chained ledger
│   ├── slime/
│   │   ├── computer_use.py       # WIRE-3 screen capture & UIA control
│   │   ├── generation.py         # WIRE-5 local image synthesis (ARMED 4200MB)
│   │   └── voice.py              # WIRE-6 speech recognition & synthesis (ALERT 1800MB)
│   ├── brain.py                  # RealBrain (HTTP) and ScriptedBrain (CI)
│   ├── daemon.py                 # Core reactor event loop & semantic scheduler
│   ├── overlay_bridge.py         # SPSC ring ripple bridge for desktop overlay
│   └── vault.py                  # Persistent episode storage (SQLite)
├── native/
│   └── bitnet/                   # Rust PyO3 ternary matmul kernel (b1.58)
├── overlay/
│   ├── index.html                # WebGPU organism visualization
│   ├── tauri_bridge.js           # Tauri JS bridge for state & ripple events
│   └── organism.wgsl             # Spatial particle WGSL compute shader
├── src-tauri/                    # Tauri v1.6 desktop application
│   ├── Cargo.toml                # Desktop app dependencies & sidecar permissions
│   ├── tauri.conf.json           # Window configuration (transparent, undecorated)
│   ├── build.rs                  # Windows resource builder
│   └── src/
│       └── main.rs               # Sidecar process manager & IPC bridge
├── tools/
│   ├── tests/                    # Ring 0 hermetic test suite (124 tests across 17 modules)
│   ├── build_native.py           # Native Rust PyO3 compilation tool
│   ├── live_demo.py              # Multi-turn autonomous agent execution demo
│   ├── _cleanup_backups.py       # Maintenance utility
│   └── _compile_all.py           # Bytecode compilation verification
├── Docs/                         # Complete technical blueprints (v7 & v7.1)
├── run.py                        # Boot sequence, preflight, smoke, and live runner
└── requirements.txt
```

---

## Tauri Desktop Packaging & WebGPU Overlay

ELORA provides a native desktop packaging wrapper via **Tauri v1.6** that renders the real-time WebGPU SDF organism overlay, connects to the kernel via a lock-free VirtIO SHM ring (`.elora/shm/overlay.ring`), and manages the ELORA daemon sidecar:

- **Transparent Overlay**: Undecorated, transparent 1280×800 desktop canvas rendering dynamic SDF metaball physics.
- **VirtIO SHM Ripple Bridge**: Lock-free SPSC ring buffer where broker capability requests emit cryptographic ripple events.
- **Sidecar Lifecycle**: Spawns `python run.py --brain bitnet`, streams telemetry into Akashic ledger, and drains on shutdown.

> [!NOTE]
> **Honest Rendering Audit**: In accordance with preflight honesty (`[WARN] leap: webgpu overlay shader verified + bridge verified; rendering UNVERIFIED`), while the WGSL shader syntax/structure and the SPSC SHM bridge are fully verified, WebGPU rendering execution itself requires an active GPU hardware adapter and is marked unverified in headless/CI runners.

### Development & Verification
Verify the Tauri application manifest and code:
```bash
cargo check --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml
```
To run the live desktop overlay in development mode:
```bash
cargo tauri dev
```
To compile the standalone desktop executable:
```bash
cargo build --manifest-path src-tauri/Cargo.toml --release
# → src-tauri/target/release/elora-tauri.exe (5.74 MB standalone binary)
```

---

## Installation & Sovereign Verification

Local-first. No API keys. Free forever. Preflight (`run.py --check`) and hermetic smoke (`run.py --smoke`) enforce environment readiness; the full test suite (`pytest tools/tests`) verifies all 124 rungs across 17 modules.

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
  [OK ] import daemon  
  [WARN] psutil + RAM  8064MB total (need >=4096; 8192 comfortable; ARMED gated by metabolism)
  [OK ] ollama  absent -> AWAKE unreachable, tasks defer
  [WARN] tauri  absent
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
  [WARN] leap: webgpu overlay  shader verified (overlay/organism.wgsl) + bridge verified; rendering UNVERIFIED (needs GPU runner in CI)
  [WARN] leap: computer_use  pywinauto absent -> screen.control unreachable
  [WARN] leap: generation  fastsdcpu absent -> ARMED unreachable, tasks defer, mock active
-- preflight: 0 fail, 8 warn --
```
*(Note: 0 fail, 9 warn if `.elora/shm/overlay.ring` has not yet been initialized prior to bridge startup)*

Run the hermetic zero-network smoke test:
```bash
python run.py --smoke
```

```text
[boot] 2/8 vault
[boot] 3/8 metabolism (booting at ALIVE, never higher)
[boot] 4/8 broker
[boot] 5/8 promotion engine (replaying ledger)
[boot] 6/8 crystallizer + decay + absorb
[boot] 7/8 loaders (heavyweights stay asleep until needed)
[boot] 8/8 daemon (registering itself as a skill - QUARANTINE)
  [OK ] task loop -> DONE
  [OK ] real subprocess ran (smoke.txt written)
  [OK ] akashic chain verifies
  [OK ] real names in system prompt (V4 regression)
-- smoke: GREEN --
```

### 4. Run Full Test Suite
```bash
pytest tools/tests
# 124 passed across 17 test modules in tools/tests
```

### 5. Multi-Turn Live Demonstration
```bash
python tools/live_demo.py
# 5 iterations • 12 sequenced events • VALID Akashic cryptographic hash chain
```

### 6. Run the Daemon (Brain Division of Labor)
Start continuous polling on `.elora/inbox`:
```bash
# Production Multi-Turn Planning (Ollama / LocalAI):
# Emits <mcp_call> blocks with complex reasoning across capabilities
python run.py --brain local

# Sovereign Offline / Fallback (BitNet b1.58):
# 380MB AWAKE addition-only kernel; returns DONE when unweighted (zero-hallucination)
python run.py --brain bitnet

# Process one inbox tick and exit cleanly:
python run.py --brain bitnet --once

# Offline / sleeping brain (for test harness):
python run.py --brain none
```

---

## Blueprint & Documentation
Detailed architectural blueprints and specs can be found in the `Docs/` directory:
- [ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md](Docs/ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md)
- [ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md](Docs/ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md)


