"""
Domain models for Prompt Bridge.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class Target:
    """Represents a logical or discovered terminal agent target."""
    id: str
    name: str
    display_name: str
    agent: str  # e.g., "claude", "codex", "opencode", "agy", "shell", "legacy"
    agent_name: str  # e.g., "Claude Code", "Codex", "Zsh Shell"
    cwd: str = ""
    folder: str = ""
    tty: str = ""
    application: str = "Terminal"  # "Terminal", "iTerm", "Active Window"
    status: str = "available"  # "available", "ready", "busy", "offline"
    is_busy: bool = False
    pid: Optional[int] = None
    cmd: str = ""
    win_idx: Optional[int] = None
    tab_idx: Optional[int] = None
    adapter: str = "auto"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionInfo:
    """Runtime information about an active terminal session."""
    tty: str
    application: str
    win_idx: Optional[int] = None
    tab_idx: Optional[int] = None
    win_name: str = ""
    selected: bool = False
    busy: bool = False
    procs: List[str] = field(default_factory=list)
    pids: List[int] = field(default_factory=list)
    cwd: str = ""
    foreground_pid: Optional[int] = None
    foreground_cmd: str = ""


@dataclass
class PromptRequest:
    """Incoming prompt delivery request."""
    prompt: str
    target: str = "auto"  # target ID, alias, or "focused"
    action: str = "execute"  # "execute", "paste_and_enter", "paste", "send"
    token: Optional[str] = None


@dataclass
class DeliveryResult:
    """Result of prompt delivery."""
    success: bool
    target_id: str
    target_name: str = ""
    adapter_used: str = ""
    message: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
