"""
End-to-End integration tests for P2P Zero-Exposure relay and E2EE cryptography.
Verifies cross-language WebCrypto compatibility, encrypted prompt delivery,
tamper resistance, and room cryptographic isolation.
"""

import unittest
import json
import subprocess
import os
from unittest.mock import MagicMock, patch

from bridge.config import Config
from bridge.p2p import P2PManager, P2PCrypto
from bridge.models import Target, PromptRequest, DeliveryResult
from bridge.router import PromptRouter
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory
from bridge.discovery import SessionDiscovery


class TestP2PEndToEndE2EE(unittest.TestCase):

    def setUp(self):
        self.config = Config()
        self.discovery = MagicMock(spec=SessionDiscovery)
        self.target_manager = TargetManager(discovery=self.discovery, config=self.config)
        self.adapter_factory = MagicMock(spec=AdapterFactory)
        self.mock_adapter = MagicMock()
        self.mock_adapter.name = "MockAppleTerminal"
        self.mock_adapter.send.return_value = DeliveryResult(
            success=True,
            target_id="claude-backend",
            target_name="Claude Code — backend",
            adapter_used="MockAppleTerminal",
            message="Delivered directly to session"
        )
        self.mock_adapter.get_history.return_value = "Line 1\nLine 2\nDone test."
        self.adapter_factory.get_adapter.return_value = self.mock_adapter

        self.router = PromptRouter(target_manager=self.target_manager, adapter_factory=self.adapter_factory)

        self.target = Target(
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
        self.discovery.get_active_targets.return_value = [self.target]

        self.room_id = "testroom_42"
        self.auth_key = "secret_e2ee_token_987654321"
        self.manager = P2PManager(room_id=self.room_id, auth_key=self.auth_key)
        self.client_crypto = P2PCrypto(self.auth_key)

    def test_e2ee_prompt_delivery_roundtrip(self):
        """Client encrypts prompt -> Host decrypts and executes -> Host encrypts result -> Client decrypts."""
        class MockRelayClient:
            def __init__(self):
                self.published_messages = []
            def publish(self, topic, payload):
                self.published_messages.append((topic, json.loads(payload)))

        relay_client = MockRelayClient()

        # 1. Phone prepares prompt request
        prompt_req = {
            "id": 101,
            "action": "prompt",
            "prompt": "run unit tests",
            "target": "claude-backend",
            "act": "execute"
        }
        encrypted_req_envelope = self.client_crypto.encrypt(json.dumps(prompt_req))

        # 2. Host receives and handles encrypted message from phone topic
        self.manager._handle_p2p_message(
            client=relay_client,
            reply_topic=f"pb/{self.room_id}/phone",
            payload_str=json.dumps(encrypted_req_envelope),
            router=self.router,
            target_manager=self.target_manager
        )

        # 3. Verify host published encrypted reply to phone topic
        self.assertEqual(len(relay_client.published_messages), 1)
        topic, encrypted_resp_envelope = relay_client.published_messages[0]
        self.assertEqual(topic, f"pb/{self.room_id}/phone")

        # 4. Phone decrypts response
        decrypted_json = self.client_crypto.decrypt(encrypted_resp_envelope)
        resp_data = json.loads(decrypted_json)

        self.assertEqual(resp_data["id"], 101)
        self.assertEqual(resp_data["action"], "prompt_response")
        self.assertTrue(resp_data["success"])
        self.assertEqual(resp_data["result"]["target_id"], "claude-backend")

        # Verify router and adapter were called with exact decrypted text
        self.mock_adapter.send.assert_called_once_with(
            target=self.target,
            text="run unit tests",
            action="execute"
        )

    def test_e2ee_tail_fetch_roundtrip(self):
        """Client requests encrypted activity log tail -> Host compresses and returns encrypted tail."""
        class MockRelayClient:
            def __init__(self):
                self.published_messages = []
            def publish(self, topic, payload):
                self.published_messages.append((topic, json.loads(payload)))

        relay_client = MockRelayClient()

        tail_req = {
            "id": 102,
            "action": "get_tail",
            "target": "claude-backend",
            "mode": "raw",
            "lines": 30
        }
        enc_req = self.client_crypto.encrypt(json.dumps(tail_req))

        with patch("bridge.p2p.get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.get_history.return_value = "Line 1\nLine 2\nDone test."
            mock_get_adapter.return_value = mock_adapter

            self.manager._handle_p2p_message(
                client=relay_client,
                reply_topic=f"pb/{self.room_id}/phone",
                payload_str=json.dumps(enc_req),
                router=self.router,
                target_manager=self.target_manager
            )

        self.assertEqual(len(relay_client.published_messages), 1)
        _, enc_resp = relay_client.published_messages[0]
        dec_resp = json.loads(self.client_crypto.decrypt(enc_resp))

        self.assertEqual(dec_resp["id"], 102)
        self.assertEqual(dec_resp["action"], "tail_response")
        self.assertTrue(dec_resp["success"])
        self.assertIn("Line 1", dec_resp["content"])

    def test_e2ee_tamper_mitm_rejection(self):
        """If intermediate relay modifies any byte of ciphertext or nonce, MAC failure triggers zero response."""
        class MockRelayClient:
            def __init__(self):
                self.published_messages = []
            def publish(self, topic, payload):
                self.published_messages.append((topic, json.loads(payload)))

        relay_client = MockRelayClient()

        req = {"id": 103, "action": "ping"}
        valid_envelope = self.client_crypto.encrypt(json.dumps(req))

        # MITM attacker flips single character in ciphertext
        tampered_envelope = dict(valid_envelope)
        c = tampered_envelope["ct"]
        tampered_envelope["ct"] = ("ff" if c[:2] != "ff" else "00") + c[2:]

        self.manager._handle_p2p_message(
            client=relay_client,
            reply_topic=f"pb/{self.room_id}/phone",
            payload_str=json.dumps(tampered_envelope),
            router=self.router,
            target_manager=self.target_manager
        )

        # Host must discard tampered message and never publish
        self.assertEqual(len(relay_client.published_messages), 0)

    def test_e2ee_room_isolation_different_keys(self):
        """Client with wrong key cannot decrypt messages from room."""
        req = {"id": 104, "action": "ping"}
        envelope = self.client_crypto.encrypt(json.dumps(req))

        different_key_crypto = P2PCrypto("different_unauthorized_key_999")
        with self.assertRaises(ValueError):
            different_key_crypto.decrypt(envelope)

    def test_cross_language_webcrypto_node_interoperability(self):
        """Verifies Python E2EE encryption can be decrypted by Node WebCrypto and vice versa."""
        node_script = '''
        const { subtle } = globalThis.crypto;
        const rawKey = "shared_test_key_xyz";
        const enc = new TextEncoder();
        const dec = new TextDecoder();

        async function initCrypto() {
            const masterDigest = await subtle.digest('SHA-256', enc.encode(rawKey));
            const masterKey = await subtle.importKey('raw', masterDigest, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
            const kEncBytes = await subtle.sign('HMAC', masterKey, enc.encode('enc'));
            const kMacBytes = await subtle.sign('HMAC', masterKey, enc.encode('mac'));
            const kEnc = await subtle.importKey('raw', kEncBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
            const kMac = await subtle.importKey('raw', kMacBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
            return { kEnc, kMac };
        }

        async function decryptEnv(env, { kEnc, kMac }) {
            const nonce = new Uint8Array(env.nonce.match(/.{1,2}/g).map(b => parseInt(b, 16)));
            const ct = new Uint8Array(env.ct.match(/.{1,2}/g).map(b => parseInt(b, 16)));
            const macInput = new Uint8Array(nonce.length + ct.length);
            macInput.set(nonce, 0);
            macInput.set(ct, nonce.length);
            const tagBytes = await subtle.sign('HMAC', kMac, macInput);
            const expectedTag = Array.from(new Uint8Array(tagBytes)).map(b => b.toString(16).padStart(2, '0')).join('');
            if (expectedTag !== env.tag) throw new Error('MAC mismatch');

            const numBlocks = Math.ceil(ct.length / 32);
            const ksChunks = [];
            for (let i = 0; i < numBlocks; i++) {
                const ctr = new Uint8Array(20);
                ctr.set(nonce, 0);
                new DataView(ctr.buffer).setUint32(16, i, false);
                const block = await subtle.sign('HMAC', kEnc, ctr);
                ksChunks.push(new Uint8Array(block));
            }
            const totalKs = new Uint8Array(numBlocks * 32);
            let off = 0;
            for (const c of ksChunks) { totalKs.set(c, off); off += c.length; }
            const pt = new Uint8Array(ct.length);
            for (let i = 0; i < ct.length; i++) pt[i] = ct[i] ^ totalKs[i];
            return dec.decode(pt);
        }

        async function encryptText(text, { kEnc, kMac }) {
            const data = enc.encode(text);
            const nonce = new Uint8Array(16);
            globalThis.crypto.getRandomValues(nonce);
            const numBlocks = Math.ceil(data.length / 32);
            const ksChunks = [];
            for (let i = 0; i < numBlocks; i++) {
                const ctr = new Uint8Array(20);
                ctr.set(nonce, 0);
                new DataView(ctr.buffer).setUint32(16, i, false);
                const block = await subtle.sign('HMAC', kEnc, ctr);
                ksChunks.push(new Uint8Array(block));
            }
            const totalKs = new Uint8Array(numBlocks * 32);
            let off = 0;
            for (const c of ksChunks) { totalKs.set(c, off); off += c.length; }
            const ct = new Uint8Array(data.length);
            for (let i = 0; i < data.length; i++) ct[i] = data[i] ^ totalKs[i];
            const macInput = new Uint8Array(nonce.length + ct.length);
            macInput.set(nonce, 0);
            macInput.set(ct, nonce.length);
            const tagBytes = await subtle.sign('HMAC', kMac, macInput);
            const tagHex = Array.from(new Uint8Array(tagBytes)).map(b => b.toString(16).padStart(2, '0')).join('');
            const nonceHex = Array.from(nonce).map(b => b.toString(16).padStart(2, '0')).join('');
            const ctHex = Array.from(ct).map(b => b.toString(16).padStart(2, '0')).join('');
            return { nonce: nonceHex, ct: ctHex, tag: tagHex };
        }

        (async () => {
            const keys = await initCrypto();
            const inputArg = process.argv.find(a => a.startsWith('{'));
            const inputEnv = JSON.parse(inputArg);
            const decFromPy = await decryptEnv(inputEnv, keys);
            const encFromNode = await encryptText("Reply from Node WebCrypto: " + decFromPy, keys);
            console.log(JSON.stringify(encFromNode));
        })().catch(err => { console.error(err); process.exit(1); });
        '''

        py_crypto = P2PCrypto("shared_test_key_xyz")
        py_envelope = py_crypto.encrypt("Hello from Python E2EE!")

        node_proc = subprocess.run(
            ["node", "-e", node_script, json.dumps(py_envelope)],
            capture_output=True,
            text=True,
            timeout=5.0
        )
        self.assertEqual(node_proc.returncode, 0, f"Node process failed: {node_proc.stderr}")

        node_envelope = json.loads(node_proc.stdout.strip())
        decrypted_in_py = py_crypto.decrypt(node_envelope)
        self.assertEqual(decrypted_in_py, "Reply from Node WebCrypto: Hello from Python E2EE!")


if __name__ == "__main__":
    unittest.main()
