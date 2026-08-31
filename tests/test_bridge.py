"""
Unit and integration tests for Prompt Bridge.
"""

import unittest
import json
import os
import subprocess
from unittest.mock import MagicMock, patch

from bridge.models import Target, PromptRequest, DeliveryResult, SessionInfo
from bridge.config import Config
from bridge.discovery import SessionDiscovery, classify_command
from bridge.targets import TargetManager
from bridge.adapters.base import TerminalAdapter
from bridge.adapters.terminal import AppleTerminalAdapter, escape_for_applescript
from bridge.adapters.iterm import ITermAdapter
from bridge.adapters.legacy import LegacyPasteAdapter
from bridge.adapters.pty import PTYAdapter
from bridge.adapters.factory import AdapterFactory
from bridge.router import PromptRouter
from bridge.server import create_server


class TestModels(unittest.TestCase):
    def test_target_serialization(self):
        target = Target(
            id="claude-backend",
            name="Claude Code — backend",
            display_name="Claude Code — backend [ttys001]",
            agent="claude",
            agent_name="Claude Code",
            cwd="/Users/mac/Projects/backend",
            folder="backend",
            tty="/dev/ttys001",
            application="Terminal",
            status="ready",
            is_busy=False,
            pid=1234,
            cmd="claude",
            win_idx=1,
            tab_idx=2
        )
        d = target.to_dict()
        self.assertEqual(d["id"], "claude-backend")
        self.assertEqual(d["agent"], "claude")
        self.assertEqual(d["folder"], "backend")
        self.assertEqual(d["tty"], "/dev/ttys001")
        self.assertEqual(d["pid"], 1234)

    def test_prompt_request_and_delivery_result(self):
        req = PromptRequest(prompt="Refactor auth", target="claude-backend", action="execute")
        self.assertEqual(req.prompt, "Refactor auth")
        self.assertEqual(req.target, "claude-backend")

        res = DeliveryResult(
            success=True,
            target_id="claude-backend",
            target_name="Claude Code — backend",
            adapter_used="AppleTerminalAdapter",
            message="Delivered"
        )
        self.assertTrue(res.success)
        self.assertEqual(res.to_dict()["adapter_used"], "AppleTerminalAdapter")


class TestDiscoveryAndClassification(unittest.TestCase):
    def test_classify_commands(self):
        cases = [
            ("claude", ("Claude Code", "claude")),
            ("node /usr/local/bin/claude", ("Claude Code", "claude")),
            ("@anthropic-ai/claude-code", ("Claude Code", "claude")),
            ("codex run", ("Codex", "codex")),
            ("opencode start", ("OpenCode", "opencode")),
            ("aider --model gpt-4", ("Aider", "aider")),
            ("agy --dangerously-skip-permissions", ("Antigravity", "agy")),
            ("python3 -i script.py", ("Python", "python")),
            ("ipython", ("IPython", "python")),
            ("node index.js", ("Node", "node")),
            ("-zsh", ("Zsh", "shell")),
            ("/bin/bash", ("Bash", "shell")),
            ("fish", ("Fish", "shell")),
            ("custom_tool --flag", ("Terminal Session", "terminal")),
        ]
        for cmd, expected in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(classify_command(cmd), expected)

    def test_session_discovery_mock(self):
        discovery = SessionDiscovery()
        with patch.object(discovery, "_discover_apple_terminal") as mock_tabs, \
             patch.object(discovery, "_discover_iterm") as mock_iterm, \
             patch.object(discovery, "_discover_processes_by_tty") as mock_procs:
            
            mock_tabs.return_value = {
                "/dev/ttys001": {
                    "app": "Terminal",
                    "win_idx": 1,
                    "tab_idx": 1,
                    "tty": "/dev/ttys001",
                    "selected": True,
                    "busy": False,
                    "procs": ["zsh", "claude"],
                    "win_name": "backend - claude"
                }
            }
            mock_iterm.return_value = {}
            mock_procs.return_value = {
                "/dev/ttys001": [
                    {"pid": 100, "ppid": 1, "cmd": "-zsh", "cwd": "/Users/mac/Projects/backend"},
                    {"pid": 101, "ppid": 100, "cmd": "claude", "cwd": "/Users/mac/Projects/backend"}
                ]
            }

            targets = discovery.get_active_targets(force_refresh=True)
            self.assertEqual(len(targets), 1)
            t = targets[0]
            self.assertEqual(t.agent, "claude")
            self.assertEqual(t.folder, "backend")
            self.assertEqual(t.tty, "/dev/ttys001")
            self.assertEqual(t.pid, 101)


