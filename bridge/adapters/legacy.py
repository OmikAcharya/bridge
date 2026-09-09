"""
Legacy Paste Adapter.
Provides fallback / backward-compatible delivery to the currently focused macOS window using
the clipboard (pbcopy) and AppleScript System Events keystrokes.
"""

import subprocess
import time
from typing import Optional

from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult


def _format_applescript_error(e: Exception) -> str:
    """Extracts stderr from CalledProcessError and checks for macOS permission issues."""
    if isinstance(e, subprocess.CalledProcessError) and e.stderr:
        err_msg = e.stderr.decode("utf-8", errors="replace").strip()
        if "1002" in err_msg or "not allowed to send keystrokes" in err_msg or "-1743" in err_msg:
            return (
                "macOS Accessibility permission required: Allow Terminal/IDE in "
                "System Settings -> Privacy & Security -> Accessibility to send keystrokes to active windows. "
                "(Prompt copied to clipboard; press ⌘V to paste manually)"
            )
        return f"AppleScript error: {err_msg}"
    return str(e)


class LegacyPasteAdapter(TerminalAdapter):
    """Adapter that pastes into whatever macOS application currently has GUI focus."""

    @property
    def name(self) -> str:
        return "LegacyPasteAdapter"

    def can_handle(self, target: Target) -> bool:
        return target.id in ("focused", "active", "legacy") or target.agent == "legacy"

    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        if not text and action not in ("interrupt", "raw_enter"):
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name="Focused Application",
                adapter_used=self.name,
                error="Prompt text is empty."
            )

        if action == "interrupt" or text == "\x03":
            try:
                applescript = 'tell application "System Events" to keystroke "c" using control down'
                subprocess.run(["osascript", "-e", applescript], check=True, capture_output=True, timeout=3.0)
                return DeliveryResult(
                    success=True,
                    target_id=target.id,
                    target_name="Focused Application",
                    adapter_used=self.name,
                    message="Sent Ctrl+C interrupt to focused application"
                )
            except Exception as e:
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name="Focused Application",
                    adapter_used=self.name,
                    error=f"Interrupt failed: {_format_applescript_error(e)}"
                )

        if action == "raw_enter" or text == "\n":
            try:
                applescript = 'tell application "System Events" to key code 36'
                subprocess.run(["osascript", "-e", applescript], check=True, capture_output=True, timeout=3.0)
                return DeliveryResult(
                    success=True,
                    target_id=target.id,
                    target_name="Focused Application",
                    adapter_used=self.name,
                    message="Sent Return (Enter) to focused application"
                )
            except Exception as e:
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name="Focused Application",
                    adapter_used=self.name,
                    error=f"Return failed: {_format_applescript_error(e)}"
                )

        # 1. Preserve current clipboard content
        prev_clipboard = None
        try:
            p = subprocess.run(["pbpaste"], capture_output=True, timeout=1.0)
            if p.returncode == 0:
                prev_clipboard = p.stdout
        except Exception:
            pass

        success = False
        try:
            # 2. Put prompt into macOS clipboard
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=2.0
            )

            press_enter = action in ("paste_and_enter", "execute")

            # 3. AppleScript keystrokes via System Events
            if press_enter:
                applescript = (
                    'tell application "System Events"\n'
                    '    keystroke "v" using command down\n'
                    '    delay 0.05\n'
                    '    key code 36\n'
                    'end tell'
                )
            else:
                applescript = 'tell application "System Events" to keystroke "v" using command down'

            subprocess.run(
                ["osascript", "-e", applescript],
                check=True,
                capture_output=True,
                timeout=3.0
            )
            success = True

            return DeliveryResult(
                success=True,
                target_id=target.id,
                target_name="Focused Application",
                adapter_used=self.name,
                message="Pasted into currently focused Mac application"
            )

        except subprocess.TimeoutExpired:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name="Focused Application",
                adapter_used=self.name,
                error="Timed out attempting to paste into active application"
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name="Focused Application",
                adapter_used=self.name,
                error=f"Legacy paste failed: {_format_applescript_error(e)}"
            )
        finally:
            # Only restore previous clipboard if automated paste succeeded.
            # If paste failed, keep prompt on clipboard so user can press ⌘V manually.
            if success and prev_clipboard is not None:
                def _restore(data):
                    time.sleep(0.35)
                    try:
                        subprocess.run(["pbcopy"], input=data, timeout=1.0)
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_restore, args=(prev_clipboard,), daemon=True).start()
