"""
Target Manager for Prompt Bridge.
Manages target registration, dynamic resolution, static alias mapping, and status queries.
"""

import os
from typing import List, Optional, Dict, Any

from bridge.models import Target
from bridge.discovery import SessionDiscovery
from bridge.config import Config


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
            focused_target = Target(
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
            targets.append(focused_target)

        return targets

    def resolve(self, target_id_or_alias: str) -> Optional[Target]:
        """
        Resolves a logical target ID, alias, TTY, or 'auto'/'focused' to an active Target.
        """
        if not target_id_or_alias or target_id_or_alias == "auto":
            return self._resolve_auto()

        if target_id_or_alias in ("focused", "active", "legacy"):
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

        # Fresh targets list
        targets = self.get_targets(force_refresh=True)

        # 1. Exact ID match
        for t in targets:
            if t.id == target_id_or_alias:
                return t

        # 2. Alias match from metadata
        for t in targets:
            if t.metadata.get("alias_id") == target_id_or_alias:
                return t

        # 3. TTY match (e.g. "/dev/ttys001" or "ttys001")
        clean_tty = target_id_or_alias if target_id_or_alias.startswith("/dev/") else f"/dev/{target_id_or_alias}"
        for t in targets:
            if t.tty == clean_tty or t.tty == target_id_or_alias:
                return t

        # 4. Folder / CWD / Name match
        lower_query = target_id_or_alias.lower()
        for t in targets:
            if t.folder.lower() == lower_query or t.name.lower() == lower_query:
                return t

        # 5. Check static config for predefined target even if not yet mapped
        static_cfg = self.config.get_static_target(target_id_or_alias)
        if static_cfg:
            # Try to match static config properties against active sessions
            target_cwd = os.path.abspath(os.path.expanduser(static_cfg.get("cwd", ""))) if static_cfg.get("cwd") else ""
            target_agent = static_cfg.get("agent", "").lower()
            for t in targets:
                if target_cwd and t.cwd == target_cwd:
                    return t
                if target_agent and t.agent.lower() == target_agent:
                    return t

        return None

    def _resolve_auto(self) -> Optional[Target]:
        """Picks the most relevant active target automatically."""
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
