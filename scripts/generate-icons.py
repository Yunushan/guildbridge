from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS_ASSET = ROOT / "docs" / "assets" / "guildbridge-icon.svg"
PACKAGE_ASSETS = ROOT / "src" / "guildbridge" / "assets"
WINDOWS_ICON = ROOT / "packaging" / "windows" / "guildbridge.ico"

BASE = 256

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="GuildBridge icon">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0f172a"/>
      <stop offset="1" stop-color="#153044"/>
    </linearGradient>
    <linearGradient id="bridge" x1="54" y1="92" x2="202" y2="178" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#7dd3fc"/>
      <stop offset="1" stop-color="#2dd4bf"/>
    </linearGradient>
  </defs>
  <rect x="12" y="12" width="232" height="232" rx="48" fill="url(#bg)"/>
  <path d="M62 166 Q128 82 194 166" fill="none" stroke="url(#bridge)" stroke-width="16" stroke-linecap="round"/>
  <path d="M60 172 H196" fill="none" stroke="#2dd4bf" stroke-width="14" stroke-linecap="round"/>
  <rect x="54" y="86" width="34" height="92" rx="12" fill="#111827" stroke="#7dd3fc" stroke-width="8"/>
  <rect x="168" y="86" width="34" height="92" rx="12" fill="#111827" stroke="#2dd4bf" stroke-width="8"/>
  <path d="M128 84 L164 102 L158 158 L128 186 L98 158 L92 102 Z" fill="#172033" stroke="#e2e8f0" stroke-width="7" stroke-linejoin="round"/>
  <path d="M108 133 H145" fill="none" stroke="#f8fafc" stroke-width="10" stroke-linecap="round"/>
  <path d="M137 119 L154 133 L137 147" fill="none" stroke="#f8fafc" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="72" cy="122" r="10" fill="#7dd3fc"/>
  <circle cx="184" cy="122" r="10" fill="#2dd4bf"/>
