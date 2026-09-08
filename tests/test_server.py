"""
Integration tests for the HTTP server and API endpoints.
"""

import unittest
import threading
import time
import json
import urllib.request
import urllib.error

from bridge.server import create_server
from bridge.config import Config


class TestServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config()
        cls.config.port = 18765  # Test port
        cls.config.auth_token = None
        cls.config.enable_legacy_paste = True
        
        cls.server = create_server(cls.config)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.2)  # Wait for server startup

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_root(self):
        url = f"http://127.0.0.1:{self.config.port}/"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("<!DOCTYPE html>", body)
            self.assertIn("Prompt Bridge", body)
            self.assertIn("bentoGrid", body)

    def test_get_html_bytes_matches_docs(self):
        from bridge.server import get_html_bytes, HTML_PATH
        self.assertTrue(HTML_PATH.is_file())
        self.assertEqual(get_html_bytes(), HTML_PATH.read_bytes())

    def test_get_ping(self):
        url = f"http://127.0.0.1:{self.config.port}/ping"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "ok")

    def test_get_targets(self):
        url = f"http://127.0.0.1:{self.config.port}/targets"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("targets", data)
            self.assertIn("default_target", data)
            # Focused target should be present
            targets = data["targets"]
            self.assertTrue(any(t["id"] == "focused" for t in targets))

    def test_get_terminal_tail(self):
        url = f"http://127.0.0.1:{self.config.port}/terminal/tail?target=focused&mode=ultra"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            self.assertEqual(data["mode"], "ultra")
            self.assertIn("content", data)


    def test_post_prompt_empty(self):
        url = f"http://127.0.0.1:{self.config.port}/prompt"
        payload = json.dumps({"target": "focused", "prompt": ""}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                self.fail("Expected HTTP 400")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            data = json.loads(e.read().decode("utf-8"))
            self.assertFalse(data["success"])

    def test_404_routes(self):
        url = f"http://127.0.0.1:{self.config.port}/non_existent_path"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                self.fail("Expected HTTP 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_abrupt_client_disconnect(self):
        import socket
        # Connect and immediately close socket without sending data
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.config.port))
        s.close()
        time.sleep(0.05)

        # Connect, send partial request line, and close socket abruptly
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.connect(("127.0.0.1", self.config.port))
        s2.sendall(b"POST /prompt HTTP/1.1\r\nContent-Length: 100\r\n\r\npartial")
        s2.close()
        time.sleep(0.05)

        # Server should still be healthy and responding
        url = f"http://127.0.0.1:{self.config.port}/ping"
        with urllib.request.urlopen(url) as resp:
            self.assertEqual(resp.status, 200)


class TestServerAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Config()
        cls.config.port = 18766
        cls.config.auth_token = "secret_test_token"
        cls.config.enable_legacy_paste = True
        
        cls.server = create_server(cls.config)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_unauthorized_targets(self):
        url = f"http://127.0.0.1:{self.config.port}/targets"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                self.fail("Expected HTTP 401")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

    def test_authorized_targets_with_bearer_token(self):
        url = f"http://127.0.0.1:{self.config.port}/targets"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.config.auth_token}"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("targets", data)


if __name__ == "__main__":
    unittest.main()
