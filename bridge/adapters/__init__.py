"""
Adapters package for Prompt Bridge.
"""

from bridge.adapters.base import TerminalAdapter
from bridge.adapters.terminal import AppleTerminalAdapter
from bridge.adapters.iterm import ITermAdapter
from bridge.adapters.legacy import LegacyPasteAdapter
from bridge.adapters.factory import get_adapter, AdapterFactory

__all__ = [
    "TerminalAdapter",
    "AppleTerminalAdapter",
    "ITermAdapter",
    "LegacyPasteAdapter",
    "get_adapter",
    "AdapterFactory",
]
