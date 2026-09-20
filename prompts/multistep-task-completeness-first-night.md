# PRODUCTION PROMPT: Multi-Step Task Completeness Audit & The First Night Run

## 1. WHAT TO USE
- Primary Stack: Python 3.14 + Rust 1.98 PyO3 BitNet Kernel + Ollama (`qwen2.5:3b` / `qwen2.5:0.5b`)
- Free Alternatives Checked: Ollama (100% local, MIT, zero cloud cost), BitNet b1.58 native CPU kernel (0 network), SQLite Akashic Ledger & Vault (zero external db cost)
- MCP Tools Available: Built-in armored shell (`shell.run_command`), VirtIO SHM ring, Akashic ledger (`ledger.verify`), Vault (`vault.save`, `vault.recall`)

## 2. WHY
- Problem it solves: Solves step-pressure compression where a model compresses a multi-clause task to a single checkable component and exits prematurely. Prevents the ledger from confounding genuine complete execution with partial effort or unperformed work.
- Autonomous impact: Gives the slime honest self-assessment without rejecting partial work. `DONE_PARTIAL` tracks honest progress; `DONE_NO_WORK` catches hunger cycles that burn energy without digestion; `ok` records complete multi-step execution.
- Why this stack vs others: Deterministic regex/clause boundary parsing in core Python standard library avoids bulky external NLP dependencies, maintaining ELORA's sub-second hermetic execution and zero-network footprint.

## 3. HOW - Step by Step
- Step 1: Implement `count_imperative_clauses` in `elora/daemon.py` with `IMPERATIVE_VERBS`, clause delimiters, and exit-phrase filtering.
- Step 2: Implement `assess_task_completion` in `Daemon` returning `DONE_NO_WORK` (0 capability pairs), `DONE_PARTIAL` (fewer capability pairs than imperative clauses), or `ok`.
- Step 3: Wire `assess_task_completion` into `Daemon.tick()` and `DriveLoop._create()`.
- Step 4: Add `test_multistep_task_completeness` and `TestImperativeClauseCounting` to `tools/tests/test_reactor.py`.
- Step 5: Launch and monitor the overnight run (`python run.py --brain local`) to observe idle cryptobiosis, autonomous consolidation, allowlist gate integrity, and self-directed experiments.

## 4. WHERE
- Where it will run: Local host Windows CLI runtime (`run.py`).
- Where data is saved: `.elora/akashic.db` (immutable hash-chained diary), `.elora/vault.db` (episodic memory).
- Where prompts are stored for reuse: `prompts/multistep-task-completeness-first-night.md`.

## 5. WHAT WILL BE THE IMPACT
- Short term (7 days): The overnight fossil record distinguishes between idle pattern mining, immune system defenses (`expansion_refused`), and self-guided skill promotions.
- Long term (90 days): Autonomous evolution where the organism runs its own curriculum without human intervention, maintaining 100% cryptographic ledger auditability.
- Cost: $0.00 — completely offline, local open-source models, zero cloud API fees.

## 6. FULL TASK PROMPT FOR CLAUDE
Role: Principal Agentic OS Architect & Cryptographic Ledger Auditor.
Context: ELORA is an autonomous, sovereign agentic operating system. A local model was certified to read tasks, choose capabilities by name, emit valid MCP calls, accept Broker verdicts, observe execution results, and conclude. However, audit analysis revealed that models under step-pressure can compress multi-clause tasks into a single capability call.
Objective: Implement the safety rung `test_multistep_task_completeness` to record `DONE_PARTIAL` when imperative clauses exceed capability pairs, and `DONE_NO_WORK` when zero pairs occur upon DONE. Then prepare the environment for the overnight autonomous run (`python run.py --brain local`).
Instructions:
1. Parse imperative clauses cleanly using standard library regex, ignoring exit signals such as 'reply with DONE'.
2. Record task status honestly in `task_finished` ledger events without rejecting the task.
3. Validate across the full test suite (all 130 tests passing green).
4. Run the night and interpret the morning fossil record based on Akashic hash verification and event signatures.
Constraints: Zero external cloud dependencies, zero regression in existing test suite, strict preservation of the ledger immutability law.
