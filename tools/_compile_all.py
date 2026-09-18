import compileall
import sys
ok = compileall.compile_dir("elora", force=True, quiet=1)
ok = compileall.compile_file("run.py", force=True, quiet=1) and ok
print("COMPILE_OK" if ok else "COMPILE_FAIL")
sys.exit(0 if ok else 1)
