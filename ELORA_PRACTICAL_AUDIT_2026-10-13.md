# ELORA Practical Runtime, Feature, and Scaling Report

**Audit date:** 2026-10-13
**Workspace:** `D:\Coding\ELORA-Workspace`
**Practical surface:** existing Brave tab, `http://127.0.0.1:8765/`
**Live dashboard:** HTTP 200 · PID 20640 · Python 3.14.6
**Overall score:** **8.1/10** (unweighted mean across 13 areas)
**Readiness:** Repaired local prototype with a working low-risk execution path. It does **not** score 9/10 in every category.

## Executive summary

The blank Brave page was caused by HTTP/1.1 static responses that did not declare their response length. That was fixed and the page now renders. I used the existing Brave instance to inspect the app, send a read-only `git.status` request through Resident, and invoke “See Screen”.

The live `git.status` task completed through daemon and Broker, returned `rc=0`, and displayed a grounded summary. The task timeline and ledger contain the matching lifecycle evidence. The result receipt explicitly says `invariants_audited=false`: a successful process return code does not prove every invariant.

“See Screen” also reached the live task pipeline, but failed with `screen.capture rc=1: screen capture unavailable: screen grab failed`. ELORA surfaced the failure and did not fabricate an image. This remains the largest functional blocker.

Repairs also replaced hard-coded health claims with measured telemetry, removed fabricated task stages and unsupported invariant claims, restored live model routing, and reduced task-feed read latency. The full test suite, smoke run, and preflight pass. A 32-reader sample returned HTTP 200s, but p95 tails still reach about half a second.

I also inspected and operated the Resident UI in the existing Brave tab. The tested desktop view now has a wider composer, quieter mesh, no duplicate top actions, compact readable evidence rows, and a 12-of-50 recent-wills list with a working “Show all” control. Stale generic no-work replies and their matching prompts are hidden from the default history, while “Show all saved messages” keeps them available. Daily Briefing opens its actual ledger summary. A live “Hlo” run ended `DONE_NO_WORK` and displayed “Hello. I'm here. What would you like me to do?”

## Practical checks performed

| Live action | Result |
|---|---|
| Opened ELORA in the existing Brave tab | Dashboard rendered; Resident, Ledger, Genome, Registry, Router, and Not wired navigation were visible. |
| `/api/health` | HTTP 200; PID 20640; Python 3.14.6. |
| Resident read-only “git status” | ELORA spoke: `git.status: branch main; 125 changed paths (18 tracked, 107 untracked).` Trace: queued → started → capability intent → Broker `rc=0` → finished. |
| Resident greeting after daemon reload | Entered “Hlo” in the opened Brave UI; the live task finished `DONE_NO_WORK` and displayed “Hello. I'm here. What would you like me to do?” |
| Resident recent-wills control | Verified the default “Recent Wills (12 of 50)”, expanded to all 50, and returned to the compact view. |
| Daily Briefing UI action | Opened the Memory deck and displayed the ledger summary: 0 pages read, 0 documents ingested, 13 skills crystallized in the last 24 hours. |
| Resident “See Screen” | Real task failed with `screen.capture rc=1` and `screen grab failed`. No image was invented. |
| Genome page | Active v14 is dated October 3. v15/v16 are stored and adoptable. The active theme displays all 7 contrast floors passing. |
| Router | Reachable; catalog reported 971 models; status probe about 2.05 seconds with Claude1 configured. Actual prompt calls returned exact test strings via Claude1 (18.1 seconds) and `auto/best-coding` (14.3 seconds). |
| Organism and memory | BitNetBrain reported AWAKE; measured available RAM 1,187.2 MiB of 8,064.2 MiB, about 14.7% headroom. |
| Ledger integrity | Full Akashic chain verification returned `(True, None)` at sequence 7656. |

The app’s “TAB IS UNCONTROLLED — NO REAL SESSION” badge refers to its internal session-control state. It does not mean the Brave interactions above were theoretical or simulated.

## Category ratings

Scores describe this practical local run; they are not certifications. Overall is the unweighted mean of the 13 scores, rounded to one decimal.

| Category | Score | Evidence and remaining gap |
|---|---:|---|
| Static serving / initial render | **9.5** | Fixed HTTP keep-alive framing and confirmed rendering in Brave. A repeat cold-start measurement remains useful. |
| Resident interaction | **8.5** | Live read-only task returned a result grounded in tool output; the live greeting now explains when no capability ran. Failures remain visible. |
| UI layout / readability (tested desktop view) | **9.0** | Brave review confirmed balanced panels, readable compact trace rows, no horizontal overflow, a working 12/50 history control, truthful no-work text, and preserved full-history access. Mobile and screen-reader behavior were not evaluated. |
| Task execution path | **9.5** | Live Resident → daemon → Broker → `git.status` completed with linked lifecycle evidence. Only a read-only task was exercised. |
| Akashic ledger / audit evidence | **8.8** | Full chain verified; recent events link to the task. The receipt correctly distinguishes `rc=0` from invariant verification. |
| Genome / contrast / theme | **8.0** | 7/7 displayed contrast floors pass; weakest is 3.53:1 for a large-text-only faint token. Active v14 is older than stored v15/v16. |
| Registry / discovery | **7.5** | Inventory is indexed, paginated, cached, and reports duplicates. A live scan covered 5,308 directories and 3,660 entries in about 5 seconds, was truncated, and the plugin loader remains unavailable. |
| Router / provider | **9.2** | Live 971-model catalog and exact-output completions verified. Requests took 14–18 seconds; no broad failover/reliability test was run. |
| Perception / screen capture | **2.0** | Real capture action fails with `rc=1`. It fails closed, but perception is unavailable in this run. |
| Resource telemetry | **9.4** | RAM is measured rather than defaulted to 70% headroom; current measured headroom was 14.7%. Longer-run resource behavior is unverified. |
| Security / execution boundaries | **6.5** | Destructive gate is closed and jailed smoke checks pass. Windows lacks `RLIMIT_FSIZE`; Job Object limits are 10 seconds, 512 MiB, one process; tiers ≥ PROBATION are blocked. Not a full security audit. |
| Error visibility | **9.2** | Router and capture failures surface as actual status/errors; the capture path does not claim synthetic health. |
| Performance / scaling | **8.5** | Task caching/indexing cut median task reads substantially; 16–32 reader p95 tails still approach 0.5 seconds. No soak test. |

