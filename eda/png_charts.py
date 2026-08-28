"""Dependency-free raster helpers for aggregate PNG cohort figures."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

RGB = tuple[int, int, int]

FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000",) * 7,
    "?": ("01110", "10001", "00010", "00100", "00100", "00000", "00100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00110", "00100"),
    ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "|": ("00100",) * 7,
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"),
}


class Canvas:
    """Minimal RGB canvas with bitmap text and standards-compliant PNG output."""

    def __init__(self, width: int, height: int, background: RGB = (255, 255, 255)) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(background * (width * height))

    def rectangle(self, x: int, y: int, width: int, height: int, color: RGB) -> None:
        left = max(0, x)
        top = max(0, y)
        right = min(self.width, x + width)
        bottom = min(self.height, y + height)
        for row in range(top, bottom):
            start = (row * self.width + left) * 3
            self.pixels[start : start + (right - left) * 3] = bytes(color) * (right - left)

    def outline(
        self, x: int, y: int, width: int, height: int, color: RGB, thickness: int = 1
    ) -> None:
        self.rectangle(x, y, width, thickness, color)
        self.rectangle(x, y + height - thickness, width, thickness, color)
        self.rectangle(x, y, thickness, height, color)
        self.rectangle(x + width - thickness, y, thickness, height, color)

    def text(
        self, x: int, y: int, value: object, color: RGB = (20, 20, 20), scale: int = 2
    ) -> None:
        cursor = x
        for character in str(value).upper():
            glyph = FONT.get(character, FONT["?"])
            for row, pattern in enumerate(glyph):
                for column, bit in enumerate(pattern):
                    if bit == "1":
                        self.rectangle(
                            cursor + column * scale,
                            y + row * scale,
                            scale,
                            scale,
                            color,
                        )
            cursor += 6 * scale

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = bytearray()
        stride = self.width * 3
        for row in range(self.height):
            raw.append(0)
            raw.extend(self.pixels[row * stride : (row + 1) * stride])

        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

        header = struct.pack(">IIBBBBB", self.width, self.height, 8, 2, 0, 0, 0)
        payload = b"\x89PNG\r\n\x1a\n"
        payload += chunk(b"IHDR", header)
        payload += chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
        payload += chunk(b"IEND", b"")
        path.write_bytes(payload)


def gap_color(value: float | None) -> RGB:
    """Map a 0-1 treatment gap to a pale-yellow through dark-red color."""
    if value is None:
        return (220, 224, 230)
    clipped = min(1.0, max(0.0, value))
    low = (255, 247, 188)
    high = (177, 0, 38)
    return tuple(round(low[index] + (high[index] - low[index]) * clipped) for index in range(3))


def contrasting_text(color: RGB) -> RGB:
    """Select readable black or white text for a filled cell."""
    luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    return (20, 20, 20) if luminance >= 145 else (255, 255, 255)
