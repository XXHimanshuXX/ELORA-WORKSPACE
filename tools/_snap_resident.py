import asyncio
import os
from playwright.async_api import async_playwright

DEST = r"C:\Users\HARSH\.gemini\antigravity\brain\caf98c78-cef8-4ff3-873a-ff6ee7b52ac7\resident_view.png"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            extra_http_headers={"X-ELORA-Client": "dashboard"}
        )
        page = await context.new_page()
        await page.goto("http://127.0.0.1:8765/")
        # Wait for the resident container to render
        await page.wait_for_selector("#resident-root", state="visible")
        # Give WebGPU/fallback and briefing poller a moment to settle
        await page.wait_for_timeout(2500)
        await page.screenshot(path=DEST)
        await browser.close()
        print(f"Captured {DEST} ({os.path.getsize(DEST)} bytes)")

if __name__ == "__main__":
    asyncio.run(main())
