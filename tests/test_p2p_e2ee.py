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

    def test_e2ee_get_targets_roundtrip_and_sanitization(self):
        """Client requests targets -> Host decrypts, sanitizes cmd & metadata, and responds with compact encrypted targets."""
        class MockRelayClient:
            def __init__(self):
                self.published_messages = []
            def publish(self, topic, payload):
                self.published_messages.append((topic, json.loads(payload)))

        relay_client = MockRelayClient()

        # Create target with very long cmd and excess metadata
        long_cmd_target = Target(
            id="test-long-agent",
            name="Test Long Agent",
            display_name="Test Long Agent [ttys002]",
            agent="claude",
            agent_name="Claude Code",
            cwd="/Users/mac/Projects/big",
            folder="big",
            tty="/dev/ttys002",
            cmd="python3 -m some.module.with.very.long.arguments " + "arg " * 100,
            metadata={
                "compact_cwd": "~/Projects/big",
                "short_cmd": "python3",
                "tty_short": "ttys002",
                "extra_raw_env": "A" * 5000,
                "extra_procs": [1, 2, 3] * 100
            }
        )
        self.discovery.get_active_targets.return_value = [self.target, long_cmd_target]

        req = {"id": 105, "action": "get_targets"}
        enc_req = self.client_crypto.encrypt(json.dumps(req))

        self.manager._handle_p2p_message(
            client=relay_client,
            reply_topic=f"pb/{self.room_id}/phone",
            payload_str=json.dumps(enc_req),
            router=self.router,
            target_manager=self.target_manager
        )

        self.assertEqual(len(relay_client.published_messages), 1)
        _, enc_resp = relay_client.published_messages[0]
        # Response must remain compact (< 16KB encrypted) to prevent broker packet drop
        self.assertLess(len(json.dumps(enc_resp)), 16000)

        dec_resp = json.loads(self.client_crypto.decrypt(enc_resp))
        self.assertEqual(dec_resp["id"], 105)
        self.assertEqual(dec_resp["action"], "targets_response")
        self.assertEqual(len(dec_resp["targets"]), 3)  # 2 discovered + focused fallback

        # Check sanitization: cmd <= 120 chars, raw env filtered out
        sanitized = next(t for t in dec_resp["targets"] if t["id"] == "test-long-agent")
        self.assertLessEqual(len(sanitized["cmd"]), 120)
        self.assertTrue(sanitized["cmd"].endswith("..."))
        self.assertNotIn("extra_raw_env", sanitized.get("metadata", {}))
        self.assertEqual(sanitized["metadata"].get("compact_cwd"), "~/Projects/big")

    def test_direct_p2p_transport_fallback(self):
        """DirectP2PTransport falls back safely to MQTT relay worker without preempting."""
        from bridge.p2p import DirectP2PTransport
        transport = DirectP2PTransport(self.manager)
        transport.start()
        # Direct transport should not be active without real signaling
        self.assertFalse(transport._active)
        with self.assertRaises(RuntimeError):
            transport.send("test")
        transport.stop()

    def test_mini_mqtt_client_socket_eof_handling(self):
        """MiniMQTTClient cleanly sets running=False when socket receives EOF."""
        from bridge.p2p import MiniMQTTClient
        import socket
        client = MiniMQTTClient()
        client.running = True
        # Mock socket that returns empty bytes on recv (EOF)
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.recv.return_value = b""
        client.sock = mock_sock
        chunk = client._recv_exact(10)
        self.assertIsNone(chunk)
        self.assertFalse(client.running)

    def test_mini_mqtt_client_coalesced_packets_buffering(self):
        """MiniMQTTClient parses multiple coalesced MQTT packets in buffer without extra data corruption."""
        from bridge.p2p import MiniMQTTClient
        import struct

        client = MiniMQTTClient()

        def make_publish_pkt(topic: str, payload_str: str) -> bytes:
            top_b = topic.encode("utf-8")
            pay_b = payload_str.encode("utf-8")
            body = struct.pack(">H", len(top_b)) + top_b + pay_b
            rem = len(body)
            hdr = bytearray([0x30])
            while True:
                b = rem % 128
                rem //= 128
                if rem > 0:
                    b |= 128
                hdr.append(b)
                if rem <= 0:
                    break
            return bytes(hdr) + body

        p1_json = json.dumps({"id": 1, "action": "get_targets", "key": self.auth_key})
        p2_json = json.dumps({"id": 2, "action": "get_tail", "key": self.auth_key})

        pkt1 = make_publish_pkt(f"pb/{self.room_id}/mac", p1_json)
        pkt2 = make_publish_pkt(f"pb/{self.room_id}/mac", p2_json)

        # Both packets arrive coalesced in buffer
        client._buf.extend(pkt1 + pkt2)

        # First message
        msg1 = client.recv_message(timeout=0.1)
        self.assertIsNotNone(msg1)
        top1, pay1 = msg1
        self.assertEqual(top1, f"pb/{self.room_id}/mac")
        data1 = json.loads(pay1)  # Must not raise JSONDecodeError: Extra data
        self.assertEqual(data1["id"], 1)

        # Second message
        msg2 = client.recv_message(timeout=0.1)
        self.assertIsNotNone(msg2)
        top2, pay2 = msg2
        self.assertEqual(top2, f"pb/{self.room_id}/mac")
        data2 = json.loads(pay2)  # Must not raise JSONDecodeError
        self.assertEqual(data2["id"], 2)

        self.assertEqual(len(client._buf), 0)

    def test_handle_p2p_message_trailing_data_resilience(self):
        """_handle_p2p_message handles trailing garbage via raw_decode fallback without failing."""
        class MockRelayClient:
            def __init__(self):
                self.published_messages = []
            def publish(self, topic, payload):
                self.published_messages.append((topic, json.loads(payload)))

        relay_client = MockRelayClient()
        req = {"id": 999, "action": "ping"}
        envelope = self.client_crypto.encrypt(json.dumps(req))

        # Payload with trailing extra data (such as extra characters or formatting artifact)
        malformed_payload_str = json.dumps(envelope) + "  \x30\x97extra_data"

        self.manager._handle_p2p_message(
            client=relay_client,
            reply_topic=f"pb/{self.room_id}/phone",
            payload_str=malformed_payload_str,
            router=self.router,
            target_manager=self.target_manager
        )

        self.assertEqual(len(relay_client.published_messages), 1)
        _, resp_envelope = relay_client.published_messages[0]
        resp = json.loads(self.client_crypto.decrypt(resp_envelope))
        self.assertEqual(resp["id"], 999)
        self.assertEqual(resp["action"], "pong")

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

    def test_e2ee_live_network_roundtrip(self):
        """Live end-to-end network test: Node WebCrypto/WebSocket client <-> Broker <-> Python daemon."""
        import secrets
        import time

        test_room = "e2e_live_" + secrets.token_hex(4)
        test_key = secrets.token_urlsafe(16)
        manager = P2PManager(room_id=test_room, auth_key=test_key)

        try:
            manager.start_relay(router=self.router, target_manager=self.target_manager)
            time.sleep(1.5)
            if not manager.relay_client or not manager.relay_client.running:
                self.skipTest("Live broker unreachable in test environment")

            node_test_script = """
            const { subtle } = globalThis.crypto;
            class E2EECryptoClient {
                constructor(rawKey) {
                    this.rawKey = rawKey;
                    this.readyPromise = this.init();
                }
                async init() {
                    const enc = new TextEncoder();
                    const masterDigest = await subtle.digest("SHA-256", enc.encode(this.rawKey));
                    const masterKey = await subtle.importKey("raw", masterDigest, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
                    const kEncBytes = await subtle.sign("HMAC", masterKey, enc.encode("enc"));
                    const kMacBytes = await subtle.sign("HMAC", masterKey, enc.encode("mac"));
                    this.kEnc = await subtle.importKey("raw", kEncBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
                    this.kMac = await subtle.importKey("raw", kMacBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
                }
                async encrypt(plaintext) {
                    await this.readyPromise;
                    const enc = new TextEncoder();
                    const data = enc.encode(plaintext);
                    const nonce = new Uint8Array(16);
                    globalThis.crypto.getRandomValues(nonce);
                    const numBlocks = Math.ceil(data.length / 32);
                    const ksChunks = [];
                    for (let i = 0; i < numBlocks; i++) {
                        const ctr = new Uint8Array(20);
                        ctr.set(nonce, 0);
                        new DataView(ctr.buffer).setUint32(16, i, false);
                        const block = await subtle.sign("HMAC", this.kEnc, ctr);
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
                    const tagBytes = await subtle.sign("HMAC", this.kMac, macInput);
                    const toHex = arr => Array.from(arr, b => b.toString(16).padStart(2, "0")).join("");
                    return { nonce: toHex(nonce), ct: toHex(ct), tag: toHex(new Uint8Array(tagBytes)) };
                }
                async decrypt(envelope) {
                    await this.readyPromise;
                    const dec = new TextDecoder();
                    const nonce = Uint8Array.from(envelope.nonce.match(/../g), b => parseInt(b, 16));
                    const ct = Uint8Array.from(envelope.ct.match(/../g), b => parseInt(b, 16));
                    const macInput = new Uint8Array(nonce.length + ct.length);
                    macInput.set(nonce, 0);
                    macInput.set(ct, nonce.length);
                    const tagBytes = await subtle.sign("HMAC", this.kMac, macInput);
                    const toHex = arr => Array.from(arr, b => b.toString(16).padStart(2, "0")).join("");
                    const expectedTag = toHex(new Uint8Array(tagBytes));
                    if (expectedTag !== envelope.tag) throw new Error("MAC mismatch");
                    const numBlocks = Math.ceil(ct.length / 32);
                    const ksChunks = [];
                    for (let i = 0; i < numBlocks; i++) {
                        const ctr = new Uint8Array(20);
                        ctr.set(nonce, 0);
                        new DataView(ctr.buffer).setUint32(16, i, false);
                        const block = await subtle.sign("HMAC", this.kEnc, ctr);
                        ksChunks.push(new Uint8Array(block));
                    }
                    const totalKs = new Uint8Array(numBlocks * 32);
                    let off = 0;
                    for (const c of ksChunks) { totalKs.set(c, off); off += c.length; }
                    const pt = new Uint8Array(ct.length);
                    for (let i = 0; i < ct.length; i++) pt[i] = ct[i] ^ totalKs[i];
                    return dec.decode(pt);
                }
            }
            class NanoMQTTWS {
                constructor(brokers, clientId, onMessage, onConnect, onDisconnect) {
                    this.brokers = Array.isArray(brokers) ? brokers : [brokers];
                    this.brokerIdx = 0;
                    this.clientId = clientId;
                    this.onMessage = onMessage;
                    this.onConnect = onConnect;
                    this.onDisconnect = onDisconnect;
                    this.ws = null;
                    this.enc = new TextEncoder();
                    this.dec = new TextDecoder();
                    this.connect();
                }
                connect() {
                    const item = this.brokers[this.brokerIdx % this.brokers.length];
                    const url = typeof item === "string" ? item : item.url;
                    this.username = (typeof item === "object" && item.username) ? item.username : null;
                    this.password = (typeof item === "object" && item.password) ? item.password : null;
                    this.ws = new WebSocket(url, ["mqtt"]);
                    this.ws.binaryType = "arraybuffer";
                    this.ws.onopen = () => this._sendConnect();
                    this.ws.onmessage = (e) => this._handleMessage(new Uint8Array(e.data));
                }
                _encodeLength(len) {
                    const bytes = [];
                    let num = len;
                    do {
                        let byte = num % 128;
                        num = Math.floor(num / 128);
                        if (num > 0) byte |= 128;
                        bytes.push(byte);
                    } while (num > 0);
                    return new Uint8Array(bytes);
                }
                _decodeLength(buf, offset) {
                    let multiplier = 1, value = 0, idx = offset;
                    while (idx < buf.length) {
                        const byte = buf[idx++];
                        value += (byte & 127) * multiplier;
                        multiplier *= 128;
                        if ((byte & 128) === 0) break;
                    }
                    return { length: value, nextOffset: idx };
                }
                _sendConnect() {
                    const cid = this.enc.encode(this.clientId);
                    const uname = this.username ? this.enc.encode(this.username) : null;
                    const pword = this.password ? this.enc.encode(this.password) : null;
                    const flags = (uname && pword) ? 0xC2 : 0x02;
                    const varHeader = new Uint8Array([0x00, 0x04, 0x4D, 0x51, 0x54, 0x54, 0x04, flags, 0x00, 0x3C]);
                    let payloadLen = 2 + cid.length;
                    if (uname) payloadLen += 2 + uname.length;
                    if (pword) payloadLen += 2 + pword.length;
                    const payload = new Uint8Array(payloadLen);
                    let off = 0;
                    payload[off++] = (cid.length >> 8) & 0xff; payload[off++] = cid.length & 0xff;
                    payload.set(cid, off); off += cid.length;
                    if (uname) {
                        payload[off++] = (uname.length >> 8) & 0xff; payload[off++] = uname.length & 0xff;
                        payload.set(uname, off); off += uname.length;
                    }
                    if (pword) {
                        payload[off++] = (pword.length >> 8) & 0xff; payload[off++] = pword.length & 0xff;
                        payload.set(pword, off); off += pword.length;
                    }
                    const remLen = varHeader.length + payload.length;
                    const lenBytes = this._encodeLength(remLen);
                    const pkt = new Uint8Array(1 + lenBytes.length + remLen);
                    pkt[0] = 0x10;
                    pkt.set(lenBytes, 1);
                    pkt.set(varHeader, 1 + lenBytes.length);
                    pkt.set(payload, 1 + lenBytes.length + varHeader.length);
                    this.ws.send(pkt);
                }
                subscribe(topic) {
                    const top = this.enc.encode(topic);
                    const payload = new Uint8Array(2 + 2 + top.length + 1);
                    payload[0] = 0x00; payload[1] = 0x01;
                    payload[2] = (top.length >> 8) & 0xff; payload[3] = top.length & 0xff;
                    payload.set(top, 4);
                    payload[4 + top.length] = 0x00;
                    const lenBytes = this._encodeLength(payload.length);
                    const pkt = new Uint8Array(1 + lenBytes.length + payload.length);
                    pkt[0] = 0x82;
                    pkt.set(lenBytes, 1);
                    pkt.set(payload, 1 + lenBytes.length);
                    this.ws.send(pkt);
                }
                publish(topic, payloadStr) {
                    const top = this.enc.encode(topic);
                    const pay = this.enc.encode(payloadStr);
                    const body = new Uint8Array(2 + top.length + pay.length);
                    body[0] = (top.length >> 8) & 0xff; body[1] = top.length & 0xff;
                    body.set(top, 2);
                    body.set(pay, 2 + top.length);
                    const lenBytes = this._encodeLength(body.length);
                    const pkt = new Uint8Array(1 + lenBytes.length + body.length);
                    pkt[0] = 0x30;
                    pkt.set(lenBytes, 1);
                    pkt.set(body, 1 + lenBytes.length);
                    this.ws.send(pkt);
                }
                _handleMessage(buf) {
                    const cmd = buf[0] & 0xf0;
                    if (cmd === 0x20) {
                        if (this.onConnect) this.onConnect();
                    } else if (cmd === 0x30) {
                        const { length: remLen, nextOffset: headerEnd } = this._decodeLength(buf, 1);
                        const topLen = (buf[headerEnd] << 8) | buf[headerEnd + 1];
                        const topic = this.dec.decode(buf.subarray(headerEnd + 2, headerEnd + 2 + topLen));
                        const payload = this.dec.decode(buf.subarray(headerEnd + 2 + topLen, headerEnd + remLen));
                        if (this.onMessage) this.onMessage(topic, payload);
                    }
                }
            }

            const args = process.argv.slice(1);
            const room = args[0];
            const key = args[1];
            const crypto = new E2EECryptoClient(key);

            const pendingRequests = new Map();
            let reqSeq = 1;

            async function p2pRequest(client, action, params = {}, timeoutMs = 8000) {
                const id = reqSeq++;
                const msg = Object.assign({ id, action, key }, params);
                const encrypted = await crypto.encrypt(JSON.stringify(msg));

                return new Promise((resolve, reject) => {
                    const timer = setTimeout(() => {
                        if (pendingRequests.has(id)) {
                            pendingRequests.delete(id);
                            reject(new Error(`Timeout for action ${action} (id=${id})`));
                        }
                    }, timeoutMs);

                    pendingRequests.set(id, {
                        resolve: (data) => {
                            clearTimeout(timer);
                            resolve(data);
                        }
                    });

                    client.publish(`pb/${room}/mac`, JSON.stringify(encrypted));
                });
            }

            const client = new NanoMQTTWS(
                [{ url: "wss://public.cloud.shiftr.io:443/mqtt", username: "public", password: "public" }],
                "test_node_" + Math.random().toString(16).slice(2, 8),
                async (topic, payload) => {
                    try {
                        const raw = JSON.parse(payload);
                        let data = raw;
                        if (raw && raw.ct && raw.nonce && raw.tag) {
                            const dec = await crypto.decrypt(raw);
                            data = JSON.parse(dec);
                        }
                        if (data && data.id && pendingRequests.has(data.id)) {
                            const { resolve } = pendingRequests.get(data.id);
                            pendingRequests.delete(data.id);
                            resolve(data);
                        }
                    } catch(e) {}
                },
                async () => {
                    client.subscribe(`pb/${room}/phone`);
                    try {
                        // 1. Ping
                        const pingRes = await p2pRequest(client, "ping");
                        if (pingRes.action !== "pong") throw new Error("Ping failed");

                        // 2. Targets
                        const targetsRes = await p2pRequest(client, "get_targets");
                        if (!Array.isArray(targetsRes.targets)) throw new Error("Targets failed");

                        // 3. Prompt
                        const promptRes = await p2pRequest(client, "prompt", {
                            target: "claude-backend",
                            prompt: "e2e network test prompt",
                            act: "execute"
                        });
                        if (!promptRes.success) throw new Error("Prompt failed");

                        console.log("SUCCESS");
                        process.exit(0);
                    } catch(err) {
                        console.error("NODE ERROR:", err);
                        process.exit(1);
                    }
                }
            );

            setTimeout(() => {
                console.error("NODE TIMEOUT");
                process.exit(1);
            }, 10000);
            """

            node_proc = subprocess.run(
                ["node", "-e", node_test_script, test_room, test_key],
                capture_output=True,
                text=True,
                timeout=12.0
            )
            self.assertEqual(node_proc.returncode, 0, f"Live E2E peer test failed: {node_proc.stderr}")
            self.assertIn("SUCCESS", node_proc.stdout)
        finally:
            manager.stop()



if __name__ == "__main__":
    unittest.main()
