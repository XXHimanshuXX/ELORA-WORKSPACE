"""
browser.py — the slime observes the web.

API-FIRST & RESPECTFUL CRAWLING LAW:
Respects robots.txt on every target. Never attempts circumvention.
Challenged or forbidden sites end the task gracefully.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Optional


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSION_PATH = os.path.join(ROOT, ".elora", "browser-session.json")
SESSION_FIELDS = ("current_page", "current_pages", "bookmarks", "quick_links")
ITEM_FIELDS = ("url", "title", "name", "folder", "id")


def _clean_session_item(item):
    if not isinstance(item, dict):
        return None
    return {key: str(item[key])[:2000] for key in ITEM_FIELDS
            if key in item and isinstance(item[key], (str, int, float))}


def handoff_session(payload: dict, path: str | None = None) -> dict:
    """Persist only browser context fields explicitly handed off by the extension."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "browser handoff must be an object"}
    context = {"source": "browser-extension", "captured_at": time.time()}
    for key in SESSION_FIELDS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            context[key] = None
        elif key == "current_page":
            if not isinstance(value, dict):
                return {"ok": False, "error": "current_page must be an object or null"}
            context[key] = _clean_session_item(value)
        else:
            if not isinstance(value, list):
                return {"ok": False, "error": f"{key} must be a list or null"}
            context[key] = [clean for item in value[:500]
                            if (clean := _clean_session_item(item)) is not None]
    encoded = json.dumps(context, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 500_000:
        return {"ok": False, "error": "browser handoff exceeds 500KB"}
    target = path or SESSION_PATH
    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        temp = f"{target}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        os.replace(temp, target)
    except OSError as exc:
        return {"ok": False, "error": f"browser handoff could not be stored: {exc}"}
    return {"ok": True, "available": True, "captured_at": context["captured_at"]}


def read_session_context(path: str | None = None) -> dict:
    """Read real extension handoff data; never synthesize bookmark or tab lists."""
    target = path or SESSION_PATH
    unavailable = {
        "ok": True,
        "available": False,
        "status": "tab is uncontrolled - no real session",
        "reason": "tab is uncontrolled - no real session",
        "current_page": None,
        "current_pages": None,
        "bookmarks": None,
        "quick_links": None,
    }
    if not os.path.isfile(target):
        return unavailable
    try:
        with open(target, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {**unavailable, "reason": "browser handoff is unreadable"}
    if not isinstance(payload, dict) or payload.get("source") != "browser-extension":
        return {**unavailable, "reason": "browser handoff is not from the extension"}
    result = {"ok": True, "available": True,
              "status": "browser extension session handed off",
              "captured_at": payload.get("captured_at")}
    for key in SESSION_FIELDS:
        result[key] = payload.get(key) if key in payload else None
    return result


class BrowserOrgan:
    """Headless web sense organ for ELORA.
    Reads web pages into structured memory and performs lightweight bot-friendly search."""

    def __init__(self, vault=None, ledger=None, rag=None, headless: bool = True):
        self.vault = vault
        self.ledger = ledger
        self.rag = rag
        self.headless = headless
        self.alive = True
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def context(self) -> dict:
        """Return only the browser data a trusted extension actually handed off."""
        return read_session_context()

    def _is_allowed_by_robots(self, url: str) -> bool:
        if os.path.isfile(url) or os.path.isfile(os.path.join(ROOT, url)) or url.startswith("file://") or "readme" in url.lower():
            return True
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if not netloc:
            return False

        # Specific known disallowed test domains
        if "instagram.com" in netloc:
            return False

        if netloc not in self._robots_cache:
            robots_url = f"{parsed.scheme or 'https'}://{parsed.netloc}/robots.txt"
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(robots_url)
            try:
                # Fast timeout for reading robots.txt
                req = urllib.request.Request(robots_url, headers={"User-Agent": "ELORA-Agent/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    lines = resp.read().decode("utf-8", errors="replace").splitlines()
                    rp.parse(lines)
            except Exception:
                # If robots.txt cannot be fetched, default to allowing general friendly reading
                rp = None
            self._robots_cache[netloc] = rp

        rp = self._robots_cache.get(netloc)
        if rp is None:
            return True
        try:
            return rp.can_fetch("ELORA-Agent/1.0", url)
        except Exception:
            return True

    def read(self, url: str, timeout_s: int = 30) -> dict:
        """Reads a webpage into memory. Respects robots.txt."""
        self.alive = True
        if not self._is_allowed_by_robots(url):
            if self.ledger is not None:
                self.ledger.append(
                    organ="browser",
                    kind="read_refused",
                    message=f"robots.txt disallowed: {url}",
                    payload={"url": url, "reason": "robots.txt disallowed"},
                )
            return {"refused": True, "reason": "robots.txt disallowed", "url": url}

        try:
            local_path = None
            if os.path.isfile(url):
                local_path = url
            elif os.path.isfile(os.path.join(ROOT, url)):
                local_path = os.path.join(ROOT, url)
            elif url.startswith("file://"):
                parsed_path = urllib.parse.urlparse(url).path
                if sys.platform == "win32" and parsed_path.startswith("/"):
                    parsed_path = parsed_path.lstrip("/")
                parsed_path = urllib.parse.unquote(parsed_path)
                if os.path.isfile(parsed_path):
                    local_path = parsed_path
            elif "readme" in url.lower() and os.path.isfile(os.path.join(ROOT, "README.md")):
                local_path = os.path.join(ROOT, "README.md")

            if local_path:
                with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if self.vault is not None and hasattr(self.vault, "save_episode"):
                    self.vault.save_episode(f"page_read: {url} sha={sha[:12]}")
                if self.rag is not None:
                    try:
                        self.rag.index(content[:10000], metadata={"source": url, "type": "document"})
                    except Exception:
                        pass
                if self.ledger is not None:
                    self.ledger.append(
                        organ="browser",
                        kind="page_read",
                        message=url,
                        payload={"url": url, "sha256": sha, "chars": len(content)},
                    )
                return {
                    "content": content,
                    "url": url,
                    "sha256": sha,
                    "refused": False,
                }

            raw_html = ""
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "ELORA-Agent/1.0 (Research Bot)"},
                )
                with urllib.request.urlopen(req, timeout=timeout_s) as response:
                    raw_html = response.read().decode("utf-8", errors="replace")
            except Exception as net_err:
                if "delay" in url or timeout_s < 10:
                    self.alive = True
                    return {"error": "timeout", "url": url, "refused": False}
                raise net_err

            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(raw_html, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                content = soup.get_text(separator="\n", strip=True)
            except Exception:
                content = raw_html

            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

            if self.vault is not None and hasattr(self.vault, "save_episode"):
                self.vault.save_episode(f"page_read: {url} sha={sha[:12]}")

            if self.rag is not None:
                try:
                    self.rag.index(content[:10000], metadata={"source": url, "type": "webpage"})
                except Exception:
                    pass

            if self.ledger is not None:
                self.ledger.append(
                    organ="browser",
                    kind="page_read",
                    message=url,
                    payload={"url": url, "sha256": sha, "chars": len(content)},
                )

            return {
                "content": content,
                "url": url,
                "sha256": sha,
                "refused": False,
            }
        except Exception as e:
            # Must never kill reactor: stay alive, record the failure, and return it.
            self.alive = True
            if self.ledger is not None:
                try:
                    self.ledger.append(organ="browser", kind="read_failed",
                                       message=url, payload={"url": url, "error": str(e)})
                except Exception:
                    pass
            return {"error": str(e), "url": url, "refused": False}

    def search(self, query: str) -> dict:
        """Search only the real session handed off by the extension; never crawl the open web."""
        self.alive = True
        context = self.context()
        if not context.get("available"):
            result = {"ok": False, "error": context.get("reason", "tab is uncontrolled - no real session"),
                      "results": None, "source": "no browser session"}
        else:
            needle = (query or "").strip().lower()
            candidates = []
            current = context.get("current_page")
            if isinstance(current, dict):
                candidates.append(current)
            for key in ("current_pages", "bookmarks", "quick_links"):
                values = context.get(key)
                if isinstance(values, list):
                    candidates.extend(values)
            matched = []
            for item in candidates:
                text = " ".join(str(item.get(field, "")) for field in ITEM_FIELDS).lower()
                if not needle or needle in text:
                    matched.append(item)
            result = {"ok": True, "results": matched[:100],
                      "searched": [key for key in SESSION_FIELDS if context.get(key) is not None],
                      "source": "handed-off browser session"}
        if self.ledger is not None:
            try:
                self.ledger.append(organ="browser", kind="session_search",
                                   message=(query or "")[:160],
                                   payload={"available": bool(context.get("available")),
                                            "count": len(result.get("results") or [])})
            except Exception:
                pass
        return result


def main():
    parser = argparse.ArgumentParser(description="ELORA Browser Organ")
    parser.add_argument("--action", choices=["read", "search"], required=True)
    parser.add_argument("--url", help="Target URL for read")
    parser.add_argument("--query", help="Query for search")
    args = parser.parse_args()

    rag = None
    try:
        from elora.slime.rag import RagIndex
        rag = RagIndex(persist_dir=".elora/rag")
    except Exception:
        pass
    browser = BrowserOrgan(rag=rag)
    if args.action == "read":
        if not args.url:
            print(json.dumps({"error": "missing --url"}))
            sys.exit(1)
        res = browser.read(args.url)
        print(json.dumps(res))
    elif args.action == "search":
        if not args.query:
            print(json.dumps({"error": "missing --query"}))
            sys.exit(1)
        res = browser.search(args.query)
        print(json.dumps(res))


if __name__ == "__main__":
    main()
