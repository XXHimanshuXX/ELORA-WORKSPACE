# ELORA OS

> **A Sovereign, Local-First Agentic Operating System**  
> *Absorbs Everything. Fakes Nothing. Free Forever. Wires Everything.*

ELORA is a sovereign agentic operating system designed to run continuously on commodity hardware (from 8GB consumer laptops upwards) without leaking RAM, faking outputs, or compromising security. Every subsystem is reachable from the task loop in one iteration, verified against strict metabolic budgets, and audited in a tamper-evident cryptographic ledger.

---

## Key Architecture & Organs

### 1. Metabolism (RAM as Blood Sugar)
- **Zero-Crash Admission Control**: Capabilities require specific metabolic states. Requests that exceed current headroom are `DEFERRED` with backoff rather than causing OOM panics.
- **Ordered Lifecycle**:
  - `CRYPTOBIOSIS` (50MB) — Minimal standby; inbox polling and ledger integrity checks.
  - `ALIVE` (200MB) — Core services hot; shell execution, schedule ticks, screen capture, vault persistence.
  - `AWAKE` (1200MB) — Local LLM / inference engine active.
  - `ALERT` (1800MB) — Real-time audio stream (ASR/TTS).
  - `ARMED` (4200MB) — Heavyweight generative pipelines.
  - `DIGESTING` (1900MB) — Subprocess code absorption & AST distillation.
- **Auto-Decay**: Inactivity triggers step-down demotion to protect system resources.

### 2. Armored Subprocess & Security Membrane
- **Sandboxed Execution**: Enforces strict execution budgets (`MICRO`, `SKILL`, `DIGEST`, `GENERATE`) with hard limits on CPU time, RAM, and output size.
- **POSIX rlimits & Windows Job Objects**: Prevents runaway loops, memory leaks, and fork bombs across platforms.
- **Allowlist AST Parsing**: Strict syntax and module allowlists for all untrusted code absorption.

### 3. Capability Broker & Dual-Key Consent
- Every tool invocation goes through the central `Broker`.
- Tier-based permissioning: `QUARANTINE` → `SANDBOX` → `TRUSTED`.
- Destructive actions require dual-key human consent tokens.

### 4. Akashic Ledger
- Tamper-evident cryptographic hash chain recording all system events (boot, tasks, tool calls, promotions, and shutdowns).
- Verifies ledger chain integrity on every boot (`verify()`).

### 5. BitNet b1.58 Inference Organ
- Addition-only ternary weights `{-1, 0, 1}` requiring no float multiplication.
- Native Rust extension (`native/bitnet`) via PyO3 with automatic pure-Python fallback.

### 6. WebGPU Overlay Organism
- Real-time metabolic ripple and state visualization via WGSL compute shader (`overlay/organism.wgsl`).

---

## Project Structure

```
.
├── elora/
│   ├── core/
│   │   ├── absorption_gate.py    # AST allowlist and quarantine parser
│   │   ├── armored_subprocess.py # Sandboxed execution membrane & budgets
│   │   ├── bitnet.py             # BitNet b1.58 ternary kernel
│   │   ├── broker.py             # Capability broker & dual-key consent
│   │   ├── capabilities.py       # Registered tools and permission tiers
│   │   ├── crystallization.py    # Skill promotion and code synthesis
│   │   ├── decay.py              # Skill usage decay and cold storage
│   │   ├── loaders.py            # On-demand metabolic asset loaders
│   │   ├── metabolism.py         # State machine & RAM admission control
│   │   ├── promotion.py          # Ledger-driven skill promotion
│   │   ├── virtio_shm.py         # Shared memory SPSC ring buffer
│   │   └── wasm_gastric.py       # Fuel-metered WebAssembly sandbox
│   ├── organs/
│   │   └── akashic.py            # Tamper-evident hash-chained ledger
│   ├── brain.py                  # RealBrain (HTTP) and ScriptedBrain (CI)
│   ├── daemon.py                 # Core reactor event loop
│   ├── overlay_bridge.py         # WebGPU ripple counter bridge
│   └── vault.py                  # Persistent episode storage
├── native/
│   └── bitnet/                   # Rust PyO3 ternary matmul kernel
├── overlay/
│   ├── index.html                # WebGPU organism visualization
│   ├── tauri_bridge.js           # Tauri JS bridge for state & ripple events
│   └── organism.wgsl             # Spatial particle WGSL shader
├── src-tauri/                    # Tauri v1 desktop application
│   ├── Cargo.toml                # Desktop app configuration & sidecar permissions
│   ├── tauri.conf.json           # Window configuration (transparent, undecorated)
│   └── src/
│       └── main.rs               # Sidecar process manager & IPC bridge
├── tools/
│   ├── tests/                    # Ring 0 hermetic test suite (124 tests)
│   ├── build_native.py           # Native Rust PyO3 compilation tool
│   ├── live_demo.py              # Multi-turn autonomous agent execution demo
│   ├── _cleanup_backups.py       # Maintenance utility
│   └── _compile_all.py           # Bytecode compilation verification
├── Docs/                         # Complete technical blueprints (v7 & v7.1)
├── run.py                        # Boot sequence, preflight, and smoke tests
└── requirements.txt
```

---

## Tauri Desktop Packaging & WebGPU Overlay

ELORA provides a native desktop packaging wrapper via **Tauri v1.6** that renders the real-time WebGPU SDF organism overlay, connects to the kernel via a lock-free VirtIO SHM ring (`.elora/shm/overlay.ring`), and manages the ELORA daemon sidecar:

- **Transparent Overlay**: Undecorated, transparent 1280x800 desktop canvas rendering dynamic SDF metaball physics.
- **VirtIO SHM Ripple Bridge**: Lock-free SPSC ring buffer where broker capability requests emit cryptographic ripple events.
- **Sidecar Lifecycle**: Spawns `python run.py --brain bitnet`, streams telemetry into Akashic ledger, and drains on shutdown.

### Development & Verification
Verify the Tauri application manifest and code:
```bash
cargo check --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml
```
To run the live desktop overlay in development mode (requires Tauri CLI):
```bash
cargo tauri dev
```

---

## Quickstart

### 1. Requirements
- Python 3.11+ (Python 3.14 compatible)
- (Optional) Rust toolchain for native BitNet acceleration
- (Optional) Ollama running locally for `AWAKE` state inference

### 2. Preflight Inspection
Verify your host environment, imported organs, and platform capabilities:
```bash
python run.py --check
```

### 3. Hermetic End-to-End Smoke Test
Run an end-to-end task loop pass (task claim → tool dispatch → armored subprocess → akashic audit → DONE) with zero external network or model dependencies:
```bash
python run.py --smoke
```

### 4. Run Test Suite
Run the 124 hermetic unit & integration tests:
```bash
pytest tools/tests
```

### 5. Boot Daemon
Start the ELORA OS daemon:
```bash
python run.py
```
To run with sleeping brain (no external LLM required):
```bash
python run.py --brain none
```

---

## Blueprint & Documentation
Detailed architectural blueprints and specs can be found in the `Docs/` directory:
- [ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md](Docs/ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md)
- [ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md](Docs/ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md)
