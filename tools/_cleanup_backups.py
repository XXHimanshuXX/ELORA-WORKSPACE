"""Remove numbered backup files only (not legitimate *_*.py modules)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = [
    os.path.join(ROOT, "elora", "core", "absorption_gate_8.py"),
    os.path.join(ROOT, "elora", "core", "absorption_gate_9.py"),
    os.path.join(ROOT, "elora", "core", "promotion_8.py"),
    os.path.join(ROOT, "tools", "tests", "test_boot_4.py"),
    os.path.join(ROOT, "tools", "tests", "test_broker_4.py"),
    os.path.join(ROOT, "tools", "tests", "test_metabolism_4.py"),
]
for path in TARGETS:
    if os.path.exists(path):
        os.remove(path)
        print("deleted", path)
    else:
        print("absent ", path)
