"""
Terminal output formatter for Prompt Bridge.
Strips ANSI control codes and formats raw terminal tail lines.
"""

import re

ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\([A-Za-z0-9]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)')
CONTROL_CHARS_REGEX = re.compile(r'[\r\x00-\x08\x0b\x0c\x0e-\x1f]')


def clean_ansi(text: str) -> str:
    """Strips ANSI escapes and non-printable terminal control codes."""
    if not text:
        return ""
    text = ANSI_REGEX.sub("", text)
    text = CONTROL_CHARS_REGEX.sub("", text)
    return text


def format_raw_tail(raw_text: str, lines: int = 35) -> str:
    """Formats raw terminal output for clean display on mobile."""
    cleaned = clean_ansi(raw_text)
    all_lines = cleaned.splitlines()
    while all_lines and not all_lines[-1].strip():
        all_lines.pop()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return "\n".join(tail)