</svg>
"""


Color = tuple[int, int, int, int]
Point = tuple[float, float]


def rgba(hex_color: str, alpha: int = 255) -> Color:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


def mix(a: Color, b: Color, t: float) -> Color:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4))  # type: ignore[return-value]


def blend(buf: bytearray, width: int, x: int, y: int, color: Color) -> None:
    if x < 0 or y < 0 or x >= width or y >= width:
        return
    offset = (y * width + x) * 4
    sr, sg, sb, sa = color
    da = buf[offset + 3]
    if sa == 255 or da == 0:
        buf[offset : offset + 4] = bytes(color)
        return
    alpha = sa / 255
    inv = 1 - alpha
    buf[offset] = round(sr * alpha + buf[offset] * inv)
    buf[offset + 1] = round(sg * alpha + buf[offset + 1] * inv)
    buf[offset + 2] = round(sb * alpha + buf[offset + 2] * inv)
    buf[offset + 3] = min(255, round(sa + da * inv))


def in_round_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> bool:
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r**2


def fill_round_rect(buf: bytearray, width: int, box: tuple[float, float, float, float], radius: float, color: Color) -> None:
    x0, y0, x1, y1 = box
    for y in range(math.floor(y0), math.ceil(y1)):
        for x in range(math.floor(x0), math.ceil(x1)):
            if in_round_rect(x + 0.5, y + 0.5, x0, y0, x1, y1, radius):
                blend(buf, width, x, y, color)


def fill_circle(buf: bytearray, width: int, cx: float, cy: float, radius: float, color: Color) -> None:
    r2 = radius * radius
    for y in range(math.floor(cy - radius), math.ceil(cy + radius)):
        for x in range(math.floor(cx - radius), math.ceil(cx + radius)):
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r2:
                blend(buf, width, x, y, color)


def fill_polygon(buf: bytearray, width: int, points: Iterable[Point], color: Color) -> None:
    pts = list(points)
    min_x = math.floor(min(x for x, _ in pts))
    max_x = math.ceil(max(x for x, _ in pts))
    min_y = math.floor(min(y for _, y in pts))
    max_y = math.ceil(max(y for _, y in pts))
    for y in range(min_y, max_y):
        for x in range(min_x, max_x):
            inside = False
            j = len(pts) - 1
            px, py = x + 0.5, y + 0.5
            for i, (xi, yi) in enumerate(pts):
                xj, yj = pts[j]
                if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                    inside = not inside
                j = i
            if inside:
                blend(buf, width, x, y, color)


def stroke_segment(buf: bytearray, width: int, a: Point, b: Point, stroke_width: float, color: Color) -> None:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    radius = stroke_width / 2
    min_x = math.floor(min(ax, bx) - radius)
    max_x = math.ceil(max(ax, bx) + radius)
    min_y = math.floor(min(ay, by) - radius)
    max_y = math.ceil(max(ay, by) + radius)
    for y in range(min_y, max_y):
        for x in range(min_x, max_x):
            if length2 == 0:
                distance2 = (x + 0.5 - ax) ** 2 + (y + 0.5 - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((x + 0.5 - ax) * dx + (y + 0.5 - ay) * dy) / length2))
                px, py = ax + t * dx, ay + t * dy
                distance2 = (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2
            if distance2 <= radius * radius:
                blend(buf, width, x, y, color)


def stroke_polyline(buf: bytearray, width: int, points: list[Point], stroke_width: float, color: Color) -> None:
    for start, end in zip(points, points[1:], strict=False):
        stroke_segment(buf, width, start, end, stroke_width, color)
    for x, y in points:
        fill_circle(buf, width, x, y, stroke_width / 2, color)


def curve_points() -> list[Point]:
    points: list[Point] = []
    for i in range(64):
        t = i / 63
        x = (1 - t) ** 2 * 62 + 2 * (1 - t) * t * 128 + t**2 * 194
        y = (1 - t) ** 2 * 166 + 2 * (1 - t) * t * 82 + t**2 * 166
        points.append((x, y))
    return points


def scale_points(points: Iterable[Point], factor: float) -> list[Point]:
    return [(x * factor, y * factor) for x, y in points]


def render(size: int, supersample: int = 4) -> bytes:
    width = size * supersample
    factor = width / BASE
    buf = bytearray(width * width * 4)

    bg0 = rgba("#0f172a")
    bg1 = rgba("#153044")
    for y in range(width):
        color = mix(bg0, bg1, y / max(1, width - 1))
        for x in range(width):
            if in_round_rect(x + 0.5, y + 0.5, 12 * factor, 12 * factor, 244 * factor, 244 * factor, 48 * factor):
                blend(buf, width, x, y, color)

    stroke_polyline(buf, width, scale_points(curve_points(), factor), 16 * factor, rgba("#46d3c8"))
    stroke_segment(buf, width, (60 * factor, 172 * factor), (196 * factor, 172 * factor), 14 * factor, rgba("#2dd4bf"))
    fill_round_rect(buf, width, (54 * factor, 86 * factor, 88 * factor, 178 * factor), 12 * factor, rgba("#111827"))
    stroke_polyline(
        buf,
        width,
        [(58 * factor, 91 * factor), (84 * factor, 91 * factor), (84 * factor, 174 * factor), (58 * factor, 174 * factor), (58 * factor, 91 * factor)],
        8 * factor,
        rgba("#7dd3fc"),
    )
    fill_round_rect(buf, width, (168 * factor, 86 * factor, 202 * factor, 178 * factor), 12 * factor, rgba("#111827"))
    stroke_polyline(
        buf,
        width,
        [(172 * factor, 91 * factor), (198 * factor, 91 * factor), (198 * factor, 174 * factor), (172 * factor, 174 * factor), (172 * factor, 91 * factor)],
        8 * factor,
        rgba("#2dd4bf"),
    )

    shield = scale_points(((128, 84), (164, 102), (158, 158), (128, 186), (98, 158), (92, 102)), factor)
    fill_polygon(buf, width, shield, rgba("#172033"))
    stroke_polyline(buf, width, [*shield, shield[0]], 7 * factor, rgba("#e2e8f0"))
    stroke_segment(buf, width, (108 * factor, 133 * factor), (145 * factor, 133 * factor), 10 * factor, rgba("#f8fafc"))
    stroke_polyline(
        buf,
        width,
        [(137 * factor, 119 * factor), (154 * factor, 133 * factor), (137 * factor, 147 * factor)],
        10 * factor,
        rgba("#f8fafc"),
    )
    fill_circle(buf, width, 72 * factor, 122 * factor, 10 * factor, rgba("#7dd3fc"))
    fill_circle(buf, width, 184 * factor, 122 * factor, 10 * factor, rgba("#2dd4bf"))

    if supersample == 1:
        return bytes(buf)

    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            acc = [0, 0, 0, 0]
            for yy in range(supersample):
                for xx in range(supersample):
                    offset = ((y * supersample + yy) * width + (x * supersample + xx)) * 4
                    for i in range(4):
                        acc[i] += buf[offset + i]
            out_offset = (y * size + x) * 4
            samples = supersample * supersample
            out[out_offset : out_offset + 4] = bytes(round(value / samples) for value in acc)
    return bytes(out)


def png_bytes(size: int) -> bytes:
    raw = render(size)
    rows = bytearray()
    stride = size * 4
    for y in range(size):
        rows.append(0)
        rows.extend(raw[y * stride : (y + 1) * stride])
    chunks = [
        chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(bytes(rows), 9)),
        chunk(b"IEND", b""),
    ]
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def bmp_icon_bytes(size: int) -> bytes:
    raw = render(size)
    header = struct.pack("<IIIHHIIIIII", 40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
    pixels = bytearray()
    stride = size * 4
    for y in range(size - 1, -1, -1):
        row = raw[y * stride : (y + 1) * stride]
        for x in range(size):
            red, green, blue, alpha = row[x * 4 : x * 4 + 4]
            pixels.extend((blue, green, red, alpha))
    mask_stride = ((size + 31) // 32) * 4
    return header + bytes(pixels) + bytes(mask_stride * size)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def ico_bytes(sizes: tuple[int, ...]) -> bytes:
    images = [bmp_icon_bytes(size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for size, image in zip(sizes, images, strict=False):
        entries.extend(struct.pack("<BBBBHHII", 0 if size == 256 else size, 0 if size == 256 else size, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    return header + bytes(entries) + b"".join(images)


def main() -> int:
    (ROOT / "docs" / "assets").mkdir(parents=True, exist_ok=True)
    PACKAGE_ASSETS.mkdir(parents=True, exist_ok=True)
    WINDOWS_ICON.parent.mkdir(parents=True, exist_ok=True)

    DOCS_ASSET.write_text(SVG, encoding="utf-8")
    (PACKAGE_ASSETS / "guildbridge-icon.svg").write_text(SVG, encoding="utf-8")
    (PACKAGE_ASSETS / "guildbridge-icon.png").write_bytes(png_bytes(256))
    icon = ico_bytes((16, 24, 32, 48, 64, 128, 256))
    (PACKAGE_ASSETS / "guildbridge-icon.ico").write_bytes(icon)
    WINDOWS_ICON.write_bytes(icon)
    print("Generated GuildBridge icon assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
