"""
Terminal adapter resolver.

Preference order:
  1. PTYAdapter      — direct PTY master injection, zero focus/clipboard (requires bridge pty_proxy)
  2. AppleTerminal / iTerm  — AppleScript OSA delivery (may touch focus for some actions)
  3. LegacyPasteAdapter     — clipboard + GUI keystroke fallback
"""

from bridge.models import Target
from bridge.adapters.base import TerminalAdapter
from bridge.adapters.terminal import AppleTerminalAdapter
from bridge.adapters.iterm import ITermAdapter
from bridge.adapters.legacy import LegacyPasteAdapter
from bridge.adapters.pty_adapter import PTYAdapter

_pty = PTYAdapter()
_terminal = AppleTerminalAdapter()
_iterm = ITermAdapter()
_legacy = LegacyPasteAdapter()


def get_adapter(target: Target) -> TerminalAdapter:
    """Resolves the best available adapter for a given target."""
    if target.id in ("focused", "active", "legacy") or target.agent == "legacy":
        return _legacy
    # Prefer PTY injection when proxy socket exists
    if _pty.can_handle(target):
        return _pty
    if target.application == "iTerm":
        return _iterm
    if target.application == "Terminal" or (target.tty and target.tty.startswith("/dev/tty")):
        return _terminal
    return _legacy


class AdapterFactory:
    """Backward-compatible adapter resolver."""
    @staticmethod
    def get_adapter(target: Target) -> TerminalAdapter:
        return get_adapter(target)
