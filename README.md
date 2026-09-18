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

## Installation & Sovereign Verification

Local-first. No API keys. Free forever. All 124 tests must be green before the Tauri window opens.

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
# Accelerates test execution 6.12x (52.25s → 8.53s) with AWAKE working set 380MB
```

### 3. Verify Preflight & Smoke Test
```bash
# Preflight audit (0 fail, 9 warn expected)
python run.py --check

# Hermetic smoke test (GREEN)
python run.py --smoke
```

### 4. Run Full Test Suite
```bash
pytest tools/tests
# 124 passed in tools/tests across 17 modules
```

### 5. Multi-Turn Live Demonstration
```bash
python tools/live_demo.py
# 5 iterations • 12 sequenced events • VALID Akashic cryptographic hash chain
```

### 6. Run or Build Desktop Overlay (Tauri v1.6)
```bash
# Verify compiler and lints (0 errors, 0 warnings)
cargo check --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml

# Run desktop overlay in dev mode (requires Tauri CLI: cargo install tauri-cli)
cargo tauri dev

# Build standalone installer (MSI on Windows)
cargo tauri build
```

---

## Blueprint & Documentation
Detailed architectural blueprints and specs can be found in the `Docs/` directory:
- [ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md](Docs/ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md)
- [ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md](Docs/ELORA-TRUE-BLUEPRINT-V7-1-METABOLISM.md)

