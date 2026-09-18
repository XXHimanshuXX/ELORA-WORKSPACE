"""
overlay_bridge.py — broker.request() ripples the WebGPU organism.

The Tauri overlay (overlay/index.html + organism.wgsl) reads this
counter or shared-memory ring. No window is required for the kernel to run.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from elora.core.virtio_shm import VirtioShmRing, RingEvent

DEFAULT_RING_PATH = os.path.join(".elora", "shm", "overlay.ring")

_last = {"capability": "", "ts": 0.0, "n": 0}
_ripple_counter = 0
_ring_cache: dict[str, VirtioShmRing] = {}


def _get_ring(path: str) -> VirtioShmRing:
    norm_path = os.path.abspath(path)
    if norm_path not in _ring_cache:
        _ring_cache[norm_path] = VirtioShmRing(norm_path, slots=64, create=True)
    return _ring_cache[norm_path]


def close_ring(path: str | None = None) -> None:
    if path is None:
        close_all_rings()
        return
    norm_path = os.path.abspath(path)
    if norm_path in _ring_cache:
        try:
            _ring_cache[norm_path].close()
        except Exception:
            pass
        del _ring_cache[norm_path]


def close_all_rings() -> None:
    for ring in list(_ring_cache.values()):
        try:
            ring.close()
        except Exception:
            pass
    _ring_cache.clear()


def ripple(capability: str) -> None:
    """Legacy / in-memory counter update for test harness & local queries."""
    global _ripple_counter
    _ripple_counter += 1
    _last["capability"] = capability
    _last["ts"] = time.time()
    _last["n"] = _ripple_counter


def last() -> dict:
    return dict(_last)


def emit_ripple(organ: str, kind: str, ring_path: str | None = None) -> RingEvent:
    """
    Writes SPSC ring event with payload and checksum slot to .elora/shm/overlay.ring.
    Falls back to file poll if mmap fails on Windows.
    """
    global _ripple_counter
    _ripple_counter += 1
    p = ring_path or DEFAULT_RING_PATH

    payload_dict = {
        "organ": organ,
        "kind": kind,
        "counter": _ripple_counter,
        "ts": time.time(),
    }
    payload_bytes = json.dumps(payload_dict).encode("utf-8")

    try:
        ring = _get_ring(p)
        ev = ring.push(payload_bytes)
    except Exception:
        # Fallback to direct file poll if mmap fails on Windows
        parent = os.path.dirname(os.path.abspath(p))
        if parent:
            os.makedirs(parent, exist_ok=True)
        fallback_json = p + ".json"
        with open(fallback_json, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload_dict))
        ev = RingEvent(epoch=_ripple_counter, payload=payload_bytes, offset=64, checksum="")

    _last["capability"] = f"{organ}.{kind}"
    _last["ts"] = payload_dict["ts"]
    _last["n"] = _ripple_counter
    return ev


def verify_and_read(ring_path: str | None = None) -> dict | None:
    """
    Pops next ripple event from SPSC ring and verifies checksum.
    Raises RuntimeError on slot checksum or header checksum failure.
    """
    p = ring_path or DEFAULT_RING_PATH
    try:
        ring = _get_ring(p)
        ev = ring.pop()
        if ev is None:
            return None
        return json.loads(ev.payload.decode("utf-8"))
    except RuntimeError:
        # Checksum errors must propagate to detect tampering
        raise
    except Exception:
        fallback_json = p + ".json"
        if os.path.exists(fallback_json):
            try:
                with open(fallback_json, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None


def read(ring_path: str | None = None) -> dict | None:
    """Convenience alias for verify_and_read."""
    return verify_and_read(ring_path)
