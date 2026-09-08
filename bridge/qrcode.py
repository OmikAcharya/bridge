"""
Pure Python QR Code Generator (Zero external dependencies).
Compliant with ISO/IEC 18004 specification.
Renders high-contrast terminal QR codes using Unicode half-block characters.
"""

from typing import List, Tuple, Dict, Any


# 1. Galois Field (GF(256)) Math Tables (Primitive polynomial: x^8 + x^4 + x^3 + x^2 + 1 = 0x11D)
GF256_EXP = [0] * 512
GF256_LOG = [0] * 256

def _init_gf256():
    x = 1
    for i in range(255):
        GF256_EXP[i] = x
        GF256_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        GF256_EXP[i] = GF256_EXP[i - 255]

_init_gf256()


def gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return GF256_EXP[GF256_LOG[x] + GF256_LOG[y]]


def rs_gen_poly(n: int) -> List[int]:
    """Generates Reed-Solomon generator polynomial g(x) = (x-a^0)(x-a^1)...(x-a^(n-1))."""
    g = [1]
    for i in range(n):
        root = GF256_EXP[i]
        new_g = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            new_g[j] ^= c
            new_g[j + 1] ^= gf_mul(c, root)
        g = new_g
    return g


def rs_encode(data: bytes, ecc_len: int) -> bytes:
    """Computes Reed-Solomon error correction codewords via polynomial division."""
    gen = rs_gen_poly(ecc_len)
    rem = list(data) + [0] * ecc_len
    for i in range(len(data)):
        lead = rem[i]
        if lead != 0:
            for j, c in enumerate(gen):
                rem[i + j] ^= gf_mul(c, lead)
    return bytes(rem[-ecc_len:])


# ISO/IEC 18004 Table 7 (Level L Specifications)
# Format: version: (size, total_codewords, ec_per_block, [(num_blocks, data_per_block)])
QR_SPECS_L = {
    1: (21, 26, 7, [(1, 19)]),
    2: (25, 44, 10, [(1, 34)]),
    3: (29, 70, 15, [(1, 55)]),
    4: (33, 100, 20, [(1, 80)]),
    5: (37, 134, 26, [(1, 108)]),
    6: (41, 172, 18, [(2, 68)]),
}

# ISO/IEC 18004 Table E.1 (Alignment Pattern Coordinates)
ALIGNMENT_COORDS = {
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}

# Format Information: Level L (01) + Mask 0 (000) = 0x77C4 (ISO Table C.1)
FORMAT_INFO_L_MASK0 = 0x77C4