class TestTargetManager(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.config.enable_legacy_paste = True
        self.config.static_targets = {
            "backend": {"name": "Claude — Backend", "folder": "backend"},
            "frontend": {"name": "Claude — Frontend", "folder": "frontend"}
        }
        self.discovery = MagicMock(spec=SessionDiscovery)
        self.target_manager = TargetManager(discovery=self.discovery, config=self.config)

    def test_get_targets_and_static_alias_mapping(self):
        self.discovery.get_active_targets.return_value = [
            Target(
                id="claude-backend",
                name="Claude Code — backend",
                display_name="Claude Code — backend [ttys001]",
                agent="claude",
                agent_name="Claude Code",
                cwd="/Users/mac/Projects/backend",
                folder="backend",
                tty="/dev/ttys001",
                application="Terminal"
            )
        ]

        targets = self.target_manager.get_targets(force_refresh=True)
        # Should contain discovered target + focused fallback
        self.assertEqual(len(targets), 2)
        
        backend_t = next(t for t in targets if t.folder == "backend")
        self.assertEqual(backend_t.name, "Claude — Backend")
        self.assertEqual(backend_t.metadata.get("alias_id"), "backend")

        focused_t = next(t for t in targets if t.id == "focused")
        self.assertIsNotNone(focused_t)

    def test_resolve_by_alias_id_and_tty(self):
        target1 = Target(
            id="claude-backend",
            name="Claude — Backend",
            display_name="Claude — Backend [ttys001]",
            agent="claude",
            agent_name="Claude Code",
            cwd="/Users/mac/Projects/backend",
            folder="backend",
            tty="/dev/ttys001",
            metadata={"alias_id": "backend", "tty_short": "ttys001"}
        )
        self.discovery.get_active_targets.return_value = [target1]

        # Resolve by alias
        res_alias = self.target_manager.resolve("backend")
        self.assertIsNotNone(res_alias)
        self.assertEqual(res_alias.id, "claude-backend")

        # Resolve by ID
        res_id = self.target_manager.resolve("claude-backend")
        self.assertIsNotNone(res_id)
        self.assertEqual(res_id.tty, "/dev/ttys001")

        # Resolve by TTY
        res_tty = self.target_manager.resolve("ttys001")
        self.assertIsNotNone(res_tty)
        self.assertEqual(res_tty.id, "claude-backend")

        # Resolve focused
        res_focused = self.target_manager.resolve("focused")
        self.assertIsNotNone(res_focused)
        self.assertEqual(res_focused.id, "focused")

        # Resolve auto
        res_auto = self.target_manager.resolve("auto")
        self.assertIsNotNone(res_auto)
        self.assertEqual(res_auto.id, "claude-backend")

        # Unknown target
        res_none = self.target_manager.resolve("non_existent_target")
        self.assertIsNone(res_none)


class TestAdaptersAndEscaping(unittest.TestCase):
    def test_escape_for_applescript(self):
        raw = 'echo "hello \\ world" && pwd'
        escaped = escape_for_applescript(raw)
        self.assertIn('\\"', escaped)
        self.assertIn('\\\\', escaped)

    def test_adapter_factory(self):
        factory = AdapterFactory()
        
        terminal_target = Target(id="t1", name="t1", display_name="t1", agent="claude", agent_name="Claude", application="Terminal", tty="/dev/ttys001")
        iterm_target = Target(id="t2", name="t2", display_name="t2", agent="codex", agent_name="Codex", application="iTerm", tty="/dev/ttys002")
        legacy_target = Target(id="focused", name="focused", display_name="focused", agent="legacy", agent_name="Legacy", application="Active Window")

        self.assertIsInstance(factory.get_adapter(terminal_target), AppleTerminalAdapter)
        self.assertIsInstance(factory.get_adapter(iterm_target), ITermAdapter)
        self.assertIsInstance(factory.get_adapter(legacy_target), LegacyPasteAdapter)


class TestPromptRouter(unittest.TestCase):
    def setUp(self):
        self.target_manager = MagicMock(spec=TargetManager)
        self.adapter_factory = MagicMock(spec=AdapterFactory)
        self.mock_adapter = MagicMock(spec=TerminalAdapter)
        self.mock_adapter.name = "MockAdapter"
        self.adapter_factory.get_adapter.return_value = self.mock_adapter
        self.router = PromptRouter(target_manager=self.target_manager, adapter_factory=self.adapter_factory)

    def test_successful_route(self):
        target = Target(
            id="backend",
            name="Claude — Backend",
            display_name="Claude — Backend",
            agent="claude",
            agent_name="Claude Code",
            tty="/dev/ttys001"
        )
        self.target_manager.resolve.return_value = target
        self.mock_adapter.send.return_value = DeliveryResult(
            success=True,
            target_id="backend",
            target_name="Claude — Backend",
            adapter_used="MockAdapter",
            message="OK"
        )

        req = PromptRequest(prompt="Check tests", target="backend", action="execute")
        res = self.router.route(req)

        self.assertTrue(res.success)
        self.assertEqual(res.target_id, "backend")
        self.mock_adapter.send.assert_called_once_with(target=target, text="Check tests", action="execute")

    def test_unresolved_target_failure(self):
        self.target_manager.resolve.return_value = None
        req = PromptRequest(prompt="Check tests", target="missing_target", action="execute")
        res = self.router.route(req)

        self.assertFalse(res.success)
        self.assertIn("could not be resolved", res.error)


if __name__ == "__main__":
    unittest.main()
