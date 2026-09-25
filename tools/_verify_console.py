"""
_verify_console.py — static checks on the frontend bundle and the desktop shell.

The dashboard probe proves the server answers. This proves the *client* is
coherent: that the ES modules parse, that the desktop config is valid JSON, and
that the console port is the same number in all three places that state it. That
last one is not hypothetical — the window URL, the Rust constant and the server
default are three independent copies of one fact, and a drift between them would
present as "the desktop window shows server-unreachable" rather than as a typo.

Run from the repository root:
    python tools/_verify_console.py
"""

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS: list[tuple[bool, str, str]] = []


def check(name, ok, note=""):
    RESULTS.append((bool(ok), name, str(note)))


def node_check(relative):
    """`node --check` needs ESM syntax to be parsed as a module, so the file is
    copied to a .mjs sibling first rather than relying on .js detection."""
    source = os.path.join(ROOT, relative)
    temp = os.path.join(ROOT, "tools", "_res", os.path.basename(source) + ".mjs")
    os.makedirs(os.path.dirname(temp), exist_ok=True)
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(text)
    completed = subprocess.run(
        ["node", "--check", temp], capture_output=True, text=True, timeout=120)
    return completed.returncode == 0, (completed.stderr or "").strip().splitlines()[:4]


# --- the ES modules ----------------------------------------------------
for module in ("overlay/app.js", "overlay/tauri_bridge.js"):
    ok, error = node_check(module)
    check(f"{module} parses as an ES module", ok, " · ".join(error) if error else "")

# --- app.js and index.html must agree about what it imports ------------
app_js = open(os.path.join(ROOT, "overlay", "app.js"), encoding="utf-8").read()
index_html = open(os.path.join(ROOT, "overlay", "index.html"), encoding="utf-8").read()

check("index.html loads app.js as a module",
      'type="module" src="app.js"' in index_html,
      "a classic script cannot use the bridge's import statement")
check("app.js imports the bridge that exists",
      "from './tauri_bridge.js'" in app_js and "initTauriBridge" in app_js,
      "")
requested = set(re.findall(r"icon\('([a-z]+)'\)", app_js))
defined = set(re.findall(r'id="i-([a-z]+)"', index_html))
check("index.html defines every icon app.js asks for", not (requested - defined),
      f"asked for {len(requested)}, missing {sorted(requested - defined)}" if requested - defined
      else f"{len(requested)} SVG glyphs, all defined")
check("no emoji in the console sources",
      not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", app_js + index_html),
      "the brief was SVG glyphs only")

# --- the desktop shell -------------------------------------------------
config_path = os.path.join(ROOT, "src-tauri", "tauri.conf.json")
with open(config_path, encoding="utf-8") as handle:
    config = json.load(handle)
check("tauri.conf.json is valid JSON", True, "")

window_url = (config.get("tauri", {}).get("windows") or [{}])[0].get("url", "")
check("the window loads the console same-origin",
      window_url.startswith("http://127.0.0.1:"),
      f"url={window_url!r} — a tauri:// origin would trigger the preflight the server refuses")
check("withGlobalTauri is enabled",
      config.get("build", {}).get("withGlobalTauri") is True,
      "without it window.__TAURI__ never exists and the bridge is browser mode forever")

# Where withGlobalTauri belongs depends on the Tauri major version: v1 reads it
# from build, v2 moved it to app. The key being present in the wrong place fails
# silently — the config still parses, generate_context! still compiles, and the
# only symptom is a bridge that is forever in browser mode. So gate it on the
# version actually pinned in Cargo.toml rather than on what this file assumes.
cargo_toml = open(os.path.join(ROOT, "src-tauri", "Cargo.toml"), encoding="utf-8").read()
tauri_version = re.search(r'^tauri\s*=\s*\{\s*version\s*=\s*"(\d+)', cargo_toml, re.M)
major = tauri_version.group(1) if tauri_version else ""
expected_section = "build" if major == "1" else "app"
check(f"withGlobalTauri sits in the v{major or '?'} location ({expected_section})",
      config.get(expected_section, {}).get("withGlobalTauri") is True,
      f"tauri {major or '?'}.x injects window.__TAURI__ from {expected_section}.withGlobalTauri")

# --- one fact, three files --------------------------------------------
rust = open(os.path.join(ROOT, "src-tauri", "src", "main.rs"), encoding="utf-8").read()
server = open(os.path.join(ROOT, "elora", "dashboard", "server.py"), encoding="utf-8").read()

