"""
PTY / Direct TTY Adapter.
Attempts direct injection via TTY character device where supported by OS permissions,
with graceful delegation.
"""

import os
import fcntl
import termios
from bridge.adapters.base import TerminalAdapter
from bridge.models import Target, DeliveryResult


class PTYAdapter(TerminalAdapter):
    """Direct TTY/PTY injection adapter."""

    @property
    def name(self) -> str:
        return "PTYAdapter"

    def can_handle(self, target: Target) -> bool:
        return bool(target.tty and os.path.exists(target.tty))

    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        if not target.tty or not os.path.exists(target.tty):
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error=f"TTY device {target.tty} not found or inaccessible."
            )

        payload = text if action in ("paste", "no_enter") else f"{text}\n"

        # Attempt TIOCSTI injection on the TTY slave
        try:
            fd = os.open(target.tty, os.O_RDWR | os.O_NOCTTY)
            try:
                for char in payload.encode("utf-8"):
                    fcntl.ioctl(fd, termios.TIOCSTI, bytes([char]))
                return DeliveryResult(
                    success=True,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    message=f"Directly injected {len(payload)} bytes to {target.tty}"
                )
            finally:
                os.close(fd)
        except PermissionError:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="TIOCSTI permission denied by macOS security policy. Use AppleTerminalAdapter or ITermAdapter."
            )
        except Exception as e:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error=f"PTY injection error: {str(e)}"
            )
