"""
Unit tests for P2P WebRTC & Zero-Exposure QR pairing.
"""

import unittest
import urllib.request
import json
from bridge.qrcode import QRCode, print_qr_code
from bridge.p2p import P2PManager
from bridge.config import Config
from bridge.server import create_server


class TestP2PAndQR(unittest.TestCase):

    def test_qr_code_generation(self):
        qr = QRCode("https://example.com/#p2p=1&room=abc123")
        self.assertGreater(qr.size, 20)
        self.assertGreater(len(qr.matrix), 20)
        ascii_qr = qr.to_terminal(quiet_zone=1)
        self.assertIn("█", ascii_qr)

    def test_p2p_manager_pairing_url_and_auth(self):
        p2p = P2PManager(room_id="room123", auth_key="secretkey_xyz")
        url = p2p.generate_pairing_url("http://192.168.1.5:8765")
        self.assertIn("#p2p=1&room=room123&key=secretkey_xyz", url)

        self.assertTrue(p2p.verify_auth_token("secretkey_xyz"))
        self.assertFalse(p2p.verify_auth_token("wrong_key"))

    def test_p2p_signaling_exchange(self):
        p2p = P2PManager(room_id="room123", auth_key="key123")
        p2p.post_signal("phone", {"type": "offer", "sdp": "v=0..."})
        
        host_signals = p2p.get_signals("host")
        self.assertEqual(len(host_signals), 1)
        self.assertEqual(host_signals[0]["sender"], "phone")
        self.assertEqual(host_signals[0]["payload"]["type"], "offer")

        # Second poll should be empty
        self.assertEqual(len(p2p.get_signals("host")), 0)


class TestP2PServerEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import threading
        cls.config = Config()
        cls.config.port = 8799
        cls.p2p_manager = P2PManager(room_id="testroom", auth_key="testkey123")
        cls.server = create_server(cls.config, p2p_manager=cls.p2p_manager)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    def setUp(self):
        from bridge.server import BridgeRequestHandler
        BridgeRequestHandler.p2p_manager = self.p2p_manager

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_get_p2p_info(self):
        res = urllib.request.urlopen("http://127.0.0.1:8799/p2p/info")
        self.assertEqual(res.status, 200)
        data = json.loads(res.read().decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("room"), "testroom")
        self.assertIn("stun:stun.l.google.com:19302", data.get("stun"))

    def test_p2p_signal_and_poll(self):
        # Post signal from phone with auth key
        req = urllib.request.Request(
            "http://127.0.0.1:8799/p2p/signal?room=testroom&sender=phone&key=testkey123",
            data=json.dumps({"type": "offer", "sdp": "test_sdp"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        res = urllib.request.urlopen(req)
        self.assertEqual(res.status, 200)

        # Poll signals for host
        poll_res = urllib.request.urlopen("http://127.0.0.1:8799/p2p/poll?room=testroom&target=host&key=testkey123")
        poll_data = json.loads(poll_res.read().decode("utf-8"))
        self.assertTrue(poll_data.get("success"))
        self.assertEqual(len(poll_data.get("messages")), 1)

    def test_binding_default_and_exposed(self):
        cfg_default = Config()
        cfg_default.port = 8797
        server_default = create_server(cfg_default, expose_lan=False)
        self.assertEqual(server_default.server_address[0], "127.0.0.1")
        server_default.server_close()

        cfg_exposed = Config()
        cfg_exposed.port = 8796
        cfg_exposed.expose_lan = True
        server_exposed = create_server(cfg_exposed, expose_lan=True)
        self.assertEqual(server_exposed.server_address[0], "0.0.0.0")
        server_exposed.server_close()
