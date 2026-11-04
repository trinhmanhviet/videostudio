"""Generate the VideoStudio tray/exe icons (pure Python, no Pillow).

Run: python scripts/make_tray_icons.py  ->  scripts/assets/videostudio*.ico
"""
from pathlib import Path
import struct
import zlib

SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
BASE = (37, 99, 235)          # blue background: visible on dark and light taskbars
PLAY = (248, 250, 252)       # white play mark
DOTS = {'ready': (34, 197, 94), 'busy': (245, 158, 11), 'stopped': (148, 163, 184)}


def _inside_round_rect(x, y, size, radius):
    r = radius
    cx = min(max(x, r), size - r)
    cy = min(max(y, r), size - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r and 0 <= x <= size and 0 <= y <= size


def _inside_triangle(x, y, a, b, c):
    def side(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    d1, d2, d3 = side((x, y), a, b), side((x, y), b, c), side((x, y), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render(size, dot=None, samples=4):
    radius = size * 0.22
    # Play mark sits a little left/up when a status dot occupies the corner.
    shift = size * 0.06 if dot else 0
    a = (size * 0.36 - shift, size * 0.26 - shift)
    b = (size * 0.36 - shift, size * 0.74 - shift)
    c = (size * 0.76 - shift, size * 0.50 - shift)
    dot_r = size * 0.24
    dot_c = (size - dot_r - size * 0.02, size - dot_r - size * 0.02)
    ring = size * 0.07
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(samples):
                for sx in range(samples):
                    x = px + (sx + .5) / samples
                    y = py + (sy + .5) / samples
                    color = None
                    if dot and (x - dot_c[0]) ** 2 + (y - dot_c[1]) ** 2 <= dot_r ** 2:
                        inner = (x - dot_c[0]) ** 2 + (y - dot_c[1]) ** 2 <= (dot_r - ring) ** 2
                        color = DOTS[dot] if inner else (255, 255, 255)
                    elif _inside_round_rect(x, y, size, radius):
                        color = PLAY if _inside_triangle(x, y, a, b, c) else BASE
                    if color:
                        acc[0] += color[0]; acc[1] += color[1]; acc[2] += color[2]; acc[3] += 1
            n = samples * samples
            alpha = acc[3] / n
            if acc[3]:
                row += bytes((round(acc[0] / acc[3]), round(acc[1] / acc[3]), round(acc[2] / acc[3]), round(alpha * 255)))
            else:
                row += b'\0\0\0\0'
        rows.append(bytes(row))
    return b''.join(rows)


def png(size, pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(pixels, 9)) + chunk(b'IEND', b'')


def ico(images):
    """ICO container with PNG entries (supported by Windows Vista and later)."""
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b'', b''
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return header + entries + blobs


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name, dot, sizes in (('videostudio', None, SIZES),
                             ('videostudio-ready', 'ready', SIZES[:6]),
                             ('videostudio-busy', 'busy', SIZES[:6]),
                             ('videostudio-stopped', 'stopped', SIZES[:6])):
        path = destination / (name + '.ico')
        path.write_bytes(ico([(s, png(s, render(s, dot))) for s in sizes]))
        outputs[name] = path
    return outputs


if __name__ == '__main__':
    for name, path in build(Path(__file__).resolve().parent / 'assets').items():
        print(name, path, path.stat().st_size)
