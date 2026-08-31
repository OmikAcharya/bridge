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
        if not text:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name="Focused Application",
                adapter_used=self.name,
                error="Prompt text is empty."
            )

        try:
            # 1. Put prompt into macOS clipboard
            subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=2.0
            )

            # 2. Paste into active application via AppleScript keystrokes
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
