# PRODUCTION PROMPT: ELORA v8 — The Organism Meets the World

## 1. WHAT TO USE
- Primary Stack: Python 3.14 + Playwright (Chromium) + ChromaDB + pypdf + BeautifulSoup4 + urllib + Google Gemini API (keyed)
- Free Alternatives Checked: 
  - Browser: Playwright (100% open-source, local headless Chromium, zero subscription)
  - Semantic Memory: ChromaDB (100% local persistent vector store, zero cloud vector database cost)
  - Ingestion: pypdf & BeautifulSoup4 (pure local parsing, zero SaaS fees)
  - Generation: Gemini API (free tier / user Pro key stored in `.elora/secrets/gemini_api_key`)
- MCP Tools Available: Built-in armored shell (`shell.run_command`), VirtIO SHM ring, Akashic ledger (`ledger.verify`), Vault (`vault.save`, `vault.recall`)

## 2. WHY
- Problem it solves: Eliminates blindness and amnesia. Previously, ELORA could only act on locally scripted tools or synthetic tasks. v8 grants real-world sensory organs: reading the web, searching information, ingesting multi-modal documents, indexing into persistent semantic memory (RAG), and generating visual output.
- Autonomous impact: Gives the Drive Loop real eyes to browse when hungry (`EXPAND`), real ears to transcribe, a persistent semantic memory to recall answers hours later without re-fetching, and an active pulse (Heartbeat every 5m) so the user never faces a silent night.
- Why this stack vs others: Strict obedience to the Ring 0 safety laws:
  1. No CAPTCHA circumvention ever (challenged pages terminate or refuse).
  2. robots.txt is strictly obeyed (disallowed URLs are recorded as `read_refused`).
  3. No API keys in source code (keys strictly stored in `.elora/secrets/`).
  4. Every single read, ingest, and generation call is cryptographically appended to the Akashic ledger.

## 3. HOW - Step by Step
- Step 1: Implement Heartbeat in `elora/daemon.py` (`[HH:MM:SS] heartbeat #N | state=ALIVE | skills=N | ledger=SEQ`).
- Step 2: Implement `elora/slime/browser.py` with `BrowserOrgan` (headless Playwright + `urllib.robotparser` + BeautifulSoup search/read).
- Step 3: Implement `elora/slime/rag.py` with `RagIndex` (ChromaDB persistent client with cosine distance, idempotent upsert).
- Step 4: Implement `elora/slime/ingest.py` with `IngestionPipeline` (PDF text extraction, chunking with overlap, image captioning, video transcription, unsupported file refusal, metabolic budgeting).
- Step 5: Implement `elora/slime/generation_api.py` with `GenerationOrgan` (Gemini API generation, secret file reading, ledger logging).
- Step 6: Register capabilities in `elora/core/capabilities.py`: `net.read`, `net.search`, `doc.ingest`, `generate.image`.
- Step 7: Update `elora/core/drive.py` with `_seed_hunger` and browser-integrated expand hunger.
- Step 8: Wire organs in `run.py` (boot stages 9 and 10, preflight check inspection).
- Step 9: Author test suite in `tools/tests/test_browser_and_ingest.py` and create fixtures in `tests/fixtures/`.
- Step 10: Run full test suite and verify all test rungs pass green.

## 4. WHERE
- Where it will run: Local host Windows CLI runtime (`run.py --brain local`).
- Where data is saved: `.elora/rag/` (ChromaDB), `.elora/vault.db` (episodes), `.elora/akashic.db` (immutable hash chain), `.elora/secrets/` (keys).
- Where prompts are stored for reuse: `prompts/v8-sensory-organs-and-world-interaction.md`.

## 5. WHAT WILL BE THE IMPACT
- Short term (7 days): Slime can read real web pages, answer memory recall queries without web fetches, and demonstrate a visible terminal heartbeat.
- Long term (90 days): Complete autonomous lifelong learning cycle: browsing knowledge, ingesting papers/books into RAG, experimenting with newly learned skills, and producing multimodal media.
- Cost: $0.00 — local Playwright, ChromaDB, and pypdf; optional free Gemini API key.

## 6. FULL TASK PROMPT FOR BUILDER
Role: Principal Systems Architect & Slime Organ Engineer.
Context: Building v8 of ELORA OS based on the specification in Desktop/Next-Steps.txt.
Objective: Implement the Heartbeat pulse, Browser Organ (net.read, net.search), Ingestion Pipeline (doc.ingest), RAG Memory (ChromaDB), and Generation Organ (generate.image), pass all test rungs in tools/tests/test_browser_and_ingest.py, and verify run.py --check.
Constraints: 
- Strict compliance with robots.txt.
- Absolutely ZERO captcha bypass or evasion words in source code.
- No API keys in source code; read only from .elora/secrets/.
- Full backward compatibility with existing 130 tests.
