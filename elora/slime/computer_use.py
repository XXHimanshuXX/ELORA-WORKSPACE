"""
computer_use.py — Tier0 perception and desktop actuation.

Provides screen perception (eyes) and zero-token UIA desktop actuation (hands).
- screen.capture: Risk.TRIVIAL, PIL.ImageGrab + SHA-256 in .elora/screenshots/
- screen.control: Risk.MODERATE, pywinauto backend (click, type_keys, get_window_text)
- app.open: Risk.MODERATE, allowlisted desktop launch only
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
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
    synthetic=True means ImageGrab failed and a placeholder was written.
    """
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    if not out_path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        out_path = os.path.join(SCREENSHOTS_DIR, f"screen_{ts}_{unique_id}.png")

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    img = None
    synthetic = False
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception:
        pass

    if img is None:
        synthetic = True
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
        "synthetic": synthetic,
    }


APP_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad.exe",),
    "explorer": ("explorer.exe",),
    "calc": ("calc.exe",),
    "calculator": ("calc.exe",),
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "firefox": ("firefox.exe",),
    "code": ("Code.exe", "code.cmd", "code"),
    "browser": ("msedge.exe", "chrome.exe", "firefox.exe"),
    "blender": ("blender.exe",),
}
APP_ALIASES = {
    "google chrome": "chrome",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "file explorer": "explorer",
    "files": "explorer",
    "microsoft edge": "edge",
}


def resolve_allowed_app(name: str) -> str | None:
    """Map a spoken app name to an executable on PATH or a well-known install. None = refused."""
    raw = (name or "").strip().lower()
    if not raw:
        return None
    key = APP_ALIASES.get(raw, raw)
    candidates = APP_ALLOWLIST.get(key)
    if not candidates:
        return None
    import shutil
    for exe in candidates:
        found = shutil.which(exe)
        if found:
            return found
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        well_known = {
            "chrome.exe": (
                os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
            ),
            "msedge.exe": (
                os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            ),
            "firefox.exe": (
                os.path.join(pf, "Mozilla Firefox", "firefox.exe"),
            ),
            "Code.exe": (
                os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
            ),
            "notepad.exe": (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "notepad.exe"),),
            "explorer.exe": (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "explorer.exe"),),
            "calc.exe": (os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "calc.exe"),),
        }
        for exe in candidates:
            for path in well_known.get(exe, ()):
                if path and os.path.isfile(path):
                    return path
        if key == "blender":
            for base in (pf, pf86, r"D:\Program Files"):
                root = os.path.join(base, "Blender Foundation")
                if not os.path.isdir(root):
                    continue
                try:
                    names = os.listdir(root)
                except OSError:
                    continue
                for name in names:
                    cand = os.path.join(root, name, "blender.exe")
                    if os.path.isfile(cand):
                        return cand
    return None


def open_app(name: str) -> dict:
    """Launch one allowlisted desktop app. Never shell=True. Never an arbitrary path."""
    exe = resolve_allowed_app(name)
    if not exe:
        return {
            "ok": False,
            "error": f"app {name!r} is not on the house allowlist",
            "allowlist": sorted(set(APP_ALLOWLIST) - {"calculator", "browser"}),
        }
    if os.environ.get("ELORA_APP_OPEN") == "dry":
        return {"ok": True, "dry": True, "app": name, "exe": exe}
    kwargs: dict = {"close_fds": False, "shell": False}
    if os.name == "nt":
        kwargs["creationflags"] = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen([exe], **kwargs)
    return {"ok": True, "app": name, "exe": exe}


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
        try:
            pywinauto.keyboard.send_keys(text)
        except RuntimeError as e:
            if "SendInput" in str(e):
                return {"action": "type_keys", "length": len(text), "status": "simulated_headless"}
            raise
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
    parser.add_argument("--action", choices=["capture", "click", "type_keys", "read", "open"], default="capture")
    parser.add_argument("--out", dest="out_path", default=None)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--text", default="")
    parser.add_argument("--target", default="")
    parser.add_argument("--app", default="")
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
    elif args.action == "open":
        print(json.dumps(open_app(args.app)))


if __name__ == "__main__":
    main()
