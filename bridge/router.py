"""
Prompt Router module.
Routes incoming prompt requests to resolved targets via appropriate terminal adapters.
"""

import logging
from typing import Optional

from bridge.models import PromptRequest, DeliveryResult, Target
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory

logger = logging.getLogger("PromptBridge.Router")


class PromptRouter:
    """Routes logical prompt delivery requests to resolved live terminal sessions."""

    def __init__(self, target_manager: TargetManager, adapter_factory: AdapterFactory):
        self.target_manager = target_manager
        self.adapter_factory = adapter_factory

    def route(self, request: PromptRequest) -> DeliveryResult:
        """Resolves target and executes prompt delivery."""
        prompt_snippet = (request.prompt[:40] + "...") if len(request.prompt) > 40 else request.prompt
        logger.info(f"Incoming prompt request (target='{request.target}', action='{request.action}', length={len(request.prompt)})")

        target: Optional[Target] = self.target_manager.resolve(request.target)

        if not target:
            err = f"Target session '{request.target}' could not be resolved. Make sure the terminal session is active."
            logger.warning(f"Resolution failed: {err}")
            return DeliveryResult(
                success=False,
                target_id=request.target,
                error=err
            )

        logger.info(f"Resolved target: id='{target.id}', name='{target.name}', tty='{target.tty}', app='{target.application}'")

        adapter = self.adapter_factory.get_adapter(target)
        logger.info(f"Selected adapter: {adapter.name}")

        result = adapter.send(target=target, text=request.prompt, action=request.action)

        if result.success:
            logger.info(f"Delivery successful to {target.name} via {adapter.name}")
        else:
            logger.error(f"Delivery failed: {result.error}")

        return result
