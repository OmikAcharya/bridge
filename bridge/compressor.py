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
SPINNERS = set("⣟⣯⣷⣾⣽⣻⢿⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⡿◴◵◶◷")


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
    - Current State & Active In-Flight Step
    - Compact summary of recent tool actions (deduplicated)
    - Shortest decisive response sentence
    """
    cleaned = clean_ansi(raw_text)
    raw_lines = [l.strip() for l in cleaned.splitlines() if l.strip()]

    # Filter out noisy terminal chrome, status bars, background logs, and borders
    filtered = []
    for l in raw_lines:
        if BORDER_REGEX.match(l):
            continue
        if re.search(r'esc to (cancel|interrupt)', l, re.IGNORECASE):
            continue
        if re.search(r'● \[\d\d:\d\d:\d\d\] .* running', l):
            continue
        if re.search(r'\b(Gemini|Claude)\b.*(/tasks|task\(s\))', l):
            continue
        if l.startswith("└ Tip:") or l.startswith("Tip: Use /"):
            continue
        if l == ">":
            continue
        # Strip expansion hints
        l = l.replace("(ctrl+o to expand)", "").strip()
        filtered.append(l)

    if not filtered:
        return "● READY\nSession idle."

    # 1. Determine active busy state from the tail
    is_busy = False
    active_step = ""

    tail_scan = filtered[-4:] if len(filtered) >= 4 else filtered
    for l in reversed(tail_scan):
        if any(c in l for c in SPINNERS) or "running command" in l.lower() or "thinking..." in l.lower():
            is_busy = True
            break
        if l.startswith("○ Bash("):
            is_busy = True
            cmd = l[l.find("(") + 1 : l.rfind(")")].strip()
            active_step = f"Executing `{cmd.split()[0]}`" if cmd else "Executing command"
            break
        if l.startswith("○ Edit("):
            is_busy = True
            f = l[l.find("(") + 1 : l.rfind(")")].split("/")[-1].strip()
            active_step = f"Editing `{f}`" if f else "Editing file"
            break

    # 2. Extract recent tools & thoughts
    edits = []
    bash_cmds = []
    last_thought = ""
    response_lines = []
    in_user_prompt = False

    for l in filtered:
        if l.startswith("> "):
            in_user_prompt = True
            response_lines = []
            continue

        if "▸ Thought for" in l or "▸ Thought" in l:
            m = re.search(r'Thought for ([\d\w\.]+)', l)
            last_thought = f"Thought {m.group(1)}" if m else "Thinking"
            continue

        # Skip thought paragraphs indented under thinking markers
        if l.startswith("Thinking about") or l.startswith("Checking recent"):
            continue

        if l.startswith("● Bash(") or l.startswith("○ Bash("):
            cmd = l[l.find("(") + 1 : l.rfind(")")].strip()
            if cmd:
                base_cmd = cmd.split()[0]
                if base_cmd not in bash_cmds:
                    bash_cmds.append(base_cmd)
            continue

        if l.startswith("● Edit(") or l.startswith("○ Edit("):
            f = l[l.find("(") + 1 : l.rfind(")")].split("/")[-1].strip()
            if f and f not in edits:
                edits.append(f)
            continue

        if l.startswith("● Read(") or l.startswith("○ Read(") or l.startswith("● View("):
            continue

        # Potential response lines
        if not l.startswith("●") and not l.startswith("○") and not l.startswith("▸") and not l.startswith("└") and not any(c in l for c in SPINNERS):
            cl = _caveman_compress_line(l)
            if cl and len(cl) > 3:
                response_lines.append(cl)

    output_lines = []

    # 1. State Line
    if is_busy:
        step_str = f" · {active_step}" if active_step else (f" · {last_thought}" if last_thought else " · Processing")
        output_lines.append(f"● BUSY{step_str}")
    else:
        output_lines.append("● READY")

    # 2. Key Actions (Only if non-empty)
    action_parts = []
    if edits:
        action_parts.append(f"Edits: {', '.join(edits[-3:])}")
    if bash_cmds:
        action_parts.append(f"Ran: {', '.join(bash_cmds[-3:])}")
    if action_parts:
        output_lines.append(" · ".join(action_parts))

    # 3. Decisive Response Line (Concise and clean)
    if response_lines:
        clean_resp = " ".join(response_lines[-2:])
        if len(clean_resp) > 140:
            clean_resp = clean_resp[:137] + "..."
        output_lines.append(f"“{clean_resp}”")

    return "\n".join(output_lines) if output_lines else "● READY\nSession idle."


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
