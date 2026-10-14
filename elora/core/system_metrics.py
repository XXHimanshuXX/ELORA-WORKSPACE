"""Small, measured host metrics shared by the daemon and dashboard."""

from __future__ import annotations


def memory_snapshot() -> dict[str, object]:
    """Return current host memory availability, or explicit unknown values."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        total_bytes = int(vm.total)
        available_bytes = int(vm.available)
        if total_bytes <= 0 or available_bytes < 0:
            raise ValueError("invalid virtual-memory counters")
    except Exception as exc:  # a missing/broken provider is an unknown, not a guess
        return {
            "ram_metric_available": False,
            "ram_headroom": None,
            "ram_available_mb": None,
            "ram_total_mb": None,
            "ram_metric_error": type(exc).__name__,
        }

    mib = 1024 * 1024
    return {
        "ram_metric_available": True,
        "ram_headroom": round(available_bytes / total_bytes, 3),
        "ram_available_mb": round(available_bytes / mib, 1),
        "ram_total_mb": round(total_bytes / mib, 1),
    }
