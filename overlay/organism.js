// organism.js — mounts the WebGPU canvas, feeds it live metabolism + ripples.
// Honest: if WebGPU is unavailable, reports "[WARN] organism offline" and
// shows a static CSS circle. Never fakes a render.

export class Organism {
  constructor(canvas) {
    this.canvas = canvas;
    this.running = false;
    this.state = 1;
    this.seed = 0.5;
    this.headroom = 0.7;
    this.rippleUntil = 0;
    this.ripple = 0;
  }

  _renderOffline() {
    this.canvas.style.background = "#14171d";
    this.canvas.dataset.status = "offline";
    try {
      const ctx2d = this.canvas.getContext("2d");
      if (ctx2d) {
        const w = this.canvas.width;
        const h = this.canvas.height;
        ctx2d.clearRect(0, 0, w, h);
        ctx2d.fillStyle = "#14171d";
        ctx2d.fillRect(0, 0, w, h);
        ctx2d.strokeStyle = "#2e3642";
        ctx2d.lineWidth = 1.5;
        ctx2d.setLineDash([5, 5]);
        ctx2d.beginPath();
        ctx2d.arc(w / 2, h / 2, 54, 0, Math.PI * 2);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
        ctx2d.fillStyle = "#7b8798";
        ctx2d.font = "11px monospace";
        ctx2d.textAlign = "center";
        ctx2d.fillText("organism offline", w / 2, h / 2 - 4);
        ctx2d.fillStyle = "#4a5360";
        ctx2d.font = "9px monospace";
        ctx2d.fillText("no webgpu adapter", w / 2, h / 2 + 12);
      }
    } catch (_) {}
  }

  async init() {
    if (!this.canvas) return false;
    if (typeof navigator === "undefined" || !navigator.gpu) {
      this._renderOffline();
      return false;
    }
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) {
        this._renderOffline();
        return false;
      }
      this.device = await adapter.requestDevice();
      const ctx = this.canvas.getContext("webgpu");
      if (!ctx) {
        this._renderOffline();
        return false;
      }
      const format = navigator.gpu.getPreferredCanvasFormat();
      ctx.configure({ device: this.device, format, alphaMode: "opaque" });
      this.ctx = ctx;
      this.format = format;

      const resp = await fetch("organism.wgsl");
      if (!resp.ok) {
        this._renderOffline();
        return false;
      }
      const shader = await resp.text();
      this.pipeline = this.device.createRenderPipeline({
        layout: "auto",
        vertex: {
          module: this.device.createShaderModule({ code: shader }),
          entryPoint: "vs",
        },
        fragment: {
          module: this.device.createShaderModule({ code: shader }),
          entryPoint: "fs",
          targets: [{ format }],
        },
        primitive: { topology: "triangle-list" },
      });
      this.uniforms = this.device.createBuffer({
        size: 32 * 4,
        usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
      });
      this.bindGroup = this.device.createBindGroup({
        layout: this.pipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer: this.uniforms } }],
      });
      this.running = true;
      this.canvas.dataset.status = "online";
      this._loop();
      return true;
    } catch (err) {
      this._renderOffline();
      return false;
    }
  }

  setState(s) { this.state = s; }             // 0..5
  setSeed(seedFloat) { this.seed = seedFloat; }
  setHeadroom(h) { this.headroom = h; }
  ripple() { this.rippleUntil = performance.now() + 400; }

  _loop() {
    if (!this.running) return;
    const now = performance.now() / 1000;
    const ripple = this.rippleUntil > performance.now() ? 1 : Math.max(0, (this.ripple || 0) * 0.95);
    this.ripple = ripple;

    const data = new Float32Array([
      this.canvas.width, this.canvas.height,
      now,
      this.state ?? 1,
      1.0,
      60.0,
      this.seed ?? 0.5,
      this.headroom ?? 0.7,
      ripple, 0, 0, 0, 0, 0, 0, 0,
    ]);
    this.device.queue.writeBuffer(this.uniforms, 0, data);

    const enc = this.device.createCommandEncoder();
    const pass = enc.beginRenderPass({
      colorAttachments: [{
        view: this.ctx.getCurrentTexture().createView(),
        clearValue: { r: 0.03, g: 0.04, b: 0.06, a: 1 },
        loadOp: "clear",
        storeOp: "store",
      }],
    });
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.bindGroup);
    pass.draw(3);
    pass.end();
    this.device.queue.submit([enc.finish()]);
    requestAnimationFrame(() => this._loop());
  }
}
