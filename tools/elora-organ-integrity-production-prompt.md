# PRODUCTION PROMPT — ELORA Organ Integrity Pass (v1)

**Date:** 2026-10-14
**Author:** Prime Orchestrator session (grounded audit)
**Status:** Awaiting owner selection of build target
**Supersedes:** the "awaken_elora / chronos / omega singularity" drop-in bundles (rejected — see §1)

---

## 1. WHAT WAS REJECTED, AND WHY (evidence, not opinion)

Three drop-in bundles were offered (`.monkeycode/uploads/`) claiming to "awaken" or "upgrade"
ELORA without breaking the 285-test suite. They were **not deployed**. Audit finding: **NET REGRESS.**

| Uploaded artifact | Target | Repo bytes | Upload bytes | Effect |
|---|---|---|---|---|
| `app.js` | `overlay/app.js` | 119,399 | 13,692 | −105,707 B; real API console → static HUD |
| `organism_mesh.json` | `overlay/organism_mesh.json` | 661,090 | 5,084 | −656,006 B (129× smaller) |
| `styles.css` | `overlay/styles.css` | 87,680 | 13,759 | −73,921 B |
| `overlay_bridge.py` | `elora/overlay_bridge.py` | 4,137 | 2,869 | deletes `ripple`/`emit_ripple` API |
| `src_tauri_main.rs` | `src-tauri/src/main.rs` | 7,548 | 3,983 | removes `:8765` console-server startup the window URL depends on |
| `index.html` / `organism.js` / `tauri_bridge.js` | `overlay/*` | — | — | breaks ES-module contract (`Organism`, `initTauriBridge` gone) |

Additional defects found in the bundles:

- **Mutates on a bare run.** `awaken_elora.py` executes `apply_awakening_to_workspace()` when given
  *no* flags; `deploy_chronos_production_stack.py` calls `deploy_stack()` unconditionally (`--deploy`
  is parsed but never read — dead flag).
- **No rollback.** Backups are `shutil.copy2` into `.elora/backups/`, which is **gitignored** — so
  `git clean -xdf` destroys the only copy. No `restore` path exists.
- **Broken symbol.** Uploaded `overlay_bridge.py:78` calls `VirtioShmRing.write()`, which does not
  exist (the class has `push`/`pop`/`close`/`verify_header`) — wrapped in `except Exception: pass`,
  so SHM telemetry silently no-ops.
- **Duplicate subsystems.** Despite "wiring" language, `broker.py`/`metabolism.py`/`decay.py` are
  untouched; the bundle adds a *parallel* ledger and a second daemon instance.
- `elora_omega_singularity_os.html` (312 KB) and a 7.9 MB stray PNG temp have **no install route** —
  they are orphaned.

**Genuine, limited upside:** `elora/core/awakening.py` (1,556 lines) and `prompts/maid_resident.md`
are net-new and conflict with nothing. They are the only salvageable pieces, and only if wired
*into* the existing organs rather than beside them.

---

## 2. THE SIX "WIRING DEBT" CLAIMS — VERDICT

The premise that ELORA is a "skeleton" is false, and most of the listed gaps are stale or invented.

| # | Claim | Verdict | Reality |
|---|---|---|---|
| 1 | Live inference unwired; offline Ollama not wired; relies on FakeBrain | **FALSE** | Real HTTP inference at `elora/brain.py:115-133` (`/v1/chat/completions`); selected in production at `run.py:494-503`; Ollama default `run.py:52-63`. `FakeBrain` **does not exist**; `ScriptedBrain` is test-only. Loader fallback `qwen2.5:3b → llama3.2:3b → qwen2.5:0.5b → BitNet` at `loaders.py:169-173`. |
| 2 | `SemanticScheduler` / `UnifiedPerceptionStream` unwired; organs idle | **FALSE** | Both classes **do not exist in code at all** — they survive only in `docs/ELORA-TRUE-BLUEPRINT-V7-UPGRADE.md:14-34`. The real organs *are* wired: `voice`/`generation` via `broker.py:374-387,718-768`; `absorb_pipeline` via `daemon.py:668-670`; `proactive` via `daemon.py:1064-1065`. |
| 3 | No live `ImageGrab.grab()`; no Tier-0 UIA | **PARTLY TRUE** | Capture is real and reachable (`computer_use.py:63-69` → `broker.py:374-375` → `daemon.py:465-507`). But there is **no UIA pre-check before vision** (`click()` is blind coordinate injection, `computer_use.py:197`), and the frame SHA-256 never reaches the ledger. |
| 4 | POSIX-only containment; discovery unbounded | **PARTLY TRUE** | Discovery **is** bounded (`discovery.py:206-208` depth 8 / cap 200k, `truncated` metadata). RLIMIT is correctly POSIX-gated (`armored_subprocess.py:122-123`) and Windows has a watchdog + Job Object — **but** only *memory* is set; `PROCESS_TIME`/`ACTIVE_PROCESS` are advertised in `run.py:283`/`SUMMARY.md:8` and never written into `BasicLimitInformation`. |
| 5 | 32-worker ledger p95 spikes | **FALSE (misattributed)** | Ledger is serialized behind one conn + `RLock` + `BEGIN IMMEDIATE` (`akashic.py:28-31,127-140`). No ledger p95 benchmark exists. The ~0.5 s p95 figure is about **dashboard HTTP readers** and is already documented in the audit docs. |
| 6 | Tauri/overlay need sidecar packaging | **PARTLY TRUE** | Repo is **Tauri v1** (`Cargo.toml:9,12`), not v2. Rust *does* spawn Python (`main.rs:137-186`) but child handles are discarded (`main.rs:148,173`) — no lifecycle. Also it spawns `run.py --brain bitnet`, **not** `--resident`. |

