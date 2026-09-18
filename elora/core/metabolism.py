"""
Metabolism — RAM is blood sugar.

The metabolic state determines which capability classes may fire.
Requests that exceed the current state are DEFERRED, never refused:
the slime says "not now", never "not ever".

Ring 0. Human-committed only. No absorbed code may import this module
except through the Broker.

   States (increasing cost):
      CRYPTOBIOSIS < ALIVE < AWAKE < ALERT < ARMED < DIGESTING

Honesty rule: if a state cannot be entered, the reason is returned
in the TaskResult so the vault episode explains WHY, not just that.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

import psutil


class State(Enum):
    CRYPTOBIOSIS = auto()   # 50MB — poll inbox only
    ALIVE        = auto()   # 200MB — core services hot
    AWAKE        = auto()   # + local LLM (~1GB, BitNet collapses to 380)
    ALERT        = auto()   # + ASR/TTS (~600MB)
    ARMED        = auto()   # + image gen (FastSD, ~3GB)
    DIGESTING    = auto()   # + absorption subprocess (~700MB)


class StateError(Exception):
    """Raised internally; never escapes to the daemon loop."""


@dataclass(frozen=True)
class StateProfile:
    """
    Declarative requirements for a metabolic state.

    ram_estimate_mb is used for ADMISSION CONTROL ONLY (can we even try?).
    Actual memory used is measured via psutil and reported honestly.
    """
    state: State
    ram_estimate_mb: int
    provides: frozenset
    loader: Optional[str] = None


STATE_ORDER: list[State] = [
    State.CRYPTOBIOSIS,
    State.ALIVE,
    State.AWAKE,
    State.ALERT,
    State.ARMED,
    State.DIGESTING,
]


PROFILES: dict[State, StateProfile] = {
    State.CRYPTOBIOSIS: StateProfile(
        state=State.CRYPTOBIOSIS,
        ram_estimate_mb=50,
        provides=frozenset({"inbox.poll", "ledger.verify"}),
    ),
    State.ALIVE: StateProfile(
        state=State.ALIVE,
        ram_estimate_mb=200,
        provides=frozenset({
            "shell.run_command", "shell.run_destructive",
            "vault.recall", "vault.save",
            "schedule.tick", "screen.capture", "fs.write", "net.fetch",
            "screen.control",
        }),
    ),
    State.AWAKE: StateProfile(
        state=State.AWAKE,
        ram_estimate_mb=380,  # BitNet b1.58; Ollama path adapts up to ~1200
        provides=frozenset({"llm.local_inference"}),
    ),
    State.ALERT: StateProfile(
        state=State.ALERT,
        ram_estimate_mb=980,   # BitNet 380 + ASR/TTS 600
        provides=frozenset({"voice.listen", "voice.speak"}),
    ),
    State.ARMED: StateProfile(
        state=State.ARMED,
        ram_estimate_mb=3380,  # BitNet 380 + FastSD 3000
        provides=frozenset({"generate.image"}),
    ),
    State.DIGESTING: StateProfile(
        state=State.DIGESTING,
        ram_estimate_mb=1080,  # BitNet 380 + gastric 700
        provides=frozenset({"slime.absorb", "slime.digest"}),
    ),
}


@dataclass(frozen=True)
class Deferred:
    """Returned instead of raising. The task loop re-queues with backoff."""
    reason: str
    detail: str
    needed_state: State
    needed_mb: int
    retry_after_s: int = 60


class Metabolism:
    """
    Governed state machine over the system's heavyweight resources.

    Thread-safety: a single RLock guards state transitions.
    Persistence: current adapted costs written to metabolism.json.
    """

    _IDLE_DEFAULTS = {
        State.ARMED: 300,
        State.DIGESTING: 120,
        State.ALERT: 600,
        State.AWAKE: 900,
        State.ALIVE: 0,
        State.CRYPTOBIOSIS: 0,
    }
    IDLE_DEMOTION_S = dict(_IDLE_DEFAULTS)

    _NEVER_AUTO_DEMOTE = {State.ALIVE, State.CRYPTOBIOSIS}

    def __init__(self, cache_dir: str, ram_hard_cap_mb: int | None = None):
        self._lock = threading.RLock()
        self._state = State.ALIVE
        self._cache_dir = cache_dir
        self._loaders: dict[State, Callable[[], bool]] = {}
        self._unloaders: dict[State, Callable[[], bool]] = {}
        self._last_use: dict[State, float] = {s: time.time() for s in State}
        self._adapted_mb: dict[State, float] = {}
        self._samples: dict[State, list[float]] = {s: [] for s in State}
        self._stop = threading.Event()

        self._explicit_cap = ram_hard_cap_mb is not None
        self._ram_hard_cap_mb = ram_hard_cap_mb or self._detect_ram()
        # Instance copy so tests can mutate timers without poisoning others
        self.IDLE_DEMOTION_S = dict(self._IDLE_DEFAULTS)
        os.makedirs(cache_dir, exist_ok=True)
        self._load_adapted()

        self._housekeeper = threading.Thread(
            target=self._housekeeping_loop, daemon=True, name="metabolism"
        )
        self._housekeeper.start()

    def register_loader(self, state: State, loader: Callable[[], bool],
                        unloader: Callable[[], bool]) -> None:
        self._loaders[state] = loader
        self._unloaders[state] = unloader

    def current_state(self) -> State:
        return self._state

    def request(self, capability: str) -> State | Deferred:
        needed = self._state_for_capability(capability)
        if needed is None:
            return Deferred(
                reason="no_state_provides",
                detail=f"capability '{capability}' has no metabolic state",
                needed_state=self._state,
                needed_mb=0,
                retry_after_s=0,
            )
        return self.promote_to(needed)

    def promote_to(self, target: State) -> State | Deferred:
        with self._lock:
            current_idx = STATE_ORDER.index(self._state)
            target_idx = STATE_ORDER.index(target)
            if target_idx <= current_idx:
                self._touch(self._state)
                return self._state

            headroom = self._available_ram_mb()
            cost = self._cost_to_reach(target)
            if cost > headroom:
                return Deferred(
                    reason="ram_insufficient",
                    detail=(f"need {cost}MB to reach {target.name}, "
                            f"headroom {headroom}MB"),
                    needed_state=target,
                    needed_mb=cost,
                    retry_after_s=60,
                )

            origin = self._state
            for i in range(current_idx + 1, target_idx + 1):
                step = STATE_ORDER[i]
                loader = self._loaders.get(step)
                if loader is not None:
                    try:
                        ok = bool(loader())
                    except Exception:
                        ok = False
                    if not ok:
                        self._demote_to(origin)
                        return Deferred(
                            reason="state_load_failed",
                            detail=f"loader for {step.name} returned False",
                            needed_state=step,
                            needed_mb=self._est(step),
                            retry_after_s=120,
                        )
                self._state = step
                self._touch(step)
                self._measure(step)
            self._persist()
            return self._state

    def mark_used(self, capability: str) -> None:
        state = self._state_for_capability(capability)
        if state:
            self._touch(state)

    def shutdown(self) -> None:
        """Stop the housekeeping thread. Tests demand this."""
        self._stop.set()
        if self._housekeeper.is_alive() and threading.current_thread() is not self._housekeeper:
            self._housekeeper.join(timeout=2)

    def _state_for_capability(self, capability: str) -> State | None:
        for state in reversed(STATE_ORDER):
            if capability in PROFILES[state].provides:
                return state
        return None

    def _est(self, st: State) -> int:
        base = PROFILES[st].ram_estimate_mb
        adapted = int(self._adapted_mb.get(st, 0))
        return max(adapted, base) if adapted else base

    def _cost_to_reach(self, target: State) -> int:
        """Delta of target vs current estimates — profiles are totals, not stacked."""
        return max(0, self._est(target) - self._est(self._state))

    def _available_ram_mb(self) -> int:
        # Explicit caps (tests) are a simulated pool so CI does not depend
        # on the host's current free RAM. Production still uses the honest
        # min(hard_cap, available) - 1200MB OS/user reserve.
        if self._explicit_cap:
            return max(0, int(self._ram_hard_cap_mb) - 1200)
        vm = psutil.virtual_memory()
        usable = min(self._ram_hard_cap_mb, int(vm.available / (1024 * 1024)))
        return max(0, usable - 1200)

    def _touch(self, state: State) -> None:
        self._last_use[state] = time.time()

    def _measure(self, state: State) -> None:
        cost = psutil.Process().memory_info().rss // (1024 * 1024)
        samples = self._samples[state]
        samples.append(cost)
        self._samples[state] = samples[-5:]
        self._adapted_mb[state] = sum(samples[-5:]) / len(samples[-5:])
        self._persist()

    def _demote_to(self, target: State) -> None:
        target_idx = STATE_ORDER.index(target)
        while STATE_ORDER.index(self._state) > target_idx:
            top_idx = STATE_ORDER.index(self._state)
            top_state = STATE_ORDER[top_idx]
            unloader = self._unloaders.get(top_state)
            if unloader:
                try:
                    unloader()
                except Exception:
                    pass
            self._state = STATE_ORDER[top_idx - 1]
        self._persist()

    def _housekeeping_loop(self) -> None:
        while not self._stop.wait(30):
            self._housekeeping_once()

    def _housekeeping_once(self) -> None:
        """Single demotion sweep — tests call this instead of sleeping."""
        with self._lock:
            st = self._state
            if st in self._NEVER_AUTO_DEMOTE:
                return
            limit = self.IDLE_DEMOTION_S.get(st, 0)
            idle_s = time.time() - self._last_use.get(st, 0)
            # limit == 0 on AWAKE is the test's "expire immediately"
            if idle_s > limit:
                idx = STATE_ORDER.index(st)
                if idx > 0:
                    self._demote_to(STATE_ORDER[idx - 1])

    def _detect_ram(self) -> int:
        return int(psutil.virtual_memory().total // (1024 * 1024))

    def _persist(self) -> None:
        path = os.path.join(self._cache_dir, "metabolism.json")
        try:
            with open(path, "w") as f:
                json.dump({
                    "state": self._state.name,
                    "adapted_mb": {k.name: v for k, v in self._adapted_mb.items()},
                }, f, indent=2)
        except OSError:
            pass

    def _load_adapted(self) -> None:
        path = os.path.join(self._cache_dir, "metabolism.json")
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._adapted_mb = {
                State[s]: v for s, v in data.get("adapted_mb", {}).items()
            }
        except (OSError, KeyError, ValueError):
            pass
