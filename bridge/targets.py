"""
Target Manager for Prompt Bridge.
Manages target registration, dynamic resolution, static alias mapping, and status queries.
"""

import os
from typing import List, Optional, Dict, Any

from bridge.models import Target
from bridge.discovery import SessionDiscovery
from bridge.config import Config


def _create_focused_target() -> Target:
    return Target(
        id="focused",
        name="Focused Mac Application",
        display_name="Focused Application (Active Window)",
        agent="legacy",
        agent_name="Focused App",
        cwd="",
        folder="",
        tty="",
        application="Active Window",
        status="available",
        is_busy=False,
        adapter="LegacyPasteAdapter"
    )


class TargetManager:
    """Manages active terminal targets and resolves logical target names."""

    def __init__(self, discovery: SessionDiscovery, config: Config):
        self.discovery = discovery
        self.config = config

    def get_targets(self, force_refresh: bool = False) -> List[Target]:
        """Returns the full list of available targets including dynamic sessions and fallback."""
        discovered = self.discovery.get_active_targets(force_refresh=force_refresh)
        targets: List[Target] = []

        # 1. Apply any configured static alias rules to discovered targets
        for target in discovered:
            # Check if any static alias maps to this target (by cwd, tty, or folder)
            for alias_id, alias_cfg in self.config.static_targets.items():
                match = False
                if "tty" in alias_cfg and alias_cfg["tty"] == target.tty:
                    match = True
                elif "cwd" in alias_cfg and os.path.abspath(os.path.expanduser(alias_cfg["cwd"])) == target.cwd:
                    match = True
                elif "folder" in alias_cfg and alias_cfg["folder"] == target.folder:
                    match = True

                if match:
                    if "name" in alias_cfg:
                        target.name = alias_cfg["name"]
                        target.display_name = f"{alias_cfg['name']} [{target.metadata.get('tty_short', '')}]"
                    target.metadata["alias_id"] = alias_id
            targets.append(target)

        # 2. Add Focused Application fallback if enabled
        if self.config.enable_legacy_paste:
            targets.append(_create_focused_target())

        return targets

    def resolve(self, target_id_or_alias: str) -> Optional[Target]:
        """
        Resolves a logical target ID, alias, TTY, or 'auto'/'focused' to an active Target.
        Uses warm cache first to avoid blocking prompt delivery.
        """
        if not target_id_or_alias or target_id_or_alias == "auto":
            return self._resolve_auto()

        if target_id_or_alias in ("focused", "active", "legacy"):
            return _create_focused_target()

        # 1. Try warm cached targets first (0ms latency)
        target = self._find_target(self.get_targets(force_refresh=False), target_id_or_alias)
        if target:
            return target

        # 2. Cold-start fallback: refresh once if not in cache
        return self._find_target(self.get_targets(force_refresh=True), target_id_or_alias)

    def _find_target(self, targets: List[Target], query: str) -> Optional[Target]:
        # 1. Exact ID match
        for t in targets:
            if t.id == query:
                return t

        # 2. Alias match from metadata
        for t in targets:
            if t.metadata.get("alias_id") == query:
                return t

        # 3. TTY match (e.g. "/dev/ttys001" or "ttys001")
        clean_tty = query if query.startswith("/dev/") else f"/dev/{query}"
        for t in targets:
            if t.tty == clean_tty or t.tty == query:
                return t

        # 4. Folder / CWD / Name match
        lower_query = query.lower()
        for t in targets:
            if t.folder.lower() == lower_query or t.name.lower() == lower_query:
                return t

        # 5. Check static config for predefined target
        static_cfg = self.config.get_static_target(query)
        if static_cfg:
            target_cwd = os.path.abspath(os.path.expanduser(static_cfg.get("cwd", ""))) if static_cfg.get("cwd") else ""
            target_agent = static_cfg.get("agent", "").lower()
            for t in targets:
                if target_cwd and t.cwd == target_cwd:
                    return t
                if target_agent and t.agent.lower() == target_agent:
                    return t

        return None

    def _resolve_auto(self) -> Optional[Target]:
        """Picks the most relevant active target automatically using warm cache."""
        targets = self.get_targets(force_refresh=False)
        if not targets:
            targets = self.get_targets(force_refresh=True)
        if not targets:
            return None

        # Priority 1: Running interactive agent (Claude, Codex, OpenCode, Aider, Agy)
        for t in targets:
            if t.agent in ("claude", "codex", "opencode", "aider", "agy") and t.id != "focused":
                return t

        # Priority 2: Other interactive sessions (Python, Node)
        for t in targets:
            if t.agent in ("python", "node") and t.id != "focused":
                return t

        # Priority 3: Any active terminal shell
        for t in targets:
            if t.id != "focused":
                return t

        # Priority 4: Focused fallback
        for t in targets:
            if t.id == "focused":
                return t

        return targets[0] if targets else None
