"""Write three tiny unique PNG previews for design cards (no PIL)."""
import os
import struct
import zlib

OUT = os.path.join(".ohmyagent", "design", "v1", "template-previews")
os.makedirs(OUT, exist_ok=True)


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def png(path, w, h, pixels):
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    body = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(body)


def lerp(a, b, t):
    return int(a + (b - a) * t)


def frame(w, h, kind):
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            nx, ny = x / w, y / h
            if kind == 0:
                r = lerp(6, 18, ny)
                g = lerp(10, 40, nx)
                b = lerp(14, 48, (nx + ny) / 2)
                if abs(nx - 0.5) < 0.004 or abs(ny - 0.48) < 0.004:
                    r, g, b = 80, 255, 210
                if (x - w // 2) ** 2 + (y - h // 2) ** 2 < 90:
                    r, g, b = 40, 220, 190
                if x < 28:
                    r, g, b = lerp(r, 8, 0.6), lerp(g, 16, 0.6), lerp(b, 22, 0.6)
            elif kind == 1:
                r = lerp(18, 8, ny)
                g = lerp(4, 10, nx)
                b = lerp(8, 16, ny)
                if 40 < x < w - 40 and 36 < y < h - 36 and (x % 48 < 2 or y % 36 < 2):
                    r, g, b = 255, 90, 70
                if 80 < x < w - 80 and 50 < y < 90:
                    r, g, b = 220, 40, 50
            else:
                r = lerp(4, 12, nx)
                g = lerp(8, 20, ny)
                b = lerp(22, 70, nx)
                cx, cy = w * 0.62, h * 0.42
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if int(d) % 18 < 2:
                    r, g, b = 120, 180, 255
                if d < 22:
                    r, g, b = 230, 240, 255
            row.extend((r, g, b))
        rows.append(row)
    return rows


w, h = 640, 360
names = ("neural-hive.png", "crimson-cockpit.png", "orbital-rings.png")
for i, name in enumerate(names):
    png(os.path.join(OUT, name), w, h, frame(w, h, i))
    print("wrote", name)