rust_port = re.search(r"CONSOLE_PORT:\s*u16\s*=\s*(\d+)", rust)
server_port = re.search(r"^DEFAULT_PORT\s*=\s*(\d+)", server, re.MULTILINE)
url_port = re.search(r"127\.0\.0\.1:(\d+)", window_url)

ports = {
    "main.rs CONSOLE_PORT": rust_port.group(1) if rust_port else None,
    "server.py DEFAULT_PORT": server_port.group(1) if server_port else None,
    "tauri.conf.json window url": url_port.group(1) if url_port else None,
}
check("the console port agrees across all three files",
      len(set(ports.values())) == 1 and None not in ports.values(),
      " · ".join(f"{k}={v}" for k, v in ports.items()))

check("the desktop shell spawns the console server",
      "-m" in rust and "elora.dashboard.server" in rust,
      "the window URL points at a server the shell must start")
check("the desktop shell starts it before the window is shown",
      rust.index("elora.dashboard.server") < rust.index("run.py"),
      "ordering in main.rs decides which process wins the port race")

# --- the honesty fix in the native readers -----------------------------
check("native readers no longer invent an ALIVE state",
      'state_name": "ALIVE"' not in rust and "unavailable(" in rust,
      "a missing state file must read as absent, never as a healthy organism")
check("native readers search for .elora instead of assuming the cwd",
      "elora_file(" in rust and "current_exe" in rust,
      "cargo tauri dev runs with cwd src-tauri/, where .elora/ does not exist")

# --- every called function must exist ----------------------------------
# `node --check` validates syntax and nothing else. It happily accepted this
# bundle while seven call sites invoked `toast(...)` against a helper actually
# named `toaster` — a ReferenceError raised inside the very handlers that report
# results to the user, which presents as buttons that do nothing. There is no
# bundler or type checker in this project, so the check lives here.
CALLABLE_GLOBALS = {
    "if", "for", "while", "switch", "catch", "return", "function", "typeof",
    "await", "async", "new", "else", "do", "delete", "void", "in", "of", "yield",
    "super", "constructor", "import", "export", "default", "this",
    "Array", "Object", "JSON", "Math", "Date", "Error", "Promise", "Number",
    "String", "Boolean", "RegExp", "Map", "Set", "WeakMap", "Symbol",
    "fetch", "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "isFinite", "isNaN", "parseInt", "parseFloat", "encodeURIComponent",
    "requestAnimationFrame", "queueMicrotask", "structuredClone",
    "document", "window", "location", "console", "Node", "URL", "URLSearchParams",
}


def strip_js_noise(source):
    """Remove comments and string bodies before scanning for call sites.

    Without this the scan reads prose: a comment saying "commands (daemon state,
    …)" looks exactly like a call to a function named `commands`, and every
    `.elora` style token written as a string reads as a call to `var`. Strings go
    before line comments because a URL contains `//` and a block comment may
    contain quotes.
    """
    source = re.sub(r"/\*[\s\S]*?\*/", " ", source)          # /* block */
    source = re.sub(r"'(?:\\.|[^'\\])*'", "''", source)        # 'single'
    source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)        # "double"
    source = re.sub(r"`(?:\\.|[^`\\])*`", "``", source)        # `template`
    source = re.sub(r"//[^\n]*", " ", source)                   # // trailing
    return source


code = strip_js_noise(app_js)
called = set(re.findall(r"(?<![\w.$])([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", code))
defined = set(re.findall(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)", code, re.M))
defined |= set(re.findall(r"^\s*(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*[:=]", code, re.M))
defined |= set(re.findall(r"^\s*class\s+([A-Za-z_$][A-Za-z0-9_$]*)", code, re.M))
for clause in re.findall(r"import\s*\{([^}]*)\}\s*from", code):
    defined |= {name.strip().split(" as ")[-1].strip() for name in clause.split(",") if name.strip()}
undefined = sorted(called - defined - CALLABLE_GLOBALS)
check("every function app.js calls is defined somewhere", not undefined,
      f"called but never defined: {undefined}" if undefined
      else f"{len(called)} call sites, all resolved")

# --- report ------------------------------------------------------------
print()
passed = sum(1 for ok, _, _ in RESULTS if ok)
for ok, name, note in RESULTS:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  —  {note}" if note else ""))
print(f"\n{passed}/{len(RESULTS)} checks passed")
sys.exit(0 if passed == len(RESULTS) else 1)
