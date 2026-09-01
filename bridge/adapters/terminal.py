"""
Apple Terminal Adapter.
Delivers input directly to a specific Terminal.app tab or TTY session.
Supports both background direct execution (with Enter) and non-executing paste.
"""

import re
import subprocess
from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult


def sanitize_tty(tty: str) -> str:
    """Sanitizes TTY device path to alphanumeric and safe path characters."""
    if not tty or not re.match(r'^[a-zA-Z0-9_/.-]+$', tty):
        return ""
    return tty


def escape_for_applescript(text: str) -> str:
    """Escapes string characters for safe embedding inside an AppleScript literal."""
    # Strip null bytes and normalize unicode paragraph/line separators
    sanitized = text.replace('\0', '').replace('\u2028', '\n').replace('\u2029', '\n')
    escaped = sanitized.replace('\\', '\\\\').replace('"', '\\"').replace('\r\n', '\n').replace('\r', '\n')
    return escaped


class AppleTerminalAdapter(TerminalAdapter):
    """Adapter for macOS Terminal.app."""

    @property
    def name(self) -> str:
        return "AppleTerminalAdapter"

    def can_handle(self, target: Target) -> bool:
        if target.application == "Terminal" or target.tty.startswith("/dev/tty"):
            return True
        return False

    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        if not text and action not in ("interrupt", "raw_enter"):
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="Prompt text is empty."
            )

        tty = sanitize_tty(target.tty)
        win_idx = int(target.win_idx) if target.win_idx and str(target.win_idx).isdigit() else 0
        tab_idx = int(target.tab_idx) if target.tab_idx and str(target.tab_idx).isdigit() else 0
        tab_finder = f'''
        set foundTab to missing value
        if {win_idx} > 0 and {tab_idx} > 0 then
            try
                set candTab to tab {tab_idx} of window {win_idx}
                if "{tty}" is "" or tty of candTab is "{tty}" then
                    set foundTab to candTab
                end if
            end try
        end if
        if foundTab is missing value and "{tty}" is not "" then
            repeat with w in windows
                repeat with t in tabs of w
                    if tty of t is "{tty}" then
                        set foundTab to t
                        exit repeat
                    end if
                end repeat
                if foundTab is not missing value then exit repeat
            end repeat
        end if
        '''

        # Check action mode
        if action == "interrupt" or text == "\x03":
            action_desc = "Interrupt (Ctrl+C)"
            script = f'''
            tell application "Terminal"
                {tab_finder}
                if foundTab is not missing value then
                    do script (ASCII character 3) in foundTab
                    return "OK"
                else
                    return "ERROR: Terminal session not found"
                end if
            end tell
            '''
        elif action == "raw_enter" or text == "\n":
            action_desc = "Return (Enter)"
            script = f'''
            tell application "Terminal"
                {tab_finder}
                if foundTab is not missing value then
                    do script "" in foundTab
                    return "OK"
                else
                    return "ERROR: Terminal session not found"
                end if
            end tell
            '''
        elif action in ("paste", "no_enter"):
            # Non-executing paste: put text on clipboard and paste via Cmd+V without sending Return
            action_desc = "Paste (No Enter)"
            try:
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(text.encode("utf-8"))
            except Exception as e:
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error=f"Failed to copy to clipboard: {e}"
                )

            script = f'''
            tell application "Terminal"
                {tab_finder}
                if foundTab is not missing value then
                    activate
                    tell application "System Events"
                        keystroke "v" using command down
                    end tell
                    return "OK"
                else
                    return "ERROR: Terminal tab not found"
                end if
            end tell
            '''
        else:
            # Direct background execution with Enter (Default)
            action_desc = "Prompt (Execute)"
            escaped_text = escape_for_applescript(text)
            script = f'''
            tell application "Terminal"
                {tab_finder}
                if foundTab is not missing value then
                    do script "{escaped_text}" in foundTab
                    return "OK"
                else
                    return "ERROR: Terminal tab or session not found"
                end if
            end tell
            '''

        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5.0
            )

            stdout = res.stdout.strip()
            stderr = res.stderr.strip()

            if res.returncode == 0 and stdout == "OK":
                return DeliveryResult(
                    success=True,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    message=f"Delivered to {target.name} ({target.tty or 'tab'})"
                )
            else:
                err_msg = stderr or stdout or "AppleScript failed to deliver prompt."
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error=err_msg
                )

        except subprocess.TimeoutExpired:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="AppleScript timed out while sending prompt."
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error=f"Unexpected error: {str(e)}"
            )

    def get_history(self, target: Target, lines: int = 50) -> str:
        """Retrieves recent terminal output history from the target tab."""
        tty = sanitize_tty(target.tty)
        win_idx = int(target.win_idx) if target.win_idx and str(target.win_idx).isdigit() else 0
        tab_idx = int(target.tab_idx) if target.tab_idx and str(target.tab_idx).isdigit() else 0
        tab_finder = f'''
        set foundTab to missing value
        if {win_idx} > 0 and {tab_idx} > 0 then
            try
                set candTab to tab {tab_idx} of window {win_idx}
                if "{tty}" is "" or tty of candTab is "{tty}" then
                    set foundTab to candTab
                end if
            end try
        end if
        if foundTab is missing value and "{tty}" is not "" then
            repeat with w in windows
                repeat with t in tabs of w
                    if tty of t is "{tty}" then
                        set foundTab to t
                        exit repeat
                    end if
                end repeat
                if foundTab is not missing value then exit repeat
            end repeat
        end if
        '''
        script = f'''
        tell application "Terminal"
            {tab_finder}
            if foundTab is not missing value then
                return history of foundTab
            else
                return ""
            end if
        end tell
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0 and res.stdout:
                raw_lines = res.stdout.splitlines()
                return "\n".join(raw_lines[-lines:])
        except Exception:
            pass
        return ""

