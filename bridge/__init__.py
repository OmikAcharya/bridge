"""
Prompt Bridge package.
Direct Android -> Existing Terminal Agent input bridge.
"""

from bridge.models import Target, PromptRequest, DeliveryResult, SessionInfo
from bridge.config import Config
from bridge.discovery import SessionDiscovery
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory
from bridge.router import PromptRouter
from bridge.server import create_server, run

__version__ = "2.0.0"

__all__ = [
    "Target",
    "PromptRequest",
    "DeliveryResult",
    "SessionInfo",
    "Config",
    "SessionDiscovery",
    "TargetManager",
    "AdapterFactory",
    "PromptRouter",
    "create_server",
    "run",
]
