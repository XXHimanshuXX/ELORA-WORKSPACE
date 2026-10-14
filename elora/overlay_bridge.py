"""
overlay_bridge.py — broker.request() ripples the WebGPU organism.

This is the producer side. The shader that consumes it (overlay/organism.wgsl)
still exists and is still structurally verified, but the console rebuilt around the
generated genome no longer mounts a canvas to host it. So today this fills a ring
and bumps a counter that nothing renders from. No window is required for the
kernel to run — and "the organism is on screen" would be an overstatement.

"""

from __future__ import annotations

import json
import os
import time
import datetime
import pathlib
from typing import Any, Dict, Optional

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


class ChronosOverlayBridge:
    """
    Writes high-frequency temporal telemetry packets (where Time is the sole unit)
    into `.elora/overlay_status.json` and `VirtioShmRing("overlay.ring")` if active.
    """

    STATE_TAU_MAP = {
        "CRYPTOBIOSIS": 0.050,
        "ALIVE": 0.200,
        "AWAKE": 0.380,
        "ALERT": 1.800,
        "DIGESTING": 1.900,
        "ARMED": 4.200,
    }

    def __init__(self, state_dir: str | pathlib.Path = ".elora", ring_path: str | None = None):
        self.state_dir = pathlib.Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.state_dir / "overlay_status.json"
        self.ring_path = ring_path or str(self.state_dir / "shm" / "overlay.ring")
        self.shm_ring = self._try_attach_shm(self.ring_path)

    @staticmethod
    def _try_attach_shm(path: str) -> Optional[Any]:
        try:
            from elora.core.virtio_shm import VirtioShmRing
            return VirtioShmRing(path, slots=64, create=True)
        except Exception:
            return None

    def close(self) -> None:
        if self.shm_ring is not None:
            try:
                self.shm_ring.close()
            except Exception:
                pass
            self.shm_ring = None

    def publish_temporal_frame(
        self,
        metabolism_state: str = "AWAKE",
        decay_remaining_s: float = 45.0,
        last_capability: str = "perception.snapshot",
        last_dt_ms: float = 1.82,
        akashic_seq: int = 39,
        akashic_head: str = "0" * 64,
        arise_overdrive: bool = False,
    ) -> Dict[str, Any]:
        now_tau = round(time.time(), 4)
        tau_budget = self.STATE_TAU_MAP.get(metabolism_state, 0.380)
        packet = {
            "schema": "elora.chronos.v7.2",
            "tau_epoch_s": now_tau,
            "metabolism_state": metabolism_state,
            "metabolism_tau_s": tau_budget,
            "decay_remaining_s": round(decay_remaining_s, 3),
            "last_capability": last_capability,
            "last_execution_dt_ms": round(last_dt_ms, 3),
            "akashic_seq": akashic_seq,
            "akashic_head": akashic_head,
            "arise_overdrive": arise_overdrive,
            "iso_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        encoded = json.dumps(packet, indent=2)
        self.status_path.write_text(encoded, encoding="utf-8")

        if self.shm_ring is not None:
            try:
                self.shm_ring.push(encoded.encode("utf-8")[:1024])
            except Exception:
                pass
        return packet
