"""Manual, local-only smoke for the Resident inbox handoff.

Set ELORA_CONSOLE_URL to the already-running console URL. This smoke only queues
one harmless will, checks its client identity and Akashic evidence, and leaves
processing to the CORE daemon. It does not click tool shortcuts or visit websites.
"""

import asyncio
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.environ.get("ELORA_CONSOLE_URL", "").rstrip("/")
SCREENSHOT = ROOT / ".elora" / "screenshots" / "resident-live-smoke.png"


async def test_live_resident():
    if not BASE_URL:
        raise RuntimeError("Set ELORA_CONSOLE_URL to the already-running console URL")

    prompt = "Resident smoke: reply DONE only; do not call tools."
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 850})
        await page.goto(BASE_URL + "/", wait_until="domcontentloaded")
        await page.wait_for_selector("#resident-root", state="visible")
        await page.wait_for_selector("#chat-input", state="visible")

        compose = page.locator("#chat-input")
        assert await compose.get_attribute("placeholder") == "Speak will..."
        await compose.fill("first line")
        await compose.press("Shift+Enter")
        await compose.type("second line")
        assert await compose.input_value() == "first line\nsecond line"
        await compose.fill(prompt)

        async with page.expect_response(
            lambda response: response.url.endswith("/api/inbox/task")
            and response.request.method == "POST"
        ) as posted:
            await compose.press("Enter")
        response = await posted.value
        assert response.ok, f"inbox endpoint returned HTTP {response.status}"
        headers = await response.request.all_headers()
        assert headers.get("x-elora-client") == "resident-overlay"
        payload = await response.json()
        task_id = payload["task_id"]
        await page.locator('.turn[data-role="will"]').filter(has_text=prompt).wait_for()
        await page.screenshot(path=str(SCREENSHOT))
        await browser.close()

    from elora.organs.akashic import AkashicLedger
    ledger = AkashicLedger(str(ROOT / ".elora" / "akashic.db"))
    try:
        intact, first_bad = ledger.verify()
        assert intact, f"Akashic verification failed at {first_bad}"
        queued = next(
            event for event in reversed(ledger.recent_events(kind="task_queued", n=100))
            if event.get("payload", {}).get("filename") == task_id
        )
        assert queued["payload"]["client"] == "resident-overlay"
        assert queued["payload"]["task"] == prompt
        print(
            f"queued {task_id}; Akashic seq={queued['seq']} "
            f"hash={queued['hash']} screenshot={SCREENSHOT.relative_to(ROOT)}"
        )
    finally:
        ledger.conn.close()


if __name__ == "__main__":
    asyncio.run(test_live_resident())
