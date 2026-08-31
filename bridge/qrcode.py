"""
Pure Python QR Code Generator (Zero external dependencies).
Generates standard QR codes and prints them to the terminal using Unicode half-blocks.
"""

import math
from typing import List, Tuple


# Galois Field (GF(256)) Math Tables for QR Reed-Solomon Error Correction
GF256_EXP = [0] * 512
GF256_LOG = [0] * 256

def _init_gf256():
    x = 1
    for i in range(255):
        GF256_EXP[i] = x
        GF256_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D  # QR Code primitive polynomial: x^8 + x^4 + x^3 + x^2 + 1
    for i in range(255, 512):
        GF256_EXP[i] = GF256_EXP[i - 255]

_init_gf256()

def gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return GF256_EXP[GF256_LOG[x] + GF256_LOG[y]]

def rs_generator_poly(ec_count: int) -> List[int]:
    g = [1]
    for i in range(ec_count):
        g = [gf_mul(p, GF256_EXP[i]) for p in g] + [0]
        for j in range(len(g) - 1):
            g[j] ^= g[j] # Multiply (x - a^i)
    return g


# QR Code Version Specifications (Version 1 to 5, Level L/M)
# Each tuple: (version, size, total_data_bytes, ec_bytes_per_block, num_blocks, align_coords)
QR_SPECS = {
    # Version: (size, ec_bytes, total_codewords)
    1: (21, 10, 26),
    2: (25, 16, 44),
    3: (29, 26, 70),
    4: (33, 36, 100),
    5: (37, 48, 134),
    6: (41, 64, 172),
}

ALIGNMENT_COORDS = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}


def _get_rs_ecc(data: bytes, ecc_count: int) -> bytes:
    """Computes Reed-Solomon error correction codewords for QR code data."""
    poly = [1]
    for i in range(ecc_count):
        factor = GF256_EXP[i]
        new_poly = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            new_poly[j] ^= gf_mul(coeff, factor)
            new_poly[j + 1] ^= coeff
        poly = new_poly

    # Polynomial division
    remainder = list(data) + [0] * ecc_count
    for i in range(len(data)):
        lead = remainder[i]
        if lead != 0:
            for j, coeff in enumerate(poly):
                remainder[i + j] ^= gf_mul(coeff, lead)

    return bytes(remainder[-ecc_count:])


