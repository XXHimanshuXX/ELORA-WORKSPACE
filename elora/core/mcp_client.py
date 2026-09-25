"""
mcp_client.py — the real Model Context Protocol, over stdio.

brain.py lets the model ASK for a tool (`<mcp_call server="omniroute" ...>`).
This module is the other half: it actually speaks to the server. JSON-RPC 2.0,
one object per line, in a child process we own.

Why hand-rolled instead of the official SDK: the daemon's dependency surface
stays flat, and every failure mode here is one we must report honestly anyway —
a server that will not launch, a tool that reports `isError` inside a normal
result envelope, a stdout that closes mid-call. Those are DATA, not exceptions
to swallow. Nothing here invents a result, and nothing here waits forever.

Two threads guard the child. One drains stderr so a chatty server cannot fill
the pipe and deadlock us, and so its last words can be quoted in the error.
One parses stdout and hands each response to the caller that is waiting on
that id — a response nobody is waiting for is recorded, never delivered.

    with McpStdioServer(DEFAULT_SERVERS["omniroute"], timeout_s=20) as mcp:
        for tool in mcp.list_tools():
            ...

Or one-shot: `describe(spec)`, `list_tools(spec)`, `call_tool(spec, name, args)`.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import threading
import weakref
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# Bump this constant when a newer revision is verified against the servers we
# actually run. We do not refuse a server that answers with a different
# version: initialize / tools list / tools call are stable across revisions,
# so the reported version is recorded and surfaced, not guessed at.
PROTOCOL_VERSION = "2024-11-05"

CLIENT_NAME = "elora"
CLIENT_VERSION = "7.0"
CLIENT_INFO = {"name": CLIENT_NAME, "version": CLIENT_VERSION}
CLIENT_CAPABILITIES: dict[str, Any] = {"roots": {"listChanged": False}}

DEFAULT_TIMEOUT_S = 30.0

_TERM_GRACE_S = 2.0
_KILL_GRACE_S = 3.0
_STDERR_MAX_LINES = 200        # bounded: a noisy server must not eat our RAM
_STDERR_TAIL_CHARS = 4000
_UNMATCHED_KEEP = 16
_MAX_TOOL_PAGES = 64


# ----------------------------------------------------------------------
# Failures — each one carries the evidence, never a summary of it
# ----------------------------------------------------------------------

class McpError(Exception):
    """Base for every failure this module can report."""


class McpUnknownServer(McpError):
    def __init__(self, name: str, known: Iterable[str]):
        self.name = name
        self.known = sorted(known)
        super().__init__(
            f"unknown MCP server {name!r}; known: {', '.join(self.known) or '(none)'}")


class McpLaunchFailed(McpError):
    """Popen itself refused. The command that failed is quoted verbatim."""

    def __init__(self, argv: Sequence[str], cause: BaseException):
        self.argv = list(argv)
        self.cause = cause
        super().__init__(
            f"cannot launch MCP server: {' '.join(argv)} -> "
            f"{type(cause).__name__}: {cause}")


class McpServerDied(McpError):
    """stdin broke or stdout closed while we were talking to the server."""

    def __init__(self, server: str, detail: str, stderr_tail: str = "",
                 returncode: int | None = None):
        self.server = server
        self.detail = detail
        self.stderr_tail = stderr_tail
        self.returncode = returncode
        tail = stderr_tail.strip()
        super().__init__(
            f"{server}: server died — {detail} (returncode={returncode})"
            + (f" | stderr tail: {tail[-500:]}" if tail else ""))


class McpTimeout(McpError):
    """A request got no matching response in time. Never a fake success."""

    def __init__(self, server: str, method: str, request_id: int,
                 timeout_s: float, stderr_tail: str = ""):
        self.server = server
        self.method = method
        self.request_id = request_id
        self.timeout_s = timeout_s
        self.stderr_tail = stderr_tail
        tail = stderr_tail.strip()
        super().__init__(
            f"{server}: no reply to {method!r} (id={request_id}) within "
            f"{timeout_s}s"
            + (f" | stderr tail: {tail[-500:]}" if tail else ""))


class McpProtocolError(McpError):
    """The server answered, but not in a shape the protocol allows."""


class McpRpcError(McpError):
    """A JSON-RPC `error` object, carried whole so callers see code + data."""

    def __init__(self, server: str, method: str, code: Any, message: str,
                 data: Any = None):
        self.server = server
        self.method = method
        self.code = code
        self.message = message
        self.data = data
        detail = f" data={data!r}" if data is not None else ""
        super().__init__(f"{server}: {method} failed: [{code}] {message}{detail}")


# ----------------------------------------------------------------------
# Servers
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class McpServerSpec:
    """One server, exactly as it would be typed into a client config file."""
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "env", dict(self.env))

    def argv(self) -> list[str]:
        """The literal argv for this server. No shell, ever."""
        return [self.command, *self.args]


_SECRETS_DIR = os.path.abspath(os.path.join(".elora", "secrets"))


def _read_secret(name: str) -> str:
    """Read one secret file. Missing is normal here and is not an error."""
    try:
        with open(os.path.join(_SECRETS_DIR, name), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _omniroute_env() -> dict[str, str]:
    """
    The environment OmniRoute's MCP server needs in order to authenticate.

    Without this the server starts, completes the handshake, and answers
    `tools/list` perfectly — it simply fails every call that touches the API,
    and reports each failure inside a successful envelope. `uptime: "unknown"`,
    an empty `circuitBreakers`, and a `degraded` array full of 401s is what a
    fully "working" tool call looked like before this existed.

    Names verified against OmniRoute's own provider source rather than guessed.

    Secrets are read here and handed to the child process; they are never
    logged, returned, or embedded in any message this module builds.
    """
    env: dict[str, str] = {}
    api_key = _read_secret("omniroute_api_key")
    if api_key:
        env["OMNIROUTE_API_KEY"] = api_key
    management_key = _read_secret("omniroute_management_api_key")
    if management_key:
        env["OMNIROUTE_MANAGEMENT_API_KEY"] = management_key
    return env


DEFAULT_SERVERS: dict[str, McpServerSpec] = {
    # Real, live local gateway — 110 tools at last probe.
    "omniroute": McpServerSpec(
        name="omniroute",
        command="node",
        args=["C:/Users/HARSH/AppData/Roaming/npm/node_modules/omniroute/bin/mcp-server.mjs"],
        env=_omniroute_env(),
    ),
    "filesystem": McpServerSpec(
        name="filesystem",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "D:/Coding/ELORA Workspace"],
    ),
}


def resolve_spec(spec: McpServerSpec | str) -> McpServerSpec:
    """Accept a spec or a bare name — brain.py emits server names as strings."""
    if isinstance(spec, McpServerSpec):
        return spec
    try:
        return DEFAULT_SERVERS[spec]
    except KeyError:
        raise McpUnknownServer(spec, DEFAULT_SERVERS) from None


def _spawn_flags() -> int:
    """CREATE_NO_WINDOW where the platform has it — a resident OS must not flash consoles."""
    if os.name == "nt":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _launch_argv(spec: McpServerSpec) -> list[str]:
    """
    argv as Popen receives it, with one Windows reality handled.

    CreateProcess cannot execute a .cmd/.bat shim, and `npx`/`npm` exist only
    as shims (verified: C:\\Program Files\\nodejs\\npx.cmd). Shelling out is not
    an option, so the shim is invoked through cmd.exe with the same explicit
    argv — an argv list, never an interpolated shell string.
    """
    if os.name == "nt":
        resolved = shutil.which(spec.command)
        if resolved and resolved.lower().endswith((".cmd", ".bat")):
            comspec = os.environ.get("COMSPEC") or "cmd.exe"
            return [comspec, "/c", resolved, *spec.args]
    return spec.argv()


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class McpToolResult:
    """
    A tool call, with protocol success and tool failure kept apart.

    `protocol_ok` means "the server answered us in valid JSON-RPC". `is_error`
    means the tool itself reported failure (`result.isError == true`) — which
    MCP delivers inside a perfectly successful envelope. Collapsing the two
    into one boolean is how agents learn to lie to themselves.
    """
    server: str
    tool: str
    protocol_ok: bool
    is_error: bool
    content: list[dict]
    structured_content: Any = None
    raw: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.protocol_ok and not self.is_error

    @property
    def text(self) -> str:
        """Concatenated text blocks — the reason most callers called at all."""
        return "\n".join(
            block.get("text", "") for block in self.content
            if isinstance(block, dict) and block.get("type") == "text")


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    message: dict | None = None


# ----------------------------------------------------------------------
# The client
# ----------------------------------------------------------------------

_LIVE: "weakref.WeakSet[McpStdioServer]" = weakref.WeakSet()
_LIVE_LOCK = threading.Lock()


@atexit.register
def _reap_live_servers() -> None:
    """Last resort: a client dropped without close() must not outlive us."""
    with _LIVE_LOCK:
        live = list(_LIVE)
    for client in live:
        try:
            client.close()
        except Exception:
            pass


class McpStdioServer:
    """One live MCP server process, speaking newline-delimited JSON-RPC 2.0."""

    def __init__(self, spec: McpServerSpec | str,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self.spec = resolve_spec(spec)
        self.timeout_s = float(timeout_s)
        self.server_info: dict = {}
        self.protocol_version: str = ""
        self.capabilities: dict = {}

        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._pending: dict[int, _Pending] = {}
        self._lock = threading.Lock()          # ids, pending, death
        self._write_lock = threading.Lock()    # one writer on stdin
        self._death: str | None = None
        self._unmatched: deque[dict] = deque(maxlen=_UNMATCHED_KEEP)
        self._bad_lines: deque[str] = deque(maxlen=_UNMATCHED_KEEP)
        self._stderr_lines: deque[str] = deque(maxlen=_STDERR_MAX_LINES)
        self._stderr_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    # -- lifecycle ----------------------------------------------------

    def start(self) -> dict:
        """Launch, initialize, send `notifications/initialized`. Returns serverInfo."""
        if self._proc is not None:
            raise McpProtocolError(f"{self.spec.name}: already started")
        argv = _launch_argv(self.spec)
        env = dict(os.environ)
        env.update(self.spec.env)
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.spec.cwd,
                env=env,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_spawn_flags(),
                start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            raise McpLaunchFailed(argv, exc) from exc
        with _LIVE_LOCK:
            _LIVE.add(self)
        self._spawn_thread(self._stderr_loop, "elora-mcp-stderr")
        self._spawn_thread(self._read_loop, "elora-mcp-stdout")
        try:
            self._initialize()
        except BaseException:
            self.close()          # an exception mid-handshake must not leak a process
            raise
        return self.server_info

    def _initialize(self) -> None:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": dict(CLIENT_CAPABILITIES),
            "clientInfo": dict(CLIENT_INFO),
        })
        self.server_info = result.get("serverInfo") or {}
        self.protocol_version = str(result.get("protocolVersion") or "")
        self.capabilities = result.get("capabilities") or {}
        self._notify("notifications/initialized")

    def close(self) -> None:
        """
        Teardown, idempotent. EOF on stdin, terminate, kill on timeout, wait().

        No `shutdown` request is sent: newer revisions dropped it, and an
        unknown-method error on the way out would just be noise. Closing
        stdin is the transport's own shutdown signal for stdio.
        """
        proc, self._proc = self._proc, None
        if proc is None:
            return
        with _LIVE_LOCK:
            _LIVE.discard(self)
        self._mark_dead("client closed the transport")
        self._close_stdin(proc)
        self._await_exit(proc)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
        for thread in self._threads:
            thread.join(timeout=_KILL_GRACE_S)

    shutdown = close   # MCP vocabulary for the same teardown

    def _close_stdin(self, proc: subprocess.Popen) -> None:
        if proc.stdin is None or proc.stdin.closed:
            return
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _await_exit(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=_TERM_GRACE_S)
            except subprocess.TimeoutExpired:
                self._kill_tree(proc)
                try:
                    proc.wait(timeout=_KILL_GRACE_S)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    try:
                        proc.wait(timeout=_KILL_GRACE_S)
                    except subprocess.TimeoutExpired:
                        pass
        try:
            proc.wait(timeout=_KILL_GRACE_S)   # always wait(): no zombies
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _kill_tree(self, proc: subprocess.Popen) -> None:
        """
        Kill what the direct child spawned too. OmniRoute's mcp-server.mjs
        launches the actual server as a grandchild, so killing only the wrapper
        would leave a node process holding our stdout pipe open forever.
        """
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    shell=False, capture_output=True, timeout=_KILL_GRACE_S,
                    creationflags=_spawn_flags(),
                )
            else:
                os.killpg(os.getpgid(proc.pid), 9)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    def __enter__(self) -> "McpStdioServer":
        if self._proc is None:
            self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()          # fires on the exception path too
        return False

    def _spawn_thread(self, target, name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    # -- MCP surface --------------------------------------------------

    def list_tools(self) -> list[dict]:
        """Every tool, following `nextCursor` until the server stops offering one."""
        tools: list[dict] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_TOOL_PAGES):
            result = self._request("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if page is None:
                page = []
            if not isinstance(page, list):
                raise McpProtocolError(
                    f"{self.spec.name}: tools/list returned {type(page).__name__}, not a list")
            tools.extend(page)
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
            if cursor in seen:
                raise McpProtocolError(
                    f"{self.spec.name}: tools/list repeated cursor {cursor!r} — refusing to loop")
            seen.add(cursor)
        raise McpProtocolError(
            f"{self.spec.name}: tools/list exceeded {_MAX_TOOL_PAGES} pages")

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> McpToolResult:
        """Call one tool. Protocol failure raises; tool failure is returned."""
        result = self._request("tools/call", {"name": name, "arguments": dict(arguments or {})})
        content = result.get("content")
        if not isinstance(content, list):
            content = []
        return McpToolResult(
            server=self.spec.name,
            tool=name,
            protocol_ok=True,
            is_error=bool(result.get("isError")),
            content=content,
            structured_content=result.get("structuredContent"),
            raw=result,
        )

    # -- transport ----------------------------------------------------

    def _request(self, method: str, params: dict | None = None) -> dict:
        if self._death is not None:
            raise self._died()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            slot = _Pending()
            self._pending[request_id] = slot
        try:
            self._write({"jsonrpc": "2.0", "id": request_id,
                         "method": method, "params": params or {}})
        except McpError:
            with self._lock:
                self._pending.pop(request_id, None)
            raise
        if not slot.event.wait(self.timeout_s):
            with self._lock:
                self._pending.pop(request_id, None)
            raise McpTimeout(self.spec.name, method, request_id,
                             self.timeout_s, self.stderr_tail())
        if slot.message is None:
            raise self._died()
        message = slot.message
        error = message.get("error")
        if error is not None:
            raise McpRpcError(self.spec.name, method,
                              (error or {}).get("code"), (error or {}).get("message", ""),
                              (error or {}).get("data"))
        result = message.get("result")
        return result if result is not None else {}

    def _notify(self, method: str, params: dict | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _write(self, message: dict) -> None:
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._write_lock:
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise self._died()
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._mark_dead(f"stdin write failed: {type(exc).__name__}: {exc}")
                raise self._died() from exc

    def _read_loop(self) -> None:
        """Parse stdout lines. Route by id; never deliver what nobody asked for."""
        proc = self._proc
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self._bad_lines.append(line)     # stray output, not a reply
                    continue
                if not isinstance(message, dict):
                    self._bad_lines.append(line)
                    continue
                if "method" in message:
                    self._handle_server_message(message)
                    continue
                request_id = message.get("id")
                with self._lock:
                    slot = self._pending.pop(request_id, None)
                if slot is None:
                    # A response to a request nobody is waiting on (timed out,
                    # or never ours). Recorded verbatim — never delivered into
                    # another caller's slot.
                    self._unmatched.append(message)
                    continue
                slot.message = message
                slot.event.set()
        except (OSError, ValueError):
            pass
        finally:
            returncode = proc.poll() if proc is not None else None
            self._mark_dead(f"stdout closed unexpectedly (returncode={returncode})")

    def _handle_server_message(self, message: dict) -> None:
        """Servers may ask us things. Answer the two we advertise, refuse the rest."""
        request_id = message.get("id")
        if request_id is None:
            return                        # notification (list_changed, log) — noted, not acted on
        method = message.get("method")
        if method == "roots/list":
            result: dict = {"roots": []}
        elif method == "ping":
            result = {}
        else:
            self._write({"jsonrpc": "2.0", "id": request_id,
                         "error": {"code": -32601, "message": f"method not found: {method}"}})
            return
        self._write({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _mark_dead(self, detail: str) -> None:
        with self._lock:
            if self._death is None:
                self._death = detail
            waiting = list(self._pending.values())
            self._pending.clear()
        for slot in waiting:
            slot.event.set()

    def _died(self) -> McpServerDied:
        proc = self._proc
        returncode = proc.poll() if proc is not None else None
        return McpServerDied(self.spec.name, self._death or "transport is closed",
                             self.stderr_tail(), returncode)

    # -- evidence -----------------------------------------------------

    def stderr_tail(self, limit: int = _STDERR_TAIL_CHARS) -> str:
        """The server's own last words. This is what goes into error messages."""
        with self._stderr_lock:
            text = "\n".join(self._stderr_lines)
        return text[-limit:]

    @property
    def unmatched_responses(self) -> list[dict]:
        """Replies that matched no pending id. Kept so a desync is visible."""
        return list(self._unmatched)

    @property
    def bad_lines(self) -> list[str]:
        """Non-JSON lines seen on stdout — a server leaking logs into the protocol."""
        return list(self._bad_lines)

    def _stderr_loop(self) -> None:
        proc = self._proc
        try:
            for line in proc.stderr:
                with self._stderr_lock:
                    self._stderr_lines.append(line.rstrip("\r\n"))
        except (OSError, ValueError):
            pass


