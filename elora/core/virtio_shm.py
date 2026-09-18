"""
virtio_shm.py — lock-free SPSC ring over a shared mapping.

Replaces HTTP + inbox file-poll as the fast path. On bare metal / QEMU
this mapping is an IVSHMEM BAR. On a laptop it is an mmap'd file that
has the same layout, so the protocol is testable without a hypervisor.

Header (64 bytes):
    magic[8] = b'ELORAIV1'
    write_idx u64
    read_idx  u64
    epoch     u64   # monotonic, never reused
    checksum  u64   # sha256(header[:-8])[:8]
    reserved

Slots follow. Each slot: len u32 + payload + checksum u32.
Tamper of a slot fails the checksum; Akashic logs offset + digest.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import struct
import time
from dataclasses import dataclass

MAGIC = b"ELORAIV1"
HEADER_SIZE = 64
SLOT_SIZE = 4096
DEFAULT_SLOTS = 64


def _u64(buf, off):
    return struct.unpack_from("<Q", buf, off)[0]


def _put_u64(buf, off, val):
    struct.pack_into("<Q", buf, off, val)


def _header_checksum(buf) -> int:
    return int.from_bytes(hashlib.sha256(bytes(buf[:56])).digest()[:8], "little")


@dataclass
class RingEvent:
    epoch: int
    payload: bytes
    offset: int
    checksum: str


class VirtioShmRing:
    def __init__(self, path: str, slots: int = DEFAULT_SLOTS, create: bool = True):
        self.path = path
        self.slots = slots
        size = HEADER_SIZE + slots * SLOT_SIZE
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        if create and (not os.path.exists(path) or os.path.getsize(path) < size):
            with open(path, "wb") as f:
                f.write(b"\x00" * size)
        self._fh = open(path, "r+b")
        self.buf = mmap.mmap(self._fh.fileno(), size)
        if bytes(self.buf[0:8]) != MAGIC:
            self.buf[0:8] = MAGIC
            _put_u64(self.buf, 8, 0)
            _put_u64(self.buf, 16, 0)
            _put_u64(self.buf, 24, 0)
            _put_u64(self.buf, 56, _header_checksum(self.buf))

    def close(self):
        try:
            self.buf.flush()
            self.buf.close()
            self._fh.close()
        except Exception:
            pass

    def _commit_header(self):
        _put_u64(self.buf, 56, _header_checksum(self.buf))

    def verify_header(self) -> bool:
        return _header_checksum(self.buf) == _u64(self.buf, 56)

    def push(self, payload: bytes) -> RingEvent:
        if len(payload) > SLOT_SIZE - 8:
            raise ValueError("payload exceeds slot")
        w = _u64(self.buf, 8)
        r = _u64(self.buf, 16)
        if (w - r) >= self.slots:
            raise BufferError("ring full")
        slot = w % self.slots
        off = HEADER_SIZE + slot * SLOT_SIZE
        digest = hashlib.sha256(payload).digest()[:4]
        struct.pack_into("<I", self.buf, off, len(payload))
        self.buf[off + 4: off + 4 + len(payload)] = payload
        self.buf[off + 4 + len(payload): off + 8 + len(payload)] = digest
        epoch = _u64(self.buf, 24) + 1
        _put_u64(self.buf, 24, epoch)
        _put_u64(self.buf, 8, w + 1)
        self._commit_header()
        return RingEvent(epoch=epoch, payload=payload, offset=off,
                         checksum=digest.hex())

    def pop(self) -> RingEvent | None:
        if not self.verify_header():
            raise RuntimeError("ivshmem header checksum failed")
        w = _u64(self.buf, 8)
        r = _u64(self.buf, 16)
        if r >= w:
            return None
        slot = r % self.slots
        off = HEADER_SIZE + slot * SLOT_SIZE
        (n,) = struct.unpack_from("<I", self.buf, off)
        payload = bytes(self.buf[off + 4: off + 4 + n])
        stored = bytes(self.buf[off + 4 + n: off + 8 + n])
        digest = hashlib.sha256(payload).digest()[:4]
        if stored != digest:
            raise RuntimeError(f"slot checksum failed at phys_off={off}")
        _put_u64(self.buf, 16, r + 1)
        self._commit_header()
        return RingEvent(epoch=_u64(self.buf, 24), payload=payload,
                         offset=off, checksum=digest.hex())


def default_ring(state_dir: str = ".elora") -> VirtioShmRing:
    return VirtioShmRing(os.path.join(state_dir, "ivshmem.ring"))
