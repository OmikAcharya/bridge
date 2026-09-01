"""
Legacy Paste Adapter.
Provides fallback / backward-compatible delivery to the currently focused macOS window using
the clipboard (pbcopy) and AppleScript System Events keystrokes.
"""

import subprocess
from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult


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
                    error=f"Interrupt failed: {str(e)}"
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
                    error=f"Return failed: {str(e)}"
                )

        # 1. Preserve current clipboard content
        prev_clipboard = None
        try:
            p = subprocess.run(["pbpaste"], capture_output=True, timeout=1.0)
            if p.returncode == 0:
                prev_clipboard = p.stdout
        except Exception:
            pass

        try:
            # 2. Put prompt into macOS clipboard
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=2.0
            )

            # 3. Paste into active application via AppleScript keystrokes
            if action in ("paste_and_enter", "execute"):
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
                error=f"Legacy paste failed: {str(e)}"
            )
        finally:
            if prev_clipboard is not None:
                def _restore(data):
                    import time
                    time.sleep(0.35)
                    try:
                        subprocess.run(["pbcopy"], input=data, timeout=1.0)
                    except Exception:
                        pass
                import threading
                threading.Thread(target=_restore, args=(prev_clipboard,), daemon=True).start()