# ----------------------------------------------------------------------
# One-shot convenience — full lifecycle, no process left behind
# ----------------------------------------------------------------------

def list_tools(spec: McpServerSpec | str,
               timeout: float = DEFAULT_TIMEOUT_S) -> list[dict]:
    """Start, list, stop. For callers that just need the catalogue."""
    with McpStdioServer(spec, timeout_s=timeout) as client:
        return client.list_tools()


def call_tool(spec: McpServerSpec | str, tool_name: str,
              arguments: Mapping[str, Any] | None = None,
              timeout: float = DEFAULT_TIMEOUT_S) -> McpToolResult:
    """Start, call once, stop. Raises on transport failure, returns tool failure."""
    with McpStdioServer(spec, timeout_s=timeout) as client:
        return client.call_tool(tool_name, arguments)


def describe(spec: McpServerSpec | str,
             timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    """
    One JSON-serializable snapshot for a dashboard.

    `reachable=False` always carries the real error string — a dashboard that
    shows a green light for a server that never answered is worse than one
    that shows nothing at all.
    """
    server_name = spec if isinstance(spec, str) else spec.name
    try:
        with McpStdioServer(spec, timeout_s=timeout) as client:
            tools = client.list_tools()
            version = client.protocol_version
            info = client.server_info
    except McpError as exc:
        return {
            "server": server_name,
            "reachable": False,
            "tool_count": 0,
            "tools": [],
            "protocol_version": None,
            "server_info": {},
            "error": str(exc),
        }
    return {
        "server": server_name,
        "reachable": True,
        "tool_count": len(tools),
        "tools": [t.get("name") for t in tools if isinstance(t, dict)],
        "protocol_version": version or None,
        "server_info": info,
        "error": None,
    }