class QRCode:
    """Encodes text into a standards-compliant QR Code matrix and renders terminal strings."""

    def __init__(self, text: str):
        self.text = text
        self.data_bytes = text.encode('utf-8')
        self.version = self._select_version()
        self.size, self.total_codewords, self.ec_len, self.block_spec = QR_SPECS_L[self.version]
        self.tot_data_bytes = sum(nb * d for nb, d in self.block_spec)
        self.matrix: List[List[int]] = [[0] * self.size for _ in range(self.size)]
        self.reserved: List[List[bool]] = [[False] * self.size for _ in range(self.size)]
        self._build()

    def _select_version(self) -> int:
        needed_bytes = len(self.data_bytes) + 3  # Mode (4b) + Length (8b) + Terminator (4b)
        for v in sorted(QR_SPECS_L.keys()):
            _, _, _, block_spec = QR_SPECS_L[v]
            cap = sum(nb * d for nb, d in block_spec)
            if needed_bytes <= cap:
                return v
        return 6

    def _set_module(self, r: int, c: int, val: int, is_reserved: bool = True):
        if 0 <= r < self.size and 0 <= c < self.size:
            self.matrix[r][c] = val
            if is_reserved:
                self.reserved[r][c] = True

    def _build(self):
        self._place_finders()
        self._place_alignment()
        self._place_timing()
        self._place_dark_module()
        self._reserve_format_info()
        self._place_data()
        self._apply_mask()
        self._place_format_info()

    def _place_finders(self):
        # 3 Finder patterns with 1-module white separators
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
                # Skip if overlapping any of the 3 finder patterns + separators
                if (r < 9 and c < 9) or (r < 9 and c >= self.size - 8) or (r >= self.size - 8 and c < 9):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                        self._set_module(r + dr, c + dc, val)

    def _place_timing(self):
        for i in range(8, self.size - 8):
            val = 1 if i % 2 == 0 else 0
            if not self.reserved[6][i]:
                self._set_module(6, i, val)
            if not self.reserved[i][6]:
                self._set_module(i, 6, val)

    def _place_dark_module(self):
        # ISO 18004 section 8.8.2: coordinate (4V + 9, 8) in 1-based = (size - 8, 8) in 0-based
        self._set_module(self.size - 8, 8, 1)

    def _get_format_coords(self) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
        # Top-left strip around finder: b0 at (0,8) up to b14 at (8,0)
        coords_tl = [
            (0, 8), (1, 8), (2, 8), (3, 8), (4, 8), (5, 8), (7, 8), (8, 8),
            (8, 7), (8, 5), (8, 4), (8, 3), (8, 2), (8, 1), (8, 0)
        ]
        # Redundant split strip: b0..b7 on top-right row 8, b8..b14 on bottom-left col 8
        coords_split = [
            (8, self.size - 1), (8, self.size - 2), (8, self.size - 3), (8, self.size - 4),
            (8, self.size - 5), (8, self.size - 6), (8, self.size - 7), (8, self.size - 8),
            (self.size - 7, 8), (self.size - 6, 8), (self.size - 5, 8), (self.size - 4, 8),
            (self.size - 3, 8), (self.size - 2, 8), (self.size - 1, 8)
        ]
        return coords_tl, coords_split

    def _reserve_format_info(self):
        coords_tl, coords_split = self._get_format_coords()
        for r, c in coords_tl + coords_split:
            self.reserved[r][c] = True

    def _place_data(self):
        # Build bitstream: Mode (0100) + Character Count (8 bits for v1-9) + Data + Terminator
        bit_str = "0100" + format(len(self.data_bytes), '08b')
        for b in self.data_bytes:
            bit_str += format(b, '08b')
        bit_str += "0000"
        max_data_bits = self.tot_data_bytes * 8
        bit_str = bit_str[:max_data_bits]
        while len(bit_str) % 8 != 0:
            bit_str += "0"

        # Byte padding with alternating standard pattern 0xEC and 0x11
        pad_bytes = ["11101100", "00010001"]
        p_idx = 0
        while len(bit_str) < max_data_bits:
            bit_str += pad_bytes[p_idx % 2]
            p_idx += 1

        raw_data = bytes(int(bit_str[i:i+8], 2) for i in range(0, len(bit_str), 8))

        # Split into blocks and compute Reed-Solomon error correction codewords
        blocks_data = []
        blocks_ec = []
        off = 0
        for nb, dlen in self.block_spec:
            for _ in range(nb):
                blk = raw_data[off:off+dlen]
                off += dlen
                blocks_data.append(blk)
                blocks_ec.append(rs_encode(blk, self.ec_len))

        # Interleave data codewords
        interleaved = bytearray()
        max_dlen = max(len(b) for b in blocks_data)
        for i in range(max_dlen):
            for b in blocks_data:
                if i < len(b):
                    interleaved.append(b[i])

        # Interleave EC codewords
        for i in range(self.ec_len):
            for ec in blocks_ec:
                interleaved.append(ec[i])

        final_bits = "".join(format(b, '08b') for b in interleaved)

        # Place bits in standard right-to-left 2-column zigzag pattern
        col = self.size - 1
        up = True
        bit_idx = 0
        while col > 0:
            if col == 6:  # Skip vertical timing line
                col = 5
            rows = range(self.size - 1, -1, -1) if up else range(self.size)
            for r in rows:
                for c in (col, col - 1):
                    if not self.reserved[r][c]:
                        b_val = int(final_bits[bit_idx]) if bit_idx < len(final_bits) else 0
                        self.matrix[r][c] = b_val
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

    def _place_format_info(self):
        coords_tl, coords_split = self._get_format_coords()
        fmt = FORMAT_INFO_L_MASK0
        for i in range(15):
            bit = (fmt >> i) & 1
            r, c = coords_tl[i]
            self.matrix[r][c] = bit
            r2, c2 = coords_split[i]
            self.matrix[r2][c2] = bit

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

                # On dark terminal background: 1 (dark module) is background/space, 0 (light) is foreground/full block
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
    banner.append(qr.to_terminal(quiet_zone=2))
    return "\n".join(banner)