**Mean:** 8.12/10, reported as **8.1/10**. The mean masks the capture blocker: ELORA should not be called fully ready while a core perception action fails.

## Automated verification

| Check | Result |
|---|---|
| Full `tools/tests` suite | **285 passed, 13 warnings, 135.74 seconds**, exit 0. |
| `run.py --smoke` | **GREEN**, exit 0: task loop, real subprocess, Akashic chain, capability names. |
| `run.py --check` | **0 failures, 4 warnings**, exit 0. Imports, Ollama, Tauri, destructive gate, BitNet, WASM fuel trapping, VirtIO checksum/tamper detection, Tauri ring, WebGPU on NVIDIA GTX 1050, pywinauto, and generation checks passed. |
| `git diff --check` | Exit 0; no whitespace errors. Git reported line-ending normalization notices for existing LF files. |

Preflight warnings: 8,064 MiB RAM is below the 8,192 MiB “comfortable” mark; POSIX `RLIMIT_FSIZE` is unavailable on Windows; Job Object limits are active; higher execution tiers are refused by Windows policy.

## Read-only scaling sample

Five requests per worker at concurrency 1, 8, 16, and 32; all returned HTTP 200. At 32 readers, each endpoint received 160 requests. This one-host sample is not a capacity or endurance guarantee.

| Endpoint | Readers | p50 | p95 |
|---|---:|---:|---:|
| `/api/tasks?limit=50` | 1 | 15.4 ms | 16.3 ms |
| | 8 | 15.1 ms | 32.8 ms |
| | 16 | 18.3 ms | 518.4 ms |
| | 32 | 22.6 ms | 542.6 ms |
| `/api/ledger?limit=50` | 1 | 15.6 ms | 15.7 ms |
| | 8 | 12.0 ms | 31.1 ms |
| | 16 | 40.5 ms | 54.9 ms |
| | 32 | 62.8 ms | 528.6 ms |
| `/api/health` | 1 | 16.0 ms | 18.8 ms |
| | 8 | 3.9 ms | 23.0 ms |
| | 16 | 4.3 ms | 516.3 ms |
| | 32 | 6.0 ms | 516.2 ms |

Task median at 32 readers is about 23 ms, down from about 1.46 seconds before the event index/cache changes. The remaining p95 spikes need profiling and a longer soak before setting a concurrency limit.

## Repairs completed

- Fixed HTTP/1.1 static-response framing so Brave completes page loading.
- Replaced fabricated/defaulted organism telemetry with measured metrics.
- Made screen capture fail closed and report its actual error.
- Removed unsupported invariant claims and synthetic task-stage completion.
- Added successful tool-result summaries and truthful no-work replies to Resident speech.
- Reworked Resident layout, filtered stale no-work pairs without deleting saved history, and made task evidence rows and the recent-wills list easier to scan.
- Restored local OmniRoute and verified real model responses.
- Indexed task-to-ledger event matching and cached task payload construction, with invalidation/coalescing coverage.
- Bounded ledger reads and retained task evidence links.

## Work still required

1. **Restore real screen capture:** diagnose why `PIL.ImageGrab.grab()` fails under the live Windows dashboard process; verify a real frame and matching ledger result.
2. **Close Windows execution-policy gap:** find a supported file-size limit and define controls before enabling higher tiers.
3. **Reduce 16–32 reader tail latency:** profile the half-second p95 spikes, repeat the benchmark, and run a soak.
4. **Finish Registry integration:** address scan truncation/cold cost and unavailable plugin loader.
5. **Review Genome v15/v16:** compare the actual visual result before adopting; a saved generation alone is not proof of improvement.
6. **Validate Resident on more surfaces:** test smaller viewports, keyboard navigation, and screen-reader output; the 9/10 UI score is for the reviewed desktop Brave view.

## Workspace and data state

- The read-only Resident result reported branch `main`, 125 changed paths (18 tracked, 107 untracked). No commit or push was made.
- Four October 2 files remain in `.elora/inbox/.processing/`. They were preserved and not executed or deleted. The top-level inbox was empty; the daemon polls top-level inbox files, not that hidden processing directory.
- `.pytest-tmp-codex/`, `scratch/`, existing vault skill artifacts, and unrelated working-tree changes were preserved.
- This replaces the stale earlier scorecard with practical evidence, measured results, and explicit failures.
