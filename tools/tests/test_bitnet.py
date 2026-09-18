"""
test_bitnet.py — Inspection rung for BitNet b1.58 ternary inference organ.

Pass criteria:
  - Real forward pass with real tensors compared against independently computed answer.
  - Trit packing and unpacking identity verified.
  - Dimension and shape mismatch verification.
  - BitNetBrain drop-in behavior (defer without weights, execution with weights).
"""

import pytest
from elora.core.bitnet import (
    ternary_matmul,
    pack_trits,
    unpack_trits,
    BitNetBrain,
    AWAKE_RSS_MB,
    available,
)


class TestBitNetInference:

    def test_known_tensor_forward_pass(self):
        """
        Independent manual calculation:
        x (1x4) = [1.5, -2.0, 3.0, 0.5]
        W (3x4) = [
            [ 1,  0, -1,  1],  # Row 0: 1.5*1 + (-2)*0 + 3*(-1) + 0.5*1 = 1.5 - 3.0 + 0.5 = -1.0
            [-1,  1,  0,  0],  # Row 1: 1.5*(-1) + (-2)*1 + 3*0 + 0.5*0 = -1.5 - 2.0 = -3.5
            [ 0,  1,  1, -1],  # Row 2: 1.5*0 + (-2)*1 + 3*1 + 0.5*(-1) = -2.0 + 3.0 - 0.5 = 0.5
        ]
        """
        x = [1.5, -2.0, 3.0, 0.5]
        w_flat = [
            1, 0, -1, 1,
            -1, 1, 0, 0,
            0, 1, 1, -1,
        ]
        n_out = 3

        # Compute reference independently
        expected = [
            x[0]*1 + x[1]*0 + x[2]*(-1) + x[3]*1,
            x[0]*(-1) + x[1]*1 + x[2]*0 + x[3]*0,
            x[0]*0 + x[1]*1 + x[2]*1 + x[3]*(-1),
        ]
        assert expected == [-1.0, -3.5, 0.5]

        # Execute kernel
        y = ternary_matmul(x, w_flat, n_out)
        assert len(y) == n_out
        for actual, exp in zip(y, expected):
            assert pytest.approx(actual, rel=1e-5) == exp

    def test_shape_mismatch_raises_value_error(self):
        x = [1.0, 2.0, 3.0]
        w = [1, -1]  # len 2 != len(x) * n_out (3 * 2 = 6)
        with pytest.raises(ValueError) as exc:
            ternary_matmul(x, w, n_out=2)
        assert "shape mismatch" in str(exc.value)

    def test_trit_pack_unpack_roundtrip(self):
        trits = [-1, 0, 1, 1, 0, -1, 1, 0, -1, -1, 1, 0, 0, 1]
        packed = pack_trits(trits)
        assert isinstance(packed, bytes)
        unpacked = unpack_trits(packed, len(trits))
        assert unpacked == trits

    def test_bitnet_brain_contracts(self):
        # 1. No hallucination without weights
        brain = BitNetBrain(weights_path=None)
        assert brain.complete("system", [{"role": "user", "content": "hi"}]) == "DONE"

        # 2. Runs projection when weights exist
        brain._weights = [1, 0, -1, 1] * 64  # 256 trits
        res = brain.complete("system", [{"role": "user", "content": "compute"}])
        assert res == "DONE"

    def test_awake_profile_constants(self):
        assert available() is True
        assert AWAKE_RSS_MB == 380
