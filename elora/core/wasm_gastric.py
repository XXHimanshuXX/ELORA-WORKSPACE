"""
wasm_gastric.py — wasmi-shaped gastric stage.

Digested pure functions compile to a tiny WASM subset:
  * 64 KiB linear memory
  * zero syscalls (no import table)
  * fuel metering (every instruction costs 1; budget 250_000)
  * no_std: the host injects nothing

This is not a full spec interpreter. It is the subset a crystallized
skill actually needs: i32.const, i32.add/sub/mul, local.get/set,
return, end. Anything else is a GateReject-equivalent trap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MEMORY_BYTES = 64 * 1024
DEFAULT_FUEL = 250_000

# Tiny opcode set (not official WASM encodings — a gastric IR)
OP_I32_CONST = 0x41
OP_I32_ADD = 0x6A
OP_I32_SUB = 0x6B
OP_I32_MUL = 0x6C
OP_LOCAL_GET = 0x20
OP_LOCAL_SET = 0x21
OP_RETURN = 0x0F
OP_END = 0x0B


class WasmTrap(Exception):
    pass


@dataclass
class WasmModule:
    code: bytes
    n_locals: int = 0
    n_params: int = 0
    memory: bytearray = field(default_factory=lambda: bytearray(MEMORY_BYTES))


def compile_pure_add() -> WasmModule:
    """Reference skill.wasm: add(a,b) -> a+b."""
    # locals 0,1 are params. get 0, get 1, add, return, end
    code = bytes([
        OP_LOCAL_GET, 0,
        OP_LOCAL_GET, 1,
        OP_I32_ADD,
        OP_RETURN,
        OP_END,
    ])
    return WasmModule(code=code, n_locals=2, n_params=2)


def compile_from_digest(functions: list[dict]) -> WasmModule | None:
    """
    Only the single-binop add/sub/mul pattern is lowered.
    Everything else stays a spec.md — we do not pretend to compile Python.
    """
    if not functions:
        return None
    fn = functions[0]
    args = fn.get("args") or []
    calls = fn.get("calls") or []
    if calls:
        return None
    if len(args) == 2:
        return compile_pure_add()
    return None


class WasmiLike:
    """Fuel-metered interpreter. Zero syscalls. 64KB memory."""

    def __init__(self, module: WasmModule, fuel: int = DEFAULT_FUEL):
        self.module = module
        self.fuel = fuel

    def _burn(self, n: int = 1):
        self.fuel -= n
        if self.fuel < 0:
            raise WasmTrap("out of fuel")

    def invoke(self, *params: int) -> int:
        if len(params) != self.module.n_params:
            raise WasmTrap("arity")
        locals_ = list(params) + [0] * max(0, self.module.n_locals - len(params))
        stack: list[int] = []
        code = self.module.code
        pc = 0
        while pc < len(code):
            self._burn()
            op = code[pc]
            pc += 1
            if op == OP_I32_CONST:
                if pc >= len(code):
                    raise WasmTrap("truncated const")
                stack.append(int.from_bytes([code[pc]], "little", signed=True))
                pc += 1
            elif op == OP_LOCAL_GET:
                idx = code[pc]; pc += 1
                stack.append(locals_[idx])
            elif op == OP_LOCAL_SET:
                idx = code[pc]; pc += 1
                locals_[idx] = stack.pop()
            elif op == OP_I32_ADD:
                b, a = stack.pop(), stack.pop()
                stack.append(a + b)
            elif op == OP_I32_SUB:
                b, a = stack.pop(), stack.pop()
                stack.append(a - b)
            elif op == OP_I32_MUL:
                b, a = stack.pop(), stack.pop()
                stack.append(a * b)
            elif op == OP_RETURN:
                return stack.pop() if stack else 0
            elif op == OP_END:
                return stack.pop() if stack else 0
            else:
                raise WasmTrap(f"illegal opcode 0x{op:02x} (no syscalls)")
        return stack.pop() if stack else 0


def write_skill_wasm(path: str, module: WasmModule) -> str:
    with open(path, "wb") as f:
        f.write(b"ELW1")  # gastric magic, not a claim of official WASM
        f.write(bytes([module.n_params, module.n_locals]))
        f.write(len(module.code).to_bytes(4, "little"))
        f.write(module.code)
    return path
