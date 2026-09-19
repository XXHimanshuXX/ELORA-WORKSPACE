"""
verify_webgpu.py — Verify WebGPU rendering of overlay/organism.wgsl.
Runs an offscreen render pass on GPU or software adapter and verifies pixel output.
"""

from __future__ import annotations

import hashlib
import os
import struct
import sys


def verify_webgpu_render() -> tuple[bool, str]:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shader_path = os.path.join(here, "overlay", "organism.wgsl")
    if not os.path.exists(shader_path):
        return False, f"shader not found: {shader_path}"

    try:
        import wgpu
    except ImportError:
        return False, "wgpu module not installed"

    try:
        with open(shader_path, "r", encoding="utf-8") as f:
            shader_code = f.read()

        adapter = wgpu.gpu.request_adapter_sync()
        if not adapter:
            return False, "no WebGPU adapter available"

        device = adapter.request_device_sync()
        c_module = device.create_shader_module(code=shader_code)

        # 256x256 offscreen render target
        width, height = 256, 256
        texture = device.create_texture(
            size=(width, height, 1),
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
            format=wgpu.TextureFormat.rgba8unorm,
        )

        # Uniform buffer: time(f32), state(f32), chainOk(f32), cpuLimit(f32), ripple(f32), pad (aligned vec3) = 48 bytes in WGSL
        uniform_data = struct.pack("<12f", 1.0, 2.0, 1.0, 60.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        uniform_buffer = device.create_buffer_with_data(
            data=uniform_data,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )

        bind_group_layout = device.create_bind_group_layout(
            entries=[
                {
                    "binding": 0,
                    "visibility": wgpu.ShaderStage.FRAGMENT,
                    "buffer": {"type": wgpu.BufferBindingType.uniform},
                }
            ]
        )

        bind_group = device.create_bind_group(
            layout=bind_group_layout,
            entries=[{"binding": 0, "resource": {"buffer": uniform_buffer, "offset": 0, "size": 48}}],
        )

        pipeline_layout = device.create_pipeline_layout(bind_group_layouts=[bind_group_layout])

        pipeline = device.create_render_pipeline(
            layout=pipeline_layout,
            vertex={
                "module": c_module,
                "entry_point": "vs",
                "buffers": [],
            },
            fragment={
                "module": c_module,
                "entry_point": "fs",
                "targets": [{"format": wgpu.TextureFormat.rgba8unorm}],
            },
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list},
        )

        command_encoder = device.create_command_encoder()
        render_pass = command_encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": texture.create_view(),
                    "resolve_target": None,
                    "clear_value": (0.0, 0.0, 0.0, 0.0),
                    "load_op": wgpu.LoadOp.clear,
                    "store_op": wgpu.StoreOp.store,
                }
            ]
        )
        render_pass.set_pipeline(pipeline)
        render_pass.set_bind_group(0, bind_group)
        render_pass.draw(3, 1, 0, 0)
        render_pass.end()

        # Read back to buffer: 256 bytes per row alignment
        bytes_per_pixel = 4
        bytes_per_row = (width * bytes_per_pixel + 255) & ~255
        buffer_size = bytes_per_row * height
        read_buffer = device.create_buffer(
            size=buffer_size,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        )

        command_encoder.copy_texture_to_buffer(
            source={"texture": texture, "origin": (0, 0, 0)},
            destination={"buffer": read_buffer, "bytes_per_row": bytes_per_row, "rows_per_image": height},
            copy_size=(width, height, 1),
        )

        device.queue.submit([command_encoder.finish()])
        read_buffer.map_sync(wgpu.MapMode.READ)
        data = bytes(read_buffer.read_mapped())
        read_buffer.unmap()

        non_zero = sum(1 for b in data if b > 0)
        digest = hashlib.sha256(data).hexdigest()[:12]

        if non_zero > 0:
            return True, f"{adapter.summary} (frame sha: {digest}, non-zero: {non_zero})"
        return False, "render produced zero/black frame"
    except Exception as e:
        return False, f"webgpu execution failed: {e}"


if __name__ == "__main__":
    ok, msg = verify_webgpu_render()
    print(f"[{'OK' if ok else 'FAIL'}] WebGPU: {msg}")
    sys.exit(0 if ok else 1)
