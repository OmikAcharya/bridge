"""
Adapters package for Prompt Bridge.
"""

from bridge.adapters.base import TerminalAdapter
from bridge.adapters.terminal import AppleTerminalAdapter
from bridge.adapters.iterm import ITermAdapter
from bridge.adapters.pty import PTYAdapter
from bridge.adapters.legacy import LegacyPasteAdapter
from bridge.adapters.factory import AdapterFactory

__all__ = [
    "TerminalAdapter",
    "AppleTerminalAdapter",
    "ITermAdapter",
    "PTYAdapter",
    "LegacyPasteAdapter",
    "AdapterFactory",
]
