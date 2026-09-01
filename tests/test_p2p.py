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
        p2p_url = p2p.generate_p2p_url()
        self.assertIn("https://omikacharya.github.io/bridge/#p2p=1&room=room123&key=secretkey_xyz", p2p_url)

        lan_url = p2p.generate_lan_url("192.168.1.5", 8765)
        self.assertEqual(lan_url, "http://192.168.1.5:8765")

        p2p_banner = p2p.get_pairing_banner(is_lan_exposed=False)
        self.assertIn("P2P ZERO-EXPOSURE", p2p_banner)
        self.assertIn("https://omikacharya.github.io/bridge", p2p_banner)

        lan_banner = p2p.get_pairing_banner(lan_ip="192.168.1.5", port=8765, is_lan_exposed=True)
        self.assertIn("DIRECT LAN IP EXPOSURE", lan_banner)
        self.assertIn("http://192.168.1.5:8765", lan_banner)

        self.assertTrue(p2p.verify_auth_token("secretkey_xyz"))
        self.assertFalse(p2p.verify_auth_token("wrong_key"))

    def test_p2p_crypto_e2ee_roundtrip_and_tamper(self):
        from bridge.p2p import P2PCrypto
        crypto = P2PCrypto("my_e2ee_shared_key_123")
        payload = json.dumps({"action": "prompt", "prompt": "pytest", "target": "auto"})

        # 1. Encrypt and decrypt roundtrip
        envelope = crypto.encrypt(payload)
        self.assertIn("nonce", envelope)
        self.assertIn("ct", envelope)
        self.assertIn("tag", envelope)
        decrypted = crypto.decrypt(envelope)
        self.assertEqual(decrypted, payload)

        # 2. Tampered ciphertext must raise ValueError
        tampered_env = dict(envelope)
        # Flip a hex character in ct
        orig_ct = tampered_env["ct"]
        tampered_env["ct"] = ("0" if orig_ct[0] != "0" else "1") + orig_ct[1:]
        with self.assertRaises(ValueError):
            crypto.decrypt(tampered_env)

        # 3. Tampered nonce must raise ValueError
        tampered_nonce_env = dict(envelope)
        orig_nonce = tampered_nonce_env["nonce"]
        tampered_nonce_env["nonce"] = ("0" if orig_nonce[0] != "0" else "1") + orig_nonce[1:]
        with self.assertRaises(ValueError):
            crypto.decrypt(tampered_nonce_env)

        # 4. Wrong key must raise ValueError
        wrong_crypto = P2PCrypto("attacker_key_999")
        with self.assertRaises(ValueError):
            wrong_crypto.decrypt(envelope)

    def test_p2p_message_handling(self):
        from bridge.discovery import SessionDiscovery
        from bridge.targets import TargetManager
        from bridge.adapters.factory import AdapterFactory
        from bridge.router import PromptRouter
        from bridge.p2p import P2PCrypto

        cfg = Config()
        discovery = SessionDiscovery()
        target_manager = TargetManager(discovery=discovery, config=cfg)
        adapter_factory = AdapterFactory()
        router = PromptRouter(target_manager=target_manager, adapter_factory=adapter_factory)

        p2p = P2PManager(room_id="room123", auth_key="key123")
        phone_crypto = P2PCrypto("key123")

        class MockClient:
            def __init__(self):
                self.published = []
            def publish(self, topic, payload):
                self.published.append((topic, json.loads(payload)))

        mock_client = MockClient()

        # 1. Test encrypted ping request and encrypted pong response
        enc_ping = phone_crypto.encrypt(json.dumps({"id": 10, "action": "ping"}))
        p2p._handle_p2p_message(mock_client, "pb/room123/phone", json.dumps(enc_ping), router, target_manager)
        self.assertEqual(len(mock_client.published), 1)
        resp_env = mock_client.published[0][1]
        decrypted_resp = json.loads(phone_crypto.decrypt(resp_env))
        self.assertEqual(decrypted_resp["action"], "pong")
        self.assertEqual(decrypted_resp["id"], 10)

        # 2. Test encrypted get_targets
        enc_targets_req = phone_crypto.encrypt(json.dumps({"id": 11, "action": "get_targets"}))
        p2p._handle_p2p_message(mock_client, "pb/room123/phone", json.dumps(enc_targets_req), router, target_manager)
        self.assertEqual(len(mock_client.published), 2)
        resp_targets_env = mock_client.published[1][1]
        dec_targets = json.loads(phone_crypto.decrypt(resp_targets_env))
        self.assertEqual(dec_targets["action"], "targets_response")
        self.assertEqual(dec_targets["id"], 11)

        # 3. Test tampered ciphertext rejected without response
        tampered = dict(enc_ping)
        tampered["ct"] = "00" + tampered["ct"][2:]
        p2p._handle_p2p_message(mock_client, "pb/room123/phone", json.dumps(tampered), router, target_manager)
        # Message count should remain 2 (tampered message discarded)
        self.assertEqual(len(mock_client.published), 2)


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