class QRCode:
    """Encodes text into a QR Code matrix and renders terminal ANSI/Unicode strings."""

    def __init__(self, text: str):
        self.text = text
        self.data_bytes = text.encode('utf-8')
        self.version = self._select_version()
        self.size, self.ec_bytes, self.total_bytes = QR_SPECS[self.version]
        self.matrix: List[List[int]] = [[-1] * self.size for _ in range(self.size)]
        self.reserved: List[List[bool]] = [[False] * self.size for _ in range(self.size)]
        self._build()

    def _select_version(self) -> int:
        needed_bytes = len(self.data_bytes) + 3 # mode indicator (4 bits) + length (8/16 bits) + terminator
        for ver, (size, ec_b, tot_b) in QR_SPECS.items():
            cap = tot_b - ec_b
            if needed_bytes <= cap:
                return ver
        return 6

    def _build(self):
        self._place_finders()
        self._place_alignment()
        self._place_timing()
        self._place_format_reserved()
        self._place_data()
        self._apply_mask()
        self._place_format_info(mask_pattern=0)

    def _set_module(self, r: int, c: int, val: int, is_reserved: bool = True):
        if 0 <= r < self.size and 0 <= c < self.size:
            self.matrix[r][c] = val
            if is_reserved:
                self.reserved[r][c] = True

    def _place_finders(self):
        for top, left in [(0, 0), (0, self.size - 7), (self.size - 7, 0)]:
            for r in range(-1, 8):
                for c in range(-1, 8):
                    qr_r, qr_c = top + r, left + c
                    if 0 <= qr_r < self.size and 0 <= qr_c < self.size:
                        if 0 <= r <= 6 and 0 <= c <= 6:
                            if r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4):
                                self._set_module(qr_r, qr_c, 1)
                            else:
                                self._set_module(qr_r, qr_c, 0)
                        else:
                            self._set_module(qr_r, qr_c, 0)

    def _place_alignment(self):
        if self.version < 2:
            return
        coords = ALIGNMENT_COORDS.get(self.version, [])
        for r in coords:
            for c in coords:
                if self.reserved[r][c]:
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        if abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0):
                            self._set_module(r + dr, c + dc, 1)
                        else:
                            self._set_module(r + dr, c + dc, 0)

    def _place_timing(self):
        for i in range(8, self.size - 8):
            val = 1 if i % 2 == 0 else 0
            if not self.reserved[6][i]:
                self._set_module(6, i, val)
            if not self.reserved[i][6]:
                self._set_module(i, 6, val)

    def _place_format_reserved(self):
        # Dark module
        self._set_module(self.size - 8, 8, 1)
        for i in range(9):
            if not self.reserved[8][i]:
                self._set_module(8, i, 0)
            if not self.reserved[i][8]:
                self._set_module(i, 8, 0)
        for i in range(self.size - 8, self.size):
            if not self.reserved[8][i]:
                self._set_module(8, i, 0)
            if not self.reserved[i][8]:
                self._set_module(i, 8, 0)

    def _place_data(self):
        # Build bit stream: Mode Byte (0100) + Count + Data + Terminator
        bit_str = "0100"
        bit_str += format(len(self.data_bytes), '08b')
        for b in self.data_bytes:
            bit_str += format(b, '08b')

        data_capacity_bits = (self.total_bytes - self.ec_bytes) * 8
        bit_str += "0000"
        bit_str = bit_str[:data_capacity_bits]
        while len(bit_str) % 8 != 0:
            bit_str += "0"

        pad_bytes = ["11101100", "00010001"]
        pad_idx = 0
        while len(bit_str) < data_capacity_bits:
            bit_str += pad_bytes[pad_idx % 2]
            pad_idx += 1

        # Convert to byte array
        raw_data = bytes(int(bit_str[i:i+8], 2) for i in range(0, len(bit_str), 8))
        ecc = _get_rs_ecc(raw_data, self.ec_bytes)
        final_bytes = raw_data + ecc

        final_bits = "".join(format(b, '08b') for b in final_bytes)
        bit_idx = 0
        total_bits = len(final_bits)

        # Place bits in standard right-to-left zigzag pattern
        col = self.size - 1
        up = True
        while col > 0:
            if col == 6: # Skip vertical timing line
                col -= 1
            rows = range(self.size - 1, -1, -1) if up else range(self.size)
            for r in rows:
                for c in (col, col - 1):
                    if not self.reserved[r][c]:
                        bit_val = int(final_bits[bit_idx]) if bit_idx < total_bits else 0
                        self.matrix[r][c] = bit_val
                        bit_idx += 1
            up = not up
            col -= 2

    def _apply_mask(self):
        # Mask pattern 0: (row + col) % 2 == 0
        for r in range(self.size):
            for c in range(self.size):
                if not self.reserved[r][c]:
                    if (r + c) % 2 == 0:
                        self.matrix[r][c] ^= 1

    def _place_format_info(self, mask_pattern: int = 0):
        # ECC Level L (01) + Mask 0 (000) = 01000 -> Format string with BCH (15, 5)
        # For Level L + Mask 0: format bits = 0x77C4 (0b111011111000100)
        fmt = 0b111011111000100
        fmt_bits = format(fmt, '015b')

        # Top-left horizontal & vertical
        for i in range(6):
            self.matrix[8][i] = int(fmt_bits[i])
        self.matrix[8][7] = int(fmt_bits[6])
        self.matrix[8][8] = int(fmt_bits[7])
        self.matrix[7][8] = int(fmt_bits[8])
        for i in range(6):
            self.matrix[5 - i][8] = int(fmt_bits[9 + i])

        # Top-right and bottom-left
        for i in range(8):
            self.matrix[8][self.size - 1 - i] = int(fmt_bits[i])
        for i in range(7):
            self.matrix[self.size - 7 + i][8] = int(fmt_bits[8 + i])

    def to_terminal(self, quiet_zone: int = 2) -> str:
        """Renders QR code as high-contrast terminal string using Unicode half-block characters."""
        lines = []
        border_size = self.size + (quiet_zone * 2)

        # Full grid with quiet zone
        grid = [[0] * border_size for _ in range(border_size)]
        for r in range(self.size):
            for c in range(self.size):
                grid[r + quiet_zone][c + quiet_zone] = max(0, self.matrix[r][c])

        # Render 2 rows per line using ▀ (upper) and ▄ (lower) blocks
        for r in range(0, border_size, 2):
            line = []
            for c in range(border_size):
                top = grid[r][c]
                bot = grid[r + 1][c] if (r + 1 < border_size) else 0

                # In inverted terminal: 1 (black/dark module) is foreground, 0 is white/light background
                if top == 1 and bot == 1:
                    line.append(" ")
                elif top == 1 and bot == 0:
                    line.append("▄")
                elif top == 0 and bot == 1:
                    line.append("▀")
                else:
                    line.append("█")
            lines.append("".join(line))

        return "\n".join(lines)


def print_qr_code(text: str, title: str = "") -> str:
    """Helper to generate and return a formatted terminal QR banner."""
    qr = QRCode(text)
    banner = []
    if title:
        banner.append(f"\n  {title}")
    banner.append(qr.to_terminal(quiet_zone=1))
    return "\n".join(banner)
