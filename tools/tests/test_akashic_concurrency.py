from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import threading
import time

from elora.organs.akashic import AkashicLedger


def test_concurrent_ledger_writers_keep_one_hash_chain(tmp_path):
    db_path = str(tmp_path / "akashic.db")
    workers = 12
    events_per_worker = 8
    ledgers = [AkashicLedger(db_path) for _ in range(4)]
    start = threading.Barrier(workers)

    def append_events(worker):
        start.wait(timeout=5)
        ledger = ledgers[worker % len(ledgers)]
        for offset in range(events_per_worker):
            ledger.append(
                organ="test",
                kind="concurrent_append",
                message=f"worker-{worker}-event-{offset}",
                payload={"worker": worker, "offset": offset},
            )

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(append_events, range(workers)))

        verifier = AkashicLedger(db_path)
        try:
            assert verifier.verify() == (True, None)
            assert len(verifier.events) == workers * events_per_worker
        finally:
            verifier.conn.close()
    finally:
        for ledger in ledgers:
            ledger.conn.close()


def test_separate_processes_serialize_ledger_appends(tmp_path):
    db_path = str(tmp_path / "multi-process.db")
    gate_dir = tmp_path / "process-gate"
    gate_dir.mkdir()
    worker_count = 4
    events_per_worker = 32
    ready_paths = [gate_dir / f"ready-{worker}" for worker in range(worker_count)]
    release_path = gate_dir / "release"
    child_code = """
import sys
import time
from pathlib import Path
from elora.organs.akashic import AkashicLedger

db_path, gate_dir, worker, count = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
(ledger := AkashicLedger(db_path))
(gate_dir / f'ready-{worker}').write_text('ready', encoding='utf-8')
release = gate_dir / 'release'
deadline = time.monotonic() + 10
while not release.exists():
    if time.monotonic() >= deadline:
        raise SystemExit('release gate timed out')
    time.sleep(0.005)
for offset in range(count):
    ledger.append('test', 'process_append', f'worker-{worker}-event-{offset}', {'worker': worker, 'offset': offset})
ledger.conn.close()
"""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    processes = []
    try:
        bootstrap = AkashicLedger(db_path)
        bootstrap.conn.close()
        for worker in range(worker_count):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", child_code, db_path, str(gate_dir), str(worker), str(events_per_worker)],
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            ))

        deadline = time.monotonic() + 10
        while not all(path.exists() for path in ready_paths):
            if any(process.poll() is not None for process in processes):
                raise AssertionError("a ledger writer exited before reaching the release gate")
            if time.monotonic() >= deadline:
                raise AssertionError("ledger writers did not reach the release gate")
            time.sleep(0.005)
        release_path.write_text("go", encoding="utf-8")

        overall_deadline = time.monotonic() + 30
        for process in processes:
            timeout = max(0.1, overall_deadline - time.monotonic())
            stdout, stderr = process.communicate(timeout=timeout)
            assert process.returncode == 0, f"writer failed: {stdout}\n{stderr}"

        verifier = AkashicLedger(db_path)
        try:
            assert verifier.verify() == (True, None)
            assert len(verifier.events) == worker_count * events_per_worker
        finally:
            verifier.conn.close()
    finally:
        release_path.touch(exist_ok=True)
        for process in processes:
            if process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
        for process in processes:
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