---

## 3. THE REAL GAPS (ranked, from code — not from the claims)

1. **Voice is a facade.** `elora/slime/voice.py:31-54` — `listen()`/`speak()` only probe
   `import sherpa_onnx` and return `{"transcript": "", "degraded": ...}`. It is fully registered and
   broker-wired, so it returns *success-shaped JSON while doing no ASR or TTS*.
2. **The metabolic body is orphaned.** The shader actually on screen (`overlay/organism.js`, GLSL)
   is driven by `/api/organism_state` polling (`overlay/app.js:1075-1099`), **not** by
   `organism.wgsl`'s uniform contract and **not** by the virtio `overlay.ring`. Nothing loads
   `organism.wgsl`. `elora/overlay_bridge.py:2-8` admits it: *"fills a ring and bumps a counter that
   nothing renders from."*
3. **Sight is outside the tamper-evident chain.** `daemon._perceive` writes the screenshot SHA-256 to
   `.elora/state.json` only (`daemon.py:498-507`). The Akashic ledger has no perception event, so
   screen evidence is editable in plain JSON without detection — defeating the project's core claim.
4. **Windows containment weaker than advertised.** Job Object sets memory only; CPU/RAM kill rests on
   a 50 ms soft polling thread; job-assignment failure is swallowed (`armored_subprocess.py:307-310`).
5. **Declared capability ≠ executed code.** `generate.image` is declared as
   `python -m elora.slime.generation_api` (`capabilities.py:245-249`) but the broker intercepts and
   runs `generation.py` in-process (`broker.py:382-383,718-740`).
6. **No inference fallback at the decision boundary.** `daemon.py:730-735` fails the task on any
   `brain.complete` exception; the fallback chain lives in a different layer (`loaders.py:234-252`).
7. ~~**Tauri sidecar has no lifecycle.** Handles dropped; no readiness, shutdown, or restart.~~
   **CORRECTED (2026-10-14):** this was wrong. Tauri v1 inserts every spawned child into a
   global `ChildStore` (`command.rs:269`) and calls `kill_children()` from
   `cleanup_before_exit()` (`app.rs:577-581`), which is active because `shell-sidecar` is
   enabled. Discarding `_child` was idle, not a leak. The real defects were **silent spawn
   failure** and **no crash recovery** — see the session log below.

---

## 4. FULL TASK PROMPT FOR THE BUILD

> **Role.** You are the ELORA systems engineer. The house doctrine is *RUN, don't claim*: no organ may
> report success it did not achieve, and no action may be reported without a ledger entry.
>
> **Objective.** Close gaps 1, 2, 3 and 5 above — the ones where the system *misrepresents itself* —
> without regressing any of the 285 tests. Prefer making a surface honest over making it bigger.
>
> **Hard constraints.**
> 1. Never overwrite `overlay/*` wholesale; the existing console is load-bearing and test-enforced.
> 2. Every new capability must be registered in `elora/core/capabilities.py` AND executed in
>    `elora/core/broker.py`. No side-channels.
> 3. Any perception or actuation event must be appended to the Akashic ledger via
>    `elora/organs/akashic.py` — no plain-file-only state for evidence.
> 4. Preserve the workspace jail. Use the house pattern: `realpath` + `normcase` + `commonpath`
>    (`elora/slime/hands.py:34-48`), never raw `startswith` on `abspath`.
> 5. `python -m pytest tools/tests -q` must stay green. `tools/tests` is the real suite.
>    Interpreter: `C:\Python314\python.exe`.
> 6. Do not commit. Show the diff and the test output.
>
> **Work items.**
> - **W1 — Voice honesty.** Either implement real ASR/TTS via a locally available backend, or make
>   `voice.py` return an explicit `unavailable` status that the broker surfaces as such. No more
>   success-shaped JSON. Add a test asserting the degraded path is labelled.
> - **W2 — One metabolic contract.** Pick one: bind `overlay/organism.wgsl` uniforms to live
>   metabolism and render it, or delete the dead ring path and document that `organism.js` polls
>   `/api/organism_state`. Do not leave both. If binding, publish `overlay_status.json` from
>   `elora/overlay_bridge.py` and add a consumer test.
> - **W3 — Perception into the chain.** Extend the Akashic ledger with a perception event type and
>   append `screen.capture` frame hashes from `daemon._perceive`. Add a test proving a mutated
>   `state.json` hash is detectable against the chain.
> - **W4 — Capability truth.** Reconcile `generate.image`: make the declared command and the executed
>   code agree, and add a test that asserts declared == executed for every `REGISTRY` entry.
> - **W5 — Windows containment honesty.** Actually set `PROCESS_TIME`/`ACTIVE_PROCESS` in the Job
>   Object `BasicLimitInformation`, or remove them from `run.py:283` and `SUMMARY.md:8`. Do not
>   advertise limits the code does not enforce.
> - **W6 — Inference fallback.** Add a bounded retry/degrade path at `daemon.py:730-735` so a downed
>   endpoint degrades the organism instead of failing the task.
>
> **Output format.** For each item: files touched, the diff, the command run, and the observed result.
> Mark anything not verified as UNVERIFIED. Report honestly if an item is infeasible.

