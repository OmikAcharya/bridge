"""
Apple Terminal Adapter.
Delivers input directly to a specific Terminal.app tab or TTY session without stealing GUI focus.
"""

import subprocess
from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult


def escape_for_applescript(text: str) -> str:
    """Escapes string characters for safe embedding inside an AppleScript literal."""
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace('\r\n', '\n').replace('\r', '\n')
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

        tty = target.tty
        win_idx = target.win_idx
        tab_idx = target.tab_idx

        # Prepare script command based on action
        if action == "interrupt" or text == "\x03":
            do_command = "do script (ASCII character 3) in foundTab"
            action_desc = "Interrupt (Ctrl+C)"
        elif action == "raw_enter" or text == "\n":
            do_command = 'do script "" in foundTab'
            action_desc = "Return (Enter)"
        else:
            escaped_text = escape_for_applescript(text)
            do_command = f'do script "{escaped_text}" in foundTab'
            action_desc = "Prompt"

        script = f'''
        tell application "Terminal"
            set foundTab to missing value
            
            -- Method 1: Find by exact TTY
            if "{tty}" is not "" then
                repeat with w in windows
                    repeat with t in tabs of w
                        if tty of t is "{tty}" then
                            set foundTab to t
                            exit repeat
                        end if
                    end repeat
                    if foundTab is not missing value then
                        exit repeat
                    end if
                end repeat
            end if
            
            -- Method 2: Fallback to window/tab index if TTY not found
            if foundTab is missing value and {win_idx if win_idx else 0} > 0 and {tab_idx if tab_idx else 0} > 0 then
                try
                    set foundTab to tab {tab_idx} of window {win_idx}
                end try
            end if
            
            if foundTab is not missing value then
                {do_command}
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
                    message=f"{action_desc} delivered to {target.name} ({target.tty})"
                )
            else:
                err_msg = stderr or stdout or "Unknown error delivering to Terminal tab"
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error=f"Terminal delivery failed: {err_msg}"
                )

        except subprocess.TimeoutExpired:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="Timed out attempting to send prompt to Terminal.app"
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error=f"AppleTerminalAdapter exception: {str(e)}"
            )
