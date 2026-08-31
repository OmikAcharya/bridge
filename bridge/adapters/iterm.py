"""
iTerm2 Adapter.
Delivers input directly to a specific iTerm2 session or TTY without stealing GUI focus.
"""

import subprocess
from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult
from bridge.adapters.terminal import escape_for_applescript


class ITermAdapter(TerminalAdapter):
    """Adapter for iTerm2 terminal emulator."""

    @property
    def name(self) -> str:
        return "ITermAdapter"

    def can_handle(self, target: Target) -> bool:
        return target.application == "iTerm"

    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        if not text:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="Prompt text is empty."
            )

        tty = target.tty
        escaped_text = escape_for_applescript(text)
        newline_bool = "false" if action in ("paste", "no_enter") else "true"

        script = f'''
        tell application "iTerm"
            set foundSession to missing value
            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if tty of s is "{tty}" then
                            set foundSession to s
                            exit repeat
                        end if
                    end repeat
                    if foundSession is not missing value then
                        exit repeat
                    end if
                end repeat
                if foundSession is not missing value then
                    exit repeat
                end if
            end repeat

            if foundSession is not missing value then
                tell foundSession
                    write text "{escaped_text}" newline {newline_bool}
                end tell
                return "OK"
            else
                return "ERROR: iTerm session not found"
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
                    message=f"Delivered directly to iTerm session {target.name} ({target.tty})"
                )
            else:
                err_msg = stderr or stdout or "Unknown error delivering to iTerm session"
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error=f"iTerm delivery failed: {err_msg}"
                )

        except subprocess.TimeoutExpired:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="Timed out attempting to send prompt to iTerm2"
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error=f"ITermAdapter exception: {str(e)}"
            )

    def get_history(self, target: Target, lines: int = 50) -> str:
        """Retrieves recent terminal output history from the iTerm2 session."""
        tty = target.tty
        script = f'''
        tell application "iTerm"
            set foundSession to missing value
            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if tty of s is "{tty}" then
                            set foundSession to s
                            exit repeat
                        end if
                    end repeat
                    if foundSession is not missing value then exit repeat
                end repeat
                if foundSession is not missing value then exit repeat
            end repeat
            if foundSession is not missing value then
                return text of foundSession
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