---

## 5. IMPACT

- **Immediate (this pass):** the system stops over-claiming. Every already-green capability becomes
  trustworthy, which is the precondition for adding anything new.
- **30 days:** a resident whose visible state, spoken state, and ledger state cannot disagree.
- **Cost:** $0. Local Ollama / existing stack only. No new paid dependency; no bundle install.

## 6. ALTERNATIVES IF THE OWNER PREFERS A DIFFERENT AXIS

- **Alt A — Wire the Tauri shell end-to-end (gap 2/7).** Manage the child process lifecycle in
  `src-tauri/src/main.rs`, switch to `run.py --resident`, add readiness/shutdown, and drive the real
  organism mesh from live metabolism. Highest *visible* payoff.
- **Alt B — Salvage `awakening.py` properly.** Keep only the net-new 1,556-line module and
  `prompts/maid_resident.md`, and rewrite its `Awakened*` classes as thin adapters over the existing
  `broker.py` / `metabolism.py` / `akashic.py` instead of parallel reimplementations. No overwrites.
- **Alt C — Windows-native hardening (gap 4).** Enforce real CPU-time/process-count Job Object limits
  and remove the soft-polling dependency. Lowest risk, no UI.

---

## 7. ENVIRONMENT NOTES

- Real suite: `tools/tests` (31 files). `tests/` at repo root holds only fixtures.
- Interpreter that has pytest + deps: `C:\Python314\python.exe`. The bundled
  `Python\pythoncore-3.14-64\python.exe` has **no pytest** — do not use it for tests.
- `scratch/stolen_repos/` is untracked and contains third-party cloned projects
  (`AgentVerse-OS`, `eidetic-os`, `OpenDAN`, `eidolon-os`). Flagged for owner decision — not ELORA code.

---

## 8. SESSION LOG

### 2026-10-14 — Axis: "Make the Resident actually live"

**Two premises of that axis were disproved before any code was written:**

1. Children are **not** orphaned (corrected above).
2. The on-screen organism is **already** driven by live metabolism:
   `overlay/app.js:1075-1095` `pollOrganism()` → `/api/organism_state` →
   `payload_organism_state()` (`server.py:897-936`) reads real `.elora/state.json` plus a live
   RAM snapshot, then calls `organism.setState/setSeed/setHeadroom`. The virtio ring in
   `elora/overlay_bridge.py` is a *second, dead* channel — not the live one.
3. Starting the console server twice stays forbidden: the browser-oriented resident entrypoint
   on `run.py` also starts one (`run.py:470-473` → `tools/_start_server.py`), so the Tauri host
   continues to own the server alone. `tools/tests/test_tauri.py` guards this, and its rationale
   is correct.

**Shipped — `src-tauri/src/main.rs` (the honest-failure pass):**

| Change | Why |
|---|---|
| `spawn()` result no longer discarded | The old `if let Ok((mut rx, _child)) = cmd.spawn()` swallowed the error. With an unresolvable `python` the console server never bound port 8765 and the window loaded a refused connection with no explanation anywhere. |
| Failure written to stderr **and** `.elora/tauri_shell.json` | A dead window now has a written reason. `.elora/state.json` (daemon) and `.elora/tauri_shell.json` (shell) stay separate, so "organism not reporting" and "shell could not start it" remain distinguishable. |
| `status`/`pid` recorded only on observed facts | `running` is set only after a spawn succeeds, using the real `child.pid()` — the same rule the state commands already follow. |
| Bounded crash recovery (`MAX_RESTARTS = 3`) | A resident that dies stays dead otherwise. A clean exit is treated as a shutdown request and is *not* restarted. |
| `ELORA_PYTHON` override | A bare `python` on Windows can resolve to the Microsoft Store stub, which exits non-zero without running anything. |

**Verified:** `cargo check` exit 0, **zero errors, zero warnings** (`tools/_check_rust.py`).
`python -m pytest tools/tests -q` → **286 passed**. The new
`test_tauri_shell_reports_failures_and_supervises_crashed_children` was proven to have teeth:
10 of its 11 invariants are absent from the pre-change revision, so it would have failed
against the old shell.

**Still open on this axis (not done):** the shell writes `.elora/tauri_shell.json`, but no UI
consumes it yet. The next step is to surface it in `overlay/app.js` as a truthful banner
("resident not running: <reason>") rather than adding another unread artifact.
