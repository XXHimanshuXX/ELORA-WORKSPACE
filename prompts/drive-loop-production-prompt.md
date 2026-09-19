# PRODUCTION PROMPT: ELORA Drive Loop (Curiosity Engine)

## 1. WHAT TO USE
- Primary Stack: Python 3.14 + Rust 1.98 PyO3 BitNet Kernel + Ollama (`qwen2.5:0.5b`)
- Free Alternatives Checked: Ollama (100% local, zero cost, MIT), BitNet b1.58 (local CPU, 0 network)
- MCP Tools Available: Built-in armored shell, VirtIO SHM ring, Akashic ledger

## 2. WHY
- Problem it solves: Eliminates the "vending machine" bottleneck where an agent OS only reacts to human inbox drops.
- Autonomous impact: Enables idle-state self-consolidation, failure-driven targeted absorption, and self-directed skill experimentation without granting privileged escape hatches.
- Why this stack vs others: Adheres strictly to the 4 Ring 0 safety lines (Broker liturgy, ceiling enforcement, allowlist membranes, and metabolic budgets).

## 3. HOW - Step by Step
- Step 1: Awaken the mind with local Ollama (`qwen2.5:0.5b`) and verify cryptographic ledger chain.
- Step 2: Implement `elora/core/drive.py` with `Hunger` dataclass and 3 hungers (`CONSOLIDATE`, `EXPAND`, `CREATE`).
- Step 3: Wire `drive.tick()` into reactor when inbox is idle.
- Step 4: Author and pass the 4 safety test rungs in `tools/tests/test_drive.py`.
- Step 5: Verify all 128 tests pass green and push to `origin main`.

## 4. WHERE
- Where it runs: ELORA OS runtime on local Windows host.
- Where data is saved: `.elora/vault.db`, `.elora/akashic.db`.
- Where prompts are stored: `prompts/drive-loop-production-prompt.md`.

## 5. WHAT WILL BE THE IMPACT
- Short term: ELORA autonomously consolidates episodic patterns and practices under-tiered skills during idle time.
- Long term: A living organism that learns and grows in the dark without human babysitting.
- Cost: $0.00 — completely offline and free forever.
