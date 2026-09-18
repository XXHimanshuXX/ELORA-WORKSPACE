"""
test_virtio_shm.py — Inspection rung for VirtIO shared-memory SPSC ring buffer.

Pass criteria:
  - Producer/consumer integrity under concurrent load.
  - Checksum validation: slot checksum failure detected when a byte is flipped.
  - Header checksum validation: corruption detected when a header byte is flipped.
  - Ring buffer capacity boundary enforcement (BufferError on ring full).
"""

import threading
import time
import pytest
from elora.core.virtio_shm import VirtioShmRing, MAGIC, HEADER_SIZE, SLOT_SIZE


class TestSpscRing:

    def test_header_and_basic_roundtrip(self, tmp_path):
        ring_file = str(tmp_path / "ivshmem.ring")
        ring = VirtioShmRing(ring_file, slots=8)

        assert ring.verify_header() is True
        assert bytes(ring.buf[:8]) == MAGIC

        # Push single event
        ev = ring.push(b"hello_shm")
        assert ev.payload == b"hello_shm"
        assert ev.epoch == 1

        # Pop event
        popped = ring.pop()
        assert popped is not None
        assert popped.payload == b"hello_shm"
        assert popped.epoch == 1

        # Empty ring returns None
        assert ring.pop() is None
        ring.close()

    def test_checksum_detects_slot_tamper(self, tmp_path):
        """Proof that flipping a payload byte causes slot checksum failure."""
        ring_file = str(tmp_path / "tamper.ring")
        ring = VirtioShmRing(ring_file, slots=8)

        ev = ring.push(b"authentic_payload")
        assert ring.verify_header() is True

        # Directly corrupt the payload byte in shared memory
        # Payload starts at off + 4
        corrupt_offset = ev.offset + 4
        ring.buf[corrupt_offset] ^= 0xFF

        # Popping corrupted slot must raise checksum failure
        with pytest.raises(RuntimeError) as exc:
            ring.pop()
        assert "slot checksum failed" in str(exc.value)
        ring.close()

    def test_header_checksum_detects_tamper(self, tmp_path):
        """Proof that corrupting the ring header fails verify_header()."""
        ring_file = str(tmp_path / "header_tamper.ring")
        ring = VirtioShmRing(ring_file, slots=8)

        ring.push(b"data")
        assert ring.verify_header() is True

        # Corrupt write index or magic in header
        ring.buf[0] = ord(b"X")
        assert ring.verify_header() is False

        with pytest.raises(RuntimeError) as exc:
            ring.pop()
        assert "ivshmem header checksum failed" in str(exc.value)
        ring.close()

    def test_ring_full_raises_buffer_error(self, tmp_path):
        ring_file = str(tmp_path / "full.ring")
        ring = VirtioShmRing(ring_file, slots=3)

        ring.push(b"item_1")
        ring.push(b"item_2")
        ring.push(b"item_3")

        # Exceed capacity without consumer popping
        with pytest.raises(BufferError) as exc:
            ring.push(b"item_4")
        assert "ring full" in str(exc.value)
        ring.close()

    def test_concurrent_producer_consumer_load(self, tmp_path):
        """Producer/consumer integrity under concurrent multi-threaded load."""
        ring_file = str(tmp_path / "concurrent.ring")
        slots = 32
        n_messages = 64

        producer_ring = VirtioShmRing(ring_file, slots=slots)
        consumer_ring = VirtioShmRing(ring_file, slots=slots, create=False)

        received = []
        errors = []

        def consumer_worker():
            popped_count = 0
            deadline = time.time() + 5.0
            while popped_count < n_messages and time.time() < deadline:
                try:
                    ev = consumer_ring.pop()
                    if ev is not None:
                        received.append(ev.payload)
                        popped_count += 1
                    else:
                        time.sleep(0.001)
                except Exception as e:
                    errors.append(e)
                    break

        consumer_thread = threading.Thread(target=consumer_worker, daemon=True)
        consumer_thread.start()

        for i in range(n_messages):
            msg = f"msg_{i:04d}".encode("utf-8")
            pushed = False
            while not pushed:
                try:
                    producer_ring.push(msg)
                    pushed = True
                except BufferError:
                    time.sleep(0.002)

        consumer_thread.join(timeout=6.0)
        producer_ring.close()
        consumer_ring.close()

        assert not errors
        assert len(received) == n_messages
        for i, payload in enumerate(received):
            assert payload == f"msg_{i:04d}".encode("utf-8")
