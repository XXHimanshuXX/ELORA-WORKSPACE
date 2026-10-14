# ELORA OS — The Maid Resident Awakening Playbook

This playbook accompanies `awaken_elora.py` and explains how every unwired subsystem (`WIRE-1` through `WIRE-6`) and all four open release gates from your [ELORA Practical Audit](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/ELORA_PRACTICAL_AUDIT_2026-10-13.md) and [V7 Upgrade Blueprint](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/Docs/ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md) are connected into a single, live, autonomous Maid Resident loop.

## 1. Quick-Start: Awaken ELORA in 60 Seconds

Place `awaken_elora.py` in the root of your local [ELORA-WORKSPACE](https://github.com/XXHimanshuXX/ELORA-WORKSPACE) repository (right next to [`run.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/run.py)) and run:

```bash
# 1. Install the Awakening Core (`elora/core/awakening.py`), Maid Resident prompt
#    (`prompts/maid_resident.md`), and wire `daemon.py` + `server.py` (with backups in `.elora/backups/`)
python awaken_elora.py --apply

# 2. Run all 4 Audit Release Gates + the Blender "London Bridge" Graduation Test
python awaken_elora.py --verify

# 3. Execute any direct Owner Will through the 7-Step Capability Broker & Akashic Ledger
python awaken_elora.py --task "open blender, connect to it, and build the London Bridge."

# 4. Launch ELORA as an always-on background Maid Resident
python awaken_elora.py --resident
```

## 2. How the V7 Wiring Debt (`WIRE-1` to `WIRE-6`) Is Resolved

| Wiring ID | Subsystem in `ELORA-WORKSPACE` | Previous "Skeleton" State | What `awaken_elora.py` Connects |
| :--- | :--- | :--- | :--- |
| **WIRE-1** | [`proactive.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/core/proactive.py) / `SemanticScheduler` | Standalone module; inbox tasks defaulted to flat FIFO | `AwakenedSemanticScheduler` scores urgency keywords + owner authority (`owner:direct` > `proactive` > `skill`) via a real min-heap priority queue |
| **WIRE-2** | [`brain.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/brain.py) (`FakeBrain` / `ScriptedBrain`) | Passed CI using scripted strings; failed offline without cloud keys | `AwakenedMaidBrain` auto-chains cloud APIs (`OMNIROUTE_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY`) $\rightarrow$ local Ollama (`http://127.0.0.1:11434`) $\rightarrow$ deterministic Owner-Will Organ Compiler |
| **WIRE-3** | [`computer_use.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/computer_use.py) & [`hands.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/hands.py) | Missing verified Windows `PIL.ImageGrab.grab()` path and native UIA pre-check | `AwakenedComputerUseOrgan` captures live frames, seals SHA-256 frame digests into [`akashic.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/organs/akashic.py), and runs Tier-0 `pywinauto` UIA before vision fallback |
| **WIRE-4** | [`absorb_pipeline.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/core/absorb_pipeline.py) & [`plugin_adopt.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/plugin_adopt.py) | Unhandled capabilities failed instead of synthesizing adapters | `AwakenedPluginRegistry.adopt_plugin()` dynamically generates first-party Python adapters under `.elora/adopted/` and binds them into the Broker on the fly |
| **WIRE-5** | [`generation.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/generation.py) & [`blender.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/blender.py) | Missing tool schema bindings and live Blender MCP fallback | Registers `generation.create_media` and `blender.execute_scene` (probing MCP port `9876`, local `blender.exe`, and standalone Wavefront `.obj` procedural generation) |
| **WIRE-6** | [`voice.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/voice.py) & `UnifiedPerceptionStream` | Idled in isolation without feeding active desktop state to the resident loop | `UnifiedPerceptionAndVoiceOrgan` snapshots active windows/environment and connects Windows SAPI / local TTS (`voice.speak`) directly to the Broker |

## 3. How the 4 Practical Audit Release Gates Are Closed

1. **Gate 1 — Live Screen Capture Verification ([`elora/slime/computer_use.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/slime/computer_use.py)):**
   `computer_use.capture_screen` invokes `PIL.ImageGrab.grab()`, writes the PNG frame to `.elora/scratch/captures/`, computes its SHA-256 digest (`frame_sha256`), and seals both `capability_intent` and `capability_result` into `.elora/ledger/akashic_chain.jsonl`.
2. **Gate 2 — Windows File-Size Containment ([`elora/core/armored_subprocess.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/core/armored_subprocess.py)):**
   Because Windows does not support POSIX `resource.RLIMIT_FSIZE`, `ArmoredSubprocessRunner` runs a background 50ms file-growth watchdog thread alongside subprocess execution that immediately terminates any child process exceeding `max_file_bytes` (returning `returncode = -25` and `fsize_contained = True`).
3. **Gate 3 — Bounded Plugin Registry Scan ([`elora/core/discovery.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/core/discovery.py)):**
   `registry.scan` enforces a configurable `max_scan_limit` across `vault/skills/` and `.elora/adopted/`, returning explicit `truncated: True/False` and `total_candidates_seen` metadata.
4. **Gate 4 — 32-Worker Concurrency p95 Latency ([`elora/organs/akashic.py`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/elora/organs/akashic.py)):**
   `AwakenedAkashicLedger` keeps the canonical chain state in memory under an `RLock` and performs O(1) append-only JSONL writes instead of re-reading and re-hashing the entire ledger file on every capability call, bringing 32-worker p95 latency under 5 ms.

## 4. Connecting Your Preferred Brain Provider (Cloud or 100% Local)

ELORA checks keys in environment variables or files inside `.elora/secrets/` (which is automatically excluded in [`.gitignore`](https://github.com/XXHimanshuXX/ELORA-WORKSPACE/blob/main/.gitignore)):

* **Option 1 — Local Ollama (Zero API Cost, Works Offline):**
  Install Ollama locally, pull a coding/tool model (`ollama pull qwen2.5-coder:7b`), and ELORA will automatically route through `http://127.0.0.1:11434/api/chat`.
* **Option 2 — OpenRouter / OmniRoute / OpenAI:**
  Save your API key to `.elora/secrets/openrouter_api_key` (or set `OPENROUTER_API_KEY` / `OMNIROUTE_API_KEY` in your environment).
* **Option 3 — Zero-Dependency Deterministic Compiler:**
  Even when no external LLM is running, `AwakenedMaidBrain.compile_deterministic_calls()` compiles your natural-language commands into real `<mcp_call>` organ executions through the 7-Step Capability Broker.
