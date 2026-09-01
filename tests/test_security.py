"""
Unit tests for Prompt Bridge security hardening.
Tests CSRF prevention, AppleScript escaping, TTY sanitization, DoS limits,
constant-time authentication, and credential redaction.
"""

import unittest
import urllib.request
import urllib.error
import json
import threading
from bridge.config import Config
from bridge.server import create_server, MAX_BODY_SIZE
from bridge.adapters.terminal import escape_for_applescript, sanitize_tty
from bridge.discovery import redact_sensitive_cmd


class TestSecurityHardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = Config()
        cls.config.port = 8798
        cls.config.auth_token = "super_secret_token_12345"
        cls.server = create_server(cls.config)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_csrf_protection_cross_site(self):
        """Cross-site Sec-Fetch-Site requests must be rejected with 403 Forbidden."""
        req = urllib.request.Request(
            "http://127.0.0.1:8798/prompt",
            data=json.dumps({"prompt": "echo hi", "target": "auto"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Sec-Fetch-Site": "cross-site",
                "Authorization": "Bearer super_secret_token_12345"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_csrf_protection_untrusted_origin(self):
        """Requests from untrusted third-party origins must be rejected with 403."""
        req = urllib.request.Request(
            "http://127.0.0.1:8798/prompt",
            data=json.dumps({"prompt": "echo hi", "target": "auto"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "http://malicious-site.com",
                "Authorization": "Bearer super_secret_token_12345"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_payload_too_large_dos_prevention(self):
        """Payloads exceeding MAX_BODY_SIZE (64KB) must return 413 Payload Too Large."""
        large_body = json.dumps({"prompt": "A" * (MAX_BODY_SIZE + 100)}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8798/prompt",
            data=large_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer super_secret_token_12345"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 413)

    def test_auth_token_constant_time_comparison(self):
        """Valid token succeeds, wrong token returns 401 Unauthorized."""
        req = urllib.request.Request(
            "http://127.0.0.1:8798/targets",
            headers={"Authorization": "Bearer super_secret_token_12345"}
        )
        res = urllib.request.urlopen(req)
        self.assertEqual(res.status, 200)

        bad_req = urllib.request.Request(
            "http://127.0.0.1:8798/targets",
            headers={"Authorization": "Bearer wrong_token"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad_req)
        self.assertEqual(ctx.exception.code, 401)

    def test_tty_sanitization(self):
        """Sanitize TTY strips dangerous characters for AppleScript injection."""
        self.assertEqual(sanitize_tty("/dev/ttys001"), "/dev/ttys001")
        self.assertEqual(sanitize_tty("ttys002"), "ttys002")
        self.assertEqual(sanitize_tty('ttys001" or 1=1'), "")
        self.assertEqual(sanitize_tty("ttys001; rm -rf /"), "")
        self.assertEqual(sanitize_tty(""), "")

    def test_applescript_escaping(self):
        """Escaping handles quotes, backslashes, line separators, and null bytes."""
        raw = 'echo "hello \\ world"\0\u2028new line\r\n'
        escaped = escape_for_applescript(raw)
        self.assertNotIn('\0', escaped)
        self.assertNotIn('\u2028', escaped)
        self.assertIn('\\"', escaped)
        self.assertIn('\\\\', escaped)

    def test_credential_redaction(self):
        """Sensitive credentials are automatically redacted in process discovery."""
        cmd1 = "curl -H 'Authorization: Bearer sk-ant-api03-abcdef1234567890' https://api.anthropic.com"
        redacted1 = redact_sensitive_cmd(cmd1)
        self.assertNotIn("sk-ant-api03", redacted1)
        self.assertIn("[REDACTED]", redacted1)

        cmd2 = "psql postgresql://admin:SuperSecretPass@localhost:5432/db"
        redacted2 = redact_sensitive_cmd(cmd2)
        self.assertNotIn("SuperSecretPass", redacted2)
        self.assertIn("[REDACTED]", redacted2)

        cmd3 = "git clone https://ghp_1234567890abcdefghijklmnopqrstuvwxyz@github.com/repo"
        redacted3 = redact_sensitive_cmd(cmd3)
        self.assertNotIn("ghp_1234567890abcdefghijklmnopqrstuvwxyz", redacted3)
        self.assertIn("[REDACTED]", redacted3)


if __name__ == "__main__":
    unittest.main()
