"""
Configuration manager for Prompt Bridge.
"""

import os
import json
from typing import Dict, Any, Optional


DEFAULT_PORT = 8765
CONFIG_PATHS = [
    os.path.expanduser("~/.bridge_config.json"),
    os.path.join(os.getcwd(), "bridge_config.json"),
]


class Config:
    def __init__(self):
        self.port: int = int(os.environ.get("BRIDGE_PORT", os.environ.get("PORT", DEFAULT_PORT)))
        self.auth_token: Optional[str] = os.environ.get("BRIDGE_AUTH_TOKEN", None)
        self.default_target: str = os.environ.get("BRIDGE_DEFAULT_TARGET", "auto")
        self.enable_legacy_paste: bool = os.environ.get("BRIDGE_ENABLE_LEGACY", "true").lower() in ("true", "1", "yes")
        self.expose_lan: bool = os.environ.get("BRIDGE_EXPOSE_LAN", "false").lower() in ("true", "1", "yes")
        self.static_targets: Dict[str, Dict[str, Any]] = {}
        self.load_file_config()

    def load_file_config(self):
        """Loads optional configuration from JSON file if present."""
        for path in CONFIG_PATHS:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.port = int(data.get("port", self.port)) if not os.environ.get("BRIDGE_PORT") else self.port
                self.auth_token = data.get("auth_token", self.auth_token) if not os.environ.get("BRIDGE_AUTH_TOKEN") else self.auth_token
                self.default_target = data.get("default_target", self.default_target)
                self.enable_legacy_paste = bool(data.get("enable_legacy_paste", self.enable_legacy_paste))
                self.expose_lan = bool(data.get("expose_lan", self.expose_lan)) if not os.environ.get("BRIDGE_EXPOSE_LAN") else self.expose_lan
                if isinstance(data.get("targets"), dict):
                    self.static_targets = data["targets"]
                break
            except Exception as e:
                print(f"[Config] Warning: Failed to read config from {path}: {e}")

    def get_static_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        return self.static_targets.get(target_id)
