"""
Abstract base class for Terminal Adapters.
"""

from abc import ABC, abstractmethod
from bridge.models import Target, DeliveryResult


class TerminalAdapter(ABC):
    """Abstract base class for all terminal injection adapters."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the adapter."""
        pass

    @abstractmethod
    def can_handle(self, target: Target) -> bool:
        """Determines if this adapter can deliver to the specified target."""
        pass

    @abstractmethod
    def send(self, target: Target, text: str, action: str = "execute") -> DeliveryResult:
        """
        Delivers the prompt text to the target.
        
        Args:
            target: The resolved Target instance.
            text: The prompt string to inject.
            action: Delivery mode ("execute", "paste_and_enter", "paste", "send").
        
        Returns:
            DeliveryResult indicating success or failure.
        """
        pass
