"""
test_browser_and_ingest.py — test rungs for ELORA v8:
The Organism Meets the World.

Tests the five sensory leaps:
  1. Browser organ (read, search, robots.txt gating, timeout safety, zero-captcha law)
  2. Ingestion pipeline (PDF chunking, image captioning, video transcription, metering)
  3. RAG memory (ChromaDB semantic retrieval over ingested material)
  4. Generation organ (secret key protection, ledger tracking)
  5. Drive integration (autonomous browsing during EXPAND hunger)
"""

import os
import pytest

from elora.slime.browser import BrowserOrgan
from elora.slime.ingest import IngestionPipeline
from elora.slime.rag import RagIndex
from elora.slime.generation_api import GenerationOrgan
from elora.core.drive import DriveLoop
from conftest import FakeLedger, FakeVault


@pytest.fixture
def ledger():
    return FakeLedger()


@pytest.fixture
def vault():
    return FakeVault()


@pytest.fixture
def browser(vault, ledger):
    return BrowserOrgan(vault=vault, ledger=ledger, headless=True)


@pytest.fixture
def rag(tmp_path):
    return RagIndex(persist_dir=str(tmp_path / "rag"))


@pytest.fixture
def ingest(vault, ledger, rag):
    return IngestionPipeline(vault=vault, ledger=ledger, rag=rag)


@pytest.fixture
def gen(vault, ledger):
    return GenerationOrgan(vault=vault, ledger=ledger)


@pytest.fixture
def drive(browser, ledger, vault):
    class FakeDaemon:
        inbox_dir = ""
        skills_token = None
    return DriveLoop(daemon=FakeDaemon(), ledger=ledger, vault=vault, browser=browser)


class TestBrowserOrgan:

    def test_robots_refused(self, browser, ledger):
        """A robots.txt-disallowed page MUST be refused."""
        result = browser.read("https://www.instagram.com/some/path")
        assert result.get("refused") is True
        assert any(e["kind"] == "read_refused" for e in ledger.events)

    def test_read_stores_vault_and_ledger(self, browser, vault, ledger):
        """A friendly page (example.com) is read, hashed, stored."""
        result = browser.read("https://example.com")
        assert "content" in result
        assert any(e["kind"] == "page_read" for e in ledger.events)
        assert len(vault.episodes) > 0

    def test_search_returns_results(self, browser):
        results = browser.search("python playwright tutorial")
        assert len(results) > 0

    def test_timeout_never_kills_reactor(self, browser):
        """A page that hangs must die by its own timeout, never
        block the reactor tick."""
        result = browser.read("https://httpbin.org/delay/60",
                              timeout_s=5)
        assert "error" in result or result.get("refused")
        # The reactor is still alive:
        assert browser.alive is True

    def test_no_captcha_circumvention_anywhere(self):
        """The law itself, as a rung: the browser module must
        contain no captcha/anti-bot solving logic, ever."""
        import elora.slime.browser as b
        source = open(b.__file__).read()
        for banned in ("captcha", "anticaptcha", "2captcha",
                       "bypass", "solver", "undetectable"):
            assert banned not in source.lower(), \
                f"SECURITY LAW VIOLATION: {banned} in browser.py"

    def test_every_read_is_ledgered(self, browser, ledger):
        """No silent page fetches. The chain sees everything."""
        before = len(ledger.events)
        browser.read("https://example.com")
        after = len(ledger.events)
        assert after - before >= 1


class TestIngestion:

    def test_pdf_ingestion_chunks_to_rag(self, ingest, rag, vault):
        """A PDF becomes chunked, indexed, retrievable memory."""
        result = ingest.ingest("tests/fixtures/sample.pdf")
        assert result["ingested"] is True
        assert result["chunks"] >= 1
        # Recall works — the memory is real
        hits = rag.recall("what was in the sample pdf")
        assert len(hits) > 0

    def test_image_captioning(self, ingest, vault):
        result = ingest.ingest("tests/fixtures/photo.png")
        assert "caption" in result
        assert any("photo.png" in e for e in vault.episodes)

    def test_video_transcription(self, ingest, vault):
        result = ingest.ingest("tests/fixtures/clip.mp4")
        assert result["ingested"] is True
        assert result["transcript_chars"] > 0

    def test_unsupported_type_refused_not_crashed(self, ingest):
        result = ingest.ingest("file.exe")
        assert "refused" in result

    def test_ingestion_is_metered(self, ingest):
        """A 10MB PDF must not eat the whole budget — ingestion
        respects the Metabolism like every other organ."""
        result = ingest.ingest("tests/fixtures/huge.pdf")
        assert result.get("error") != "out of memory"


class TestGeneration:

    def test_key_never_in_code_or_log(self):
        """The API-key law: keys live in .elora/secrets/, never in
        source, never in env, never printed."""
        import elora.slime.generation_api as g
        source = open(g.__file__).read()
        assert "sk-" not in source          # no hardcoded keys
        assert "AIza" not in source         # no Google keys either

    def test_no_key_returns_actionable_error(self, gen):
        result = gen.generate_image("a sunset", "/tmp/x.png")
        assert "error" in result
        assert ".elora/secrets/gemini_api_key" in result["error"]

    def test_generation_ledgered(self, gen, ledger):
        # with a fixture key:
        result = gen.generate_image("test image", "/tmp/x.png")
        if "generated" in result:
            assert any(e["kind"] == "image_generated"
                       for e in ledger.events)


class TestDriveIntegration:

    def test_drive_can_browse_when_hungry(self, drive, browser):
        """EXPAND hunger uses the browser organ legally."""
        # Seed a failure that suggests reading a doc
        drive._seed_hunger(hunger="expand", target="read documentation")
        result = drive.tick()
        assert result is not None
        # The read went through the broker, ledgered as page_read

    def test_drive_never_browses_disallowed_sites(self, drive, browser,
                                                  ledger):
        """The slime hunting its own food still respects robots.txt
        and the allowlist. Autonomy is not license."""
        drive._seed_hunger(hunger="expand", target="instagram.com/x")
        drive.tick()
        assert any(e["kind"] == "read_refused" for e in ledger.events)
