"""
test_armored.py — the armored subprocess cage.

Every test plants a target that tries to escape, and asserts it cannot.
Targets are written as inline python -c commands so the tests read
like an attacker's shopping list.
"""
import os
try:
    import resource  # noqa: F401  # POSIX-only; collection must not die on Windows
except ImportError:
    resource = None
import subprocess
import pytest

from elora.core.armored_subprocess import (
    armored_run, Budget, BudgetExceeded)


class TestCpuLimit:
    def test_runaway_loop_dies(self):
        result = armored_run(
            ["python", "-c", "while True: pass"],
            budget=Budget(cpu_seconds=2, ram_mb=256, wall_seconds=30),
        )
        assert result.killed_by == "cpu_limit"
        assert result.duration_s < 30      # didn't eat the wall clock
        assert result.returncode != 0

    def test_fast_task_survives(self):
        result = armored_run(
            ["python", "-c", "print('hello')"],
            budget=Budget(cpu_seconds=10, ram_mb=256, wall_seconds=30),
        )
        assert result.returncode == 0
        assert "hello" in result.stdout


class TestRamLimit:
    def test_allocation_beyond_cage_dies(self):
        result = armored_run(
            ["python", "-c", "x = bytearray(999 * 1024 * 1024)"],
            budget=Budget(cpu_seconds=10, ram_mb=256, wall_seconds=30),
        )
        assert result.returncode != 0
        assert result.killed_by != "wall_limit"  # OOM, not timeout

    def test_allocation_within_cage_survives(self):
        result = armored_run(
            ["python", "-c", "x = bytearray(100 * 1024 * 1024)"],
            budget=Budget(cpu_seconds=10, ram_mb=512, wall_seconds=30),
        )
        assert result.returncode == 0

    def test_parent_rss_unchanged(self):
        import psutil
        before = psutil.Process().memory_info().rss
        armored_run(
            ["python", "-c", "x = bytearray(200 * 1024 * 1024); import time; time.sleep(1)"],
            budget=Budget(cpu_seconds=5, ram_mb=512, wall_seconds=30),
        )
        after = psutil.Process().memory_info().rss
        assert after - before < 50 * 1024 * 1024  # parent didn't balloon


class TestWallClock:
    def test_sleeper_terminated(self):
        result = armored_run(
            ["python", "-c", "import time; time.sleep(9999)"],
            budget=Budget(cpu_seconds=60, ram_mb=256, wall_seconds=3),
        )
        assert result.timed_out is True
        assert result.killed_by == "wall_limit"
        assert result.duration_s < 10           # 3s budget + kill grace


class TestFileSize:
    def test_disk_flood_stopped(self):
        result = armored_run(
            ["python", "-c",
             "open('flood.bin','wb').write(b'\\0' * 100 * 1024 * 1024)"],
            budget=Budget(cpu_seconds=10, ram_mb=256, wall_seconds=30,
                          file_mb=10),
        )
        assert result.returncode != 0


class TestForkBlocked:
    def test_fork_raises(self):
        result = armored_run(
            ["python", "-c",
             "import os\n"
             "try:\n"
             "    pid = os.fork()\n"
             "    print('FORK_OK' if pid >= 0 else 'FORK_FAIL')\n"
             "except OSError:\n"
             "    print('FORK_BLOCKED')\n"],
            budget=Budget(cpu_seconds=5, ram_mb=256, wall_seconds=15),
        )
        assert "FORK_BLOCKED" in result.stdout


class TestEnvironmentScrubbed:
    def test_planted_key_absent(self):
        os.environ["FAKE_API_KEY"] = "sk-trap-0000"
        try:
            result = armored_run(
                ["python", "-c",
                 "import os; print(os.environ.get('FAKE_API_KEY', 'ABSENT'))"],
                budget=Budget(cpu_seconds=5, ram_mb=256, wall_seconds=15),
            )
            assert "sk-trap" not in result.stdout
            assert "ABSENT" in result.stdout
        finally:
            del os.environ["FAKE_API_KEY"]

    def test_elora_sandbox_flag_set(self):
        result = armored_run(
            ["python", "-c",
             "import os; print(os.environ.get('ELORA_SANDBOX', 'NO'))"],
            budget=Budget(cpu_seconds=5, ram_mb=256, wall_seconds=15),
        )
        assert "1" in result.stdout


class TestOutputIntegrity:
    def test_stdout_hashed_correctly(self):
        import hashlib
        result = armored_run(
            ["python", "-c", "print('payload')"],
            budget=Budget(cpu_seconds=5, ram_mb=256, wall_seconds=15),
        )
        expected = hashlib.sha256(b"payload\n").hexdigest()
        assert result.stdout_sha256 == expected

    def test_flood_truncated(self):
        result = armored_run(
            ["python", "-c", "print('A' * 5_000_000)"],
            budget=Budget(cpu_seconds=10, ram_mb=256, wall_seconds=30,
                          stdout_max_bytes=1000),
        )
        assert len(result.stdout) < 1200


class TestBudgetValidation:
    def test_zero_budget_is_loud(self):
        with pytest.raises(BudgetExceeded):
            armored_run(["true"], budget=Budget(cpu_seconds=0, ram_mb=256))
        with pytest.raises(BudgetExceeded):
            armored_run(["true"], budget=Budget(cpu_seconds=5, ram_mb=0))