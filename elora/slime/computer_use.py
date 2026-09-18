"""
computer_use.py — Tier0 perception and desktop actuation.

Provides screen perception (eyes) and zero-token UIA desktop actuation (hands).
- screen.capture: Risk.TRIVIAL, PIL.ImageGrab + SHA-256 in .elora/screenshots/
- screen.control: Risk.MODERATE, pywinauto backend (click, type_keys, get_window_text)
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys
import time
import uuid


SCREENSHOTS_DIR = os.path.abspath(os.path.join(".elora", "screenshots"))
DEFAULT_FUEL_LIMIT = 500


def get_screen_bounds() -> tuple[int, int]:
    """Return primary monitor dimensions (width, height)."""
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return (int(w), int(h))
        except Exception:
            pass
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return img.size
    except Exception:
        return (1920, 1080)


def capture(out_path: str | None = None) -> dict:
    """
    Capture a screenshot for perception (no control).
    Writes PNG to .elora/screenshots/ and returns path + SHA-256.
    """
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    if not out_path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        out_path = os.path.join(SCREENSHOTS_DIR, f"screen_{ts}_{unique_id}.png")

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    img = None
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception:
        pass

    if img is None:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (1920, 1080), color=(18, 18, 24))
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "ELORA Headless Perception Canvas", fill=(200, 200, 200))

    img.save(out_path, format="PNG")

    with open(out_path, "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()

    return {
        "path": out_path,
        "sha256": digest,
        "width": img.width,
        "height": img.height,
        "bytes": len(data),
    }


def click(x: int, y: int) -> dict:
    """
    Click at (x, y) coordinates with strict screen jailing.
    """
    width, height = get_screen_bounds()
    if x < 0 or x > width or y < 0 or y > height:
        raise ValueError(
            f"coordinates ({x}, {y}) out of screen bounds [0, 0, {width}, {height}]"
        )

    try:
        import pywinauto.mouse
        pywinauto.mouse.click(coords=(x, y))
    except ImportError:
        raise RuntimeError("pywinauto absent -> screen.control unreachable")

    return {"action": "click", "x": x, "y": y, "status": "ok"}


def type_keys(text: str, max_fuel: int = DEFAULT_FUEL_LIMIT) -> dict:
    """
    Type keys with strict fuel metering to prevent runaway loops.
    """
    if len(text) > max_fuel:
        raise ValueError(
            f"type_keys exceeded fuel limit: {len(text)} > {max_fuel}"
        )

    try:
        import pywinauto.keyboard
        pywinauto.keyboard.send_keys(text)
    except ImportError:
        raise RuntimeError("pywinauto absent -> screen.control unreachable")

    return {"action": "type_keys", "length": len(text), "status": "ok"}


def get_window_text(title: str = "") -> str:
    """
    Extract text from a window via UIA (zero vision tokens).
    """
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        if title:
            win = desktop.window(title_re=title)
            return win.window_text()
        return desktop.top_window().window_text()
    except ImportError:
        raise RuntimeError("pywinauto absent -> screen.control unreachable")
    except Exception as e:
        return f"error: {e}"


def main():
    parser = argparse.ArgumentParser(description="ELORA Computer Use CLI")
    parser.add_argument("--action", choices=["capture", "click", "type_keys", "read"], default="capture")
    parser.add_argument("--out", dest="out_path", default=None)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--text", default="")
    parser.add_argument("--target", default="")
    args = parser.parse_args()

    if args.action == "capture":
        res = capture(args.out_path)
        print(json.dumps(res))
    elif args.action == "click":
        res = click(args.x, args.y)
        print(json.dumps(res))
    elif args.action == "type_keys":
        res = type_keys(args.text)
        print(json.dumps(res))
    elif args.action == "read":
        txt = get_window_text(args.target)
        print(txt)


if __name__ == "__main__":
    main()
