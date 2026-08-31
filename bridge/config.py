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
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "port" in data and not os.environ.get("BRIDGE_PORT"):
                        self.port = int(data["port"])
                    if "auth_token" in data and not os.environ.get("BRIDGE_AUTH_TOKEN"):
                        self.auth_token = data["auth_token"]
                    if "default_target" in data:
                        self.default_target = data["default_target"]
                    if "enable_legacy_paste" in data:
                        self.enable_legacy_paste = bool(data["enable_legacy_paste"])
                    if "expose_lan" in data and not os.environ.get("BRIDGE_EXPOSE_LAN"):
                        self.expose_lan = bool(data["expose_lan"])
                    if "targets" in data and isinstance(data["targets"], dict):
                        self.static_targets = data["targets"]
                    break
                except Exception as e:
                    print(f"[Config] Warning: Failed to read config from {path}: {e}")

    def get_static_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        return self.static_targets.get(target_id)
