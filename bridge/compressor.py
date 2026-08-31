"""
Caveman Ultra Output Compressor for Prompt Bridge.
Transforms raw terminal session logs and agent output into:
1. Raw Mode: Clean ANSI-stripped, formatted terminal output.
2. Caveman Ultra Mode: Dense, structured 3-line synthesis (State, Actions, Last Message).
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


def compress_caveman_ultra(raw_text: str, max_items: int = 4) -> str:
    """
    Synthesizes raw agent terminal output into high-density Caveman Ultra format.
    Extracts:
    - Current State & Active Step
    - Compact summary of recent tool actions (deduplicated)
    - Shortest decisive response sentence
    """
    cleaned = clean_ansi(raw_text)
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]

    # Filter out noisy borders, prompts, and CLI footers
    filtered = []
    for l in lines:
        if BORDER_REGEX.match(l):
            continue
        if "esc to cancel" in l or "ctrl+o to expand" in l or "running command..." in l.lower():
            continue
        if l.startswith("Tip: Use /help") or l == ">":
            continue
        filtered.append(l)

    if not filtered:
        return "Terminal idle. Ready for prompt."

    # Identify state
    is_busy = False
    if any("running" in l.lower() or "thought for" in l.lower() or "⣻" in l or "⣟" in l for l in filtered[-5:]):
        is_busy = True

    edits = []
    bash_cmds = []
    last_thought = ""
    response_lines = []
    in_response = False

    for l in filtered:
        if l.startswith("> "):
            in_response = True
            response_lines = []
            continue

        if "▸ Thought for" in l or "▸ Thought" in l:
            m = re.search(r'Thought for ([\d\w\.]+)', l)
            last_thought = f"Thought {m.group(1)}" if m else "Thinking"
            continue

        if l.startswith("● Bash(") or l.startswith("○ Bash("):
            cmd = l[l.find("(")+1 : l.rfind(")")]
            if cmd and cmd not in bash_cmds:
                bash_cmds.append(cmd)
            continue

        if l.startswith("● Edit(") or l.startswith("○ Edit("):
            f = l[l.find("(")+1 : l.rfind(")")].split("/")[-1]
            if f and f not in edits:
                edits.append(f)
            continue

        if l.startswith("● Read(") or l.startswith("○ Read(") or l.startswith("● View("):
            continue

        if in_response:
            if not l.startswith("●") and not l.startswith("○") and not l.startswith("▸"):
                cl = _caveman_compress_line(l)
                if cl and len(cl) > 2:
                    response_lines.append(cl)

    output_lines = []

    # 1. State / Current Action
    if is_busy:
        step = ""
        if bash_cmds:
            step = f" · Executing `{bash_cmds[-1][:32]}`"
        elif edits:
            step = f" · Editing `{edits[-1]}`"
        elif last_thought:
            step = f" · {last_thought}"
        output_lines.append(f"● BUSY{step}")
    else:
        output_lines.append("● READY")

    # 2. Key Actions (Combined into one concise line)
    action_parts = []
    if edits:
        action_parts.append(f"Edits: {', '.join(edits[-3:])}")
    if bash_cmds:
        short_cmds = [c.split()[0] for c in bash_cmds[-2:]]
        action_parts.append(f"Ran: {', '.join(short_cmds)}")
    if action_parts:
        output_lines.append(" · ".join(action_parts))

    # 3. Last Response snippet (1-2 lines max)
    if response_lines:
        clean_resp = " ".join(response_lines[-2:])
        if len(clean_resp) > 130:
            clean_resp = clean_resp[:127] + "..."
        output_lines.append(f"“{clean_resp}”")

    return "\n".join(output_lines) if output_lines else "Session ready."


def _caveman_compress_line(line: str) -> str:
    """Applies Caveman word-level compression to non-code prose."""
    t = re.sub(r'^[•\-\*]\s*', '', line)
    t = re.sub(r'#+\s*', '', t)
    
    # Drop pleasantries & filler
    fillers = [
        r"\b(basically|actually|simply|just|certainly|sure|of course|happy to|please note that)\b",
        r"\b(the following changes were made|as you can see|in order to|i have|we have)\b",
        r"\b(a|an|the)\b",
    ]
    for pat in fillers:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)

    t = re.sub(r'\s+', ' ', t).strip()
    return t


def format_raw_tail(raw_text: str, lines: int = 35) -> str:
    """Formats raw terminal output for clean display on mobile."""
    cleaned = clean_ansi(raw_text)
    all_lines = cleaned.splitlines()
    tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
    return "\n".join(tail)
