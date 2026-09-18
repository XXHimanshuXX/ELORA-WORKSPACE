"""
test_wasm_gastric.py — Inspection rung for WASM gastric stage interpreter.

Pass criteria:
  - add(a, b) asserted against independent Python calculation across diverse inputs.
  - Fuel metering provably traps infinite runaway loops.
  - Fuel exhaustion halts execution when budget is smaller than instruction count.
  - Arity checking traps mismatched argument counts.
  - Illegal opcodes / syscall attempts trapped immediately (no_std isolation).
"""

import pytest
from elora.core.wasm_gastric import (
    WasmiLike,
    WasmModule,
    WasmTrap,
    compile_pure_add,
    compile_from_digest,
    write_skill_wasm,
    MEMORY_BYTES,
    OP_BR_REL,
    OP_LOCAL_GET,
    OP_I32_ADD,
    OP_RETURN,
    OP_END,
)


class TestWasmGastricCage:

    def test_independent_arithmetic_computation(self):
        """Verify dynamic execution against independently computed answers."""
        module = compile_pure_add()
        vm = WasmiLike(module)

        cases = [(2, 40), (-15, 25), (1024, 2048), (0, 0), (-50, -30), (7, 42)]
        for a, b in cases:
            # Independent ground truth
            expected = a + b
            result = vm.invoke(a, b)
            assert result == expected

    def test_fuel_metering_halts_finite_program_when_exhausted(self):
        """A program requiring 5 fuel must trap when given only 2."""
        module = compile_pure_add()
        # compile_pure_add has 5 instructions: get, get, add, return, end
        starved_vm = WasmiLike(module, fuel=2)
        with pytest.raises(WasmTrap) as exc:
            starved_vm.invoke(2, 40)
        assert "out of fuel" in str(exc.value)

    def test_fuel_metering_halts_infinite_loop(self):
        """
        Proof that fuel metering actually halts an infinite loop.
        Bytecode: relative branch back 2 bytes indefinitely.
        0x00: OP_BR_REL (0x0C)
        0x01: -2 (0xFE in two's complement) -> jumps back to 0x00
        """
        infinite_loop_code = bytes([OP_BR_REL, 0xFE])
        loop_module = WasmModule(code=infinite_loop_code, n_locals=0, n_params=0)

        fuel_budget = 100
        vm = WasmiLike(loop_module, fuel=fuel_budget)

        with pytest.raises(WasmTrap) as exc:
            vm.invoke()
        assert "out of fuel" in str(exc.value)
        assert vm.fuel == -1

    def test_arity_trap(self):
        module = compile_pure_add()
        vm = WasmiLike(module)
        with pytest.raises(WasmTrap) as exc:
            vm.invoke(1)  # needs 2
        assert "arity" in str(exc.value)

        with pytest.raises(WasmTrap) as exc:
            vm.invoke(1, 2, 3)
        assert "arity" in str(exc.value)

    def test_illegal_opcode_trapped(self):
        # 0xEE is not a valid gastric IR opcode
        bad_code = bytes([0xEE, OP_RETURN, OP_END])
        bad_module = WasmModule(code=bad_code, n_locals=0, n_params=0)
        vm = WasmiLike(bad_module)
        with pytest.raises(WasmTrap) as exc:
            vm.invoke()
        assert "illegal opcode" in str(exc.value)
        assert "no syscalls" in str(exc.value)

    def test_memory_boundary_and_serialization(self, tmp_path):
        module = compile_pure_add()
        assert len(module.memory) == MEMORY_BYTES
        assert len(module.memory) == 65536

        wasm_path = tmp_path / "skill.wasm"
        out = write_skill_wasm(str(wasm_path), module)
        assert wasm_path.exists()
        assert wasm_path.read_bytes().startswith(b"ELW1")
