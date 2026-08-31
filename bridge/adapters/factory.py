"""
Adapter factory for resolving appropriate terminal injection adapters.
"""

from typing import List
from bridge.models import Target
from bridge.adapters.base import TerminalAdapter
from bridge.adapters.terminal import AppleTerminalAdapter
from bridge.adapters.iterm import ITermAdapter
from bridge.adapters.pty import PTYAdapter
from bridge.adapters.legacy import LegacyPasteAdapter


class AdapterFactory:
    """Selects and manages available terminal adapters."""

    def __init__(self):
        self.terminal_adapter = AppleTerminalAdapter()
        self.iterm_adapter = ITermAdapter()
        self.pty_adapter = PTYAdapter()
        self.legacy_adapter = LegacyPasteAdapter()

    def get_adapter(self, target: Target) -> TerminalAdapter:
        """Resolves the best available adapter for a given target."""
        # 1. Explicit legacy / focused target
        if target.id in ("focused", "active", "legacy") or target.agent == "legacy":
            return self.legacy_adapter

        # 2. iTerm2 application target
        if target.application == "iTerm":
            return self.iterm_adapter

        # 3. macOS Terminal.app target
        if target.application == "Terminal" or (target.tty and target.tty.startswith("/dev/tty")):
            return self.terminal_adapter

        # 4. Fallback to legacy paste if everything else fails
        return self.legacy_adapter
