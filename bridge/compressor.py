"""
Caveman Ultra Output Compressor for Prompt Bridge.
Transforms raw terminal session logs and agent output into:
1. Raw Mode: Clean ANSI-stripped, formatted terminal output.
2. Caveman Ultra Mode: Ultra-concise, telegraphic action summary (thoughts, tools, errors, concise answers).
"""

import re
from typing import List, Dict, Any


ANSI_REGEX = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\([A-Za-z0-9]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)')
CONTROL_CHARS_REGEX = re.compile(r'[\r\x00-\x08\x0b\x0c\x0e-\x1f]')
BORDER_REGEX = re.compile(r'^[─━═\-_=~]{3,}$')
SPINNER_CHARS = set("⣟⣯⣷⣾⣽⣻⢿⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏◴◵◶◷")


def clean_ansi(text: str) -> str:
    """Strips ANSI escapes and non-printable terminal control codes."""
    if not text:
        return ""
    text = ANSI_REGEX.sub("", text)
    text = CONTROL_CHARS_REGEX.sub("", text)
    return text


def compress_caveman_ultra(raw_text: str, max_items: int = 15) -> str:
    """
    Compresses raw agent terminal output into Caveman Ultra format.
    Preserves exact tools, thoughts, errors, and key response sentences while eliminating filler.
    """
    cleaned = clean_ansi(raw_text)
    raw_lines = [l.strip() for l in cleaned.splitlines()]
    
    # Filter out empty lines, decorative borders, and CLI footers
    filtered = []
    for line in raw_lines:
        if not line:
            continue
        if BORDER_REGEX.match(line):
            continue
        if "esc to cancel" in line or "ctrl+o to expand" in line or "python3 main.py running" in line:
            continue
        if any(c in line for c in SPINNER_CHARS) and "Running command" in line:
            continue
        if line.startswith("Tip: Use /help") or line == ">":
            continue
        filtered.append(line)

    if not filtered:
        return "Terminal ready. No active output."

    events = []
    in_code_block = False

    for line in filtered:
        # Code fence tracking
        if line.startswith("```"):
            in_code_block = not in_code_block
            events.append(line)
            continue
        if in_code_block:
            events.append(line)
            continue

        # 1. Thought block
        if "▸ Thought for" in line or line.startswith("▸ Thought"):
            match = re.search(r'Thought for ([\d\w\.]+)', line)
            dur = match.group(1) if match else "awhile"
            events.append(f"🧠 Thinking ({dur})")
            continue

        # 2. Tool Calls
        if line.startswith("● Bash(") or line.startswith("○ Bash("):
            cmd = line[line.find("(")+1 : line.rfind(")")]
            events.append(f"⚡ Bash: `{cmd}`" if cmd else "⚡ Executed command")
            continue
        if line.startswith("● Edit(") or line.startswith("○ Edit("):
            target = line[line.find("(")+1 : line.rfind(")")]
            short_target = target.split("/")[-1] if "/" in target else target
            events.append(f"📝 Edit: `{short_target}`")
            continue
        if line.startswith("● Read(") or line.startswith("○ Read(") or line.startswith("● View(") or line.startswith("○ View("):
            target = line[line.find("(")+1 : line.rfind(")")]
            short_target = target.split("/")[-1] if "/" in target else target
            events.append(f"📖 Read: `{short_target}`")
            continue

        # 3. Errors and failures
        if "Error:" in line or "Traceback (" in line or "Exception" in line or "FAILED" in line:
            events.append(f"❌ {line}")
            continue

        # 4. User prompts
        if line.startswith("> "):
            prompt_text = line[2:].strip()
            if prompt_text:
                events.append(f"👤 Prompt: \"{prompt_text[:60]}{'...' if len(prompt_text) > 60 else ''}\"")
            continue

        # 5. Success markers
        if "OK" in line or "✓" in line or "passed" in line.lower():
            if len(line) < 80:
                events.append(f"✓ {line}")
                continue

        # 6. Regular prose / response text (apply Caveman compression)
        compressed_line = _caveman_compress_line(line)
        if compressed_line:
            events.append(compressed_line)

    # De-duplicate consecutive identical items
    deduped = []
    for item in events:
        if not deduped or deduped[-1] != item:
            deduped.append(item)

    # Take recent items
    recent = deduped[-max_items:]
    return "\n".join(recent)


def _caveman_compress_line(line: str) -> str:
    """Applies Caveman word-level compression to non-code prose."""
    if len(line) < 3:
        return ""
    
    # Drop pleasantries & filler
    fillers = [
        r"\b(basically|actually|simply|just|certainly|sure|of course|happy to|please note that)\b",
        r"\b(the following changes were made|as you can see|in order to|i have)\b",
        r"\b(a|an|the)\b",
    ]
    compressed = line
    for pat in fillers:
        compressed = re.sub(pat, "", compressed, flags=re.IGNORECASE)

    # Clean up double spaces
    compressed = re.sub(r'\s+', ' ', compressed).strip()
    return compressed


def format_raw_tail(raw_text: str, lines: int = 35) -> str:
    """Formats raw terminal output for clean display on mobile."""
    cleaned = clean_ansi(raw_text)
    all_lines = cleaned.splitlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return "\n".join(tail)
