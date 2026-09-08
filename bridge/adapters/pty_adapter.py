"""
PTY Adapter — focus-independent stdin injection via PTY master fd.

Connects to a Unix domain socket exposed by the bridge PTY proxy.
Writing to the socket writes to the master side of the PTY pair,
which the child process (agent) reads as stdin.

No clipboard, no window activation, no GUI keystrokes.
"""

import logging
import os
import signal
import socket
import time
from typing import Optional

from bridge.models import Target, DeliveryResult
from bridge.adapters.base import TerminalAdapter

logger = logging.getLogger("PromptBridge.PTYAdapter")

# Socket directory — must match pty_proxy.py
PTY_SOCK_DIR = os.environ.get("BRIDGE_PTY_SOCK_DIR", "/tmp")
PTY_SOCK_PREFIX = "bridge_pty_"


def _find_socket(target: Target) -> Optional[str]:
    """Finds the Unix domain socket for a target's PTY proxy session."""
    # Check metadata first (set by discovery when proxy socket is found)
    sock_path = target.metadata.get("pty_sock")
    if sock_path and os.path.exists(sock_path):
        return sock_path

    # Scan by PID
    if target.pid:
        candidate = os.path.join(PTY_SOCK_DIR, f"{PTY_SOCK_PREFIX}{target.pid}.sock")
        if os.path.exists(candidate):
            return candidate

    # Scan by TTY name (proxy names sockets after slave device)
    if target.tty:
        tty_short = target.tty.replace("/dev/", "")
        candidate = os.path.join(PTY_SOCK_DIR, f"{PTY_SOCK_PREFIX}{tty_short}.sock")
        if os.path.exists(candidate):
            return candidate

    return None


class PTYAdapter(TerminalAdapter):
    """Injects text into a terminal session's stdin via PTY master fd.

    Requires the target process to be running under the bridge PTY proxy
    (bridge/pty_proxy.py), which exposes the master fd on a Unix domain socket.

    This adapter:
    - Does NOT call activate on any application
    - Does NOT change window/tab focus
    - Does NOT touch the system clipboard
    - Does NOT simulate GUI keystrokes
    """

    @property
    def name(self) -> str:
        return "PTYAdapter"

    def can_handle(self, target: Target) -> bool:
        return _find_socket(target) is not None

    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        sock_path = _find_socket(target)
        if not sock_path:
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="No PTY proxy socket found for this target."
            )

        # Handle interrupt: send SIGINT to foreground process group, no socket needed
        if action == "interrupt" or text == "\x03":
            return self._send_interrupt(target)

        if not text and action not in ("raw_enter",):
            return DeliveryResult(
                success=False,
                target_id=target.id,
                target_name=target.name,
                adapter_used=self.name,
                error="Prompt text is empty."
            )

        # Build the raw bytes to inject
        if action == "raw_enter" or text == "\n":
            payload = b"\n"
        elif action in ("paste", "no_enter"):
            # Inject text without trailing newline
            payload = text.encode("utf-8")
        else:
            # execute / paste_and_enter / send: text + newline
            payload = text.encode("utf-8") + b"\n"

        last_err = None
        for attempt in range(3):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(3.0)
                    conn.connect(sock_path)
                    conn.sendall(payload)

                return DeliveryResult(
                    success=True,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    message=f"Injected {len(payload)} bytes via PTY to {target.name}"
                )
            except (ConnectionRefusedError, FileNotFoundError) as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.05)
                    continue
            except socket.timeout:
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error="PTY proxy socket connection timed out."
                )
            except OSError as e:
                return DeliveryResult(
                    success=False,
                    target_id=target.id,
                    target_name=target.name,
                    adapter_used=self.name,
                    error=f"PTY socket error: {e}"
                )

        return DeliveryResult(
            success=False,
            target_id=target.id,
            target_name=target.name,
            adapter_used=self.name,
            error=f"PTY socket error: {last_err}"
        )

    def _send_interrupt(self, target: Target) -> DeliveryResult:
        """Sends SIGINT to the target's foreground process group."""
        if target.pid:
            try:
                # Send to process group for proper signal propagation
                pgid = os.getpgid(target.pid)
                os.killpg(pgid, signal.SIGINT)
            except ProcessLookupError:
                pass
            except OSError:
                # Fallback: signal the process directly
                try:
                    os.kill(target.pid, signal.SIGINT)
                except OSError:
                    pass

        # Also write Ctrl-C byte to PTY if socket available
        sock_path = _find_socket(target)
        if sock_path:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(1.0)
                    conn.connect(sock_path)
                    conn.sendall(b"\x03")
            except OSError:
                pass

        return DeliveryResult(
            success=True,
            target_id=target.id,
            target_name=target.name,
            adapter_used=self.name,
            message="Interrupt sent via PTY"
        )
