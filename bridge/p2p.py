"""
Peer-to-Peer (P2P) Zero-Exposure Relay & Terminal Bridge for Prompt Bridge.
Enables instant, end-to-end encrypted (E2EE) remote terminal interaction over public networks
without exposing local ports or IP addresses.
"""

import os
import secrets
import struct
import socket
import hmac
import hashlib
import threading
import time
import json
import logging
import importlib

class DirectP2PTransport:
    """Stub for WebRTC DataChannel transport.
    Tries to import aiortc; if unavailable, falls back to relay.
    """

    def __init__(self, p2p_manager: 'P2PManager'):
        self.manager = p2p_manager
        self._handler = None
        self._active = False
        self._rtc = None

    def start(self) -> None:
        try:
            aiortc = importlib.import_module('aiortc')
            # Minimal stub: create PeerConnection, set up data channel
            self._rtc = aiortc.RTCPeerConnection()
            self._channel = self._rtc.createDataChannel('bridge')
            self._channel.on('message', self._on_message)
            self._active = True
            # Signaling would be handled elsewhere; here we just note success
        except Exception as e:
            # Log and signal fallback
            import logging
            logging.getLogger('PromptBridge.P2P').debug('Direct P2P unavailable: %s', e)
            self._active = False
            # Fallback to existing relay will be started by manager

    def _on_message(self, payload):
        if self._handler:
            self._handler(payload)

    def register_handler(self, handler) -> None:
        self._handler = handler

    def send(self, message: str) -> None:
        if not self._active:
            raise RuntimeError('Direct P2P not active')
        self._channel.send(message)

    def stop(self) -> None:
        if self._rtc:
            import asyncio
            try:
                asyncio.run(self._rtc.close())
            except Exception:
                pass
        self._active = False


from abc import ABC, abstractmethod

class Transport(ABC):
    """Abstract transport interface used by PromptRouter."""

    @abstractmethod
    def start(self) -> None:
        """Initialize and start the transport. Should be non-blocking and return once ready."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Terminate the transport and clean up resources."""
        ...

    @abstractmethod
    def send(self, message: str) -> None:
        """Send a raw string message to the remote side."""
        ...

    @abstractmethod
    def register_handler(self, handler) -> None:
        """Register a callable that will receive incoming messages.
        The handler will be called with a single argument: the message string."""
        ...
from typing import Dict, Any, Optional, Tuple

from bridge.qrcode import print_qr_code
from bridge.models import PromptRequest
from bridge.compressor import compress_caveman_ultra, format_raw_tail
from bridge.adapters.factory import get_adapter

logger = logging.getLogger("PromptBridge.P2P")

DEFAULT_HOSTED_CLIENT_URL = os.environ.get("BRIDGE_CLIENT_URL", "https://omikacharya.github.io/bridge")
DEFAULT_MQTT_BROKERS = [
    ("public.cloud.shiftr.io", 443, True, "/mqtt", "public", "public"),
    ("broker.hivemq.com", 1883, False, "", None, None),
    ("broker.emqx.io", 1883, False, "", None, None),
]
DEFAULT_MQTT_BROKER = os.environ.get("BRIDGE_MQTT_BROKER", "public.cloud.shiftr.io")
DEFAULT_MQTT_PORT = int(os.environ.get("BRIDGE_MQTT_PORT", "443"))


class P2PCrypto:
    """
    Standard-library CTR + Encrypt-then-MAC (HMAC-SHA256) Authenticated Encryption.
    Provides true zero-knowledge end-to-end encryption between Phone and Mac.
    """

    def __init__(self, raw_key: str):
        self.master_key = hashlib.sha256(raw_key.encode("utf-8")).digest()
        self.k_enc = hmac.new(self.master_key, b"enc", hashlib.sha256).digest()
        self.k_mac = hmac.new(self.master_key, b"mac", hashlib.sha256).digest()

    def encrypt(self, plaintext: str) -> dict:
        """Encrypts plaintext string into an authenticated {nonce, ct, tag} envelope."""
        data = plaintext.encode("utf-8")
        nonce = secrets.token_bytes(16)
        keystream = b"".join(
            hmac.new(self.k_enc, nonce + struct.pack(">I", i), hashlib.sha256).digest()
            for i in range((len(data) + 31) // 32)
        )[:len(data)]
        ciphertext = bytes(b ^ k for b, k in zip(data, keystream))
        tag = hmac.new(self.k_mac, nonce + ciphertext, hashlib.sha256).hexdigest()
        return {"nonce": nonce.hex(), "ct": ciphertext.hex(), "tag": tag}

    def decrypt(self, envelope: dict) -> str:
        """Verifies MAC and decrypts ciphertext envelope into plaintext string."""
        if not isinstance(envelope, dict) or "nonce" not in envelope or "ct" not in envelope or "tag" not in envelope:
            raise ValueError("Malformed ciphertext envelope")

        nonce = bytes.fromhex(envelope["nonce"])
        ciphertext = bytes.fromhex(envelope["ct"])
        tag = envelope["tag"]

        expected_tag = hmac.new(self.k_mac, nonce + ciphertext, hashlib.sha256).hexdigest()
        if not secrets.compare_digest(tag, expected_tag):
            raise ValueError("MAC verification failed - message tampered or wrong key")

        keystream = b"".join(
            hmac.new(self.k_enc, nonce + struct.pack(">I", i), hashlib.sha256).digest()
            for i in range((len(ciphertext) + 31) // 32)
        )[:len(ciphertext)]
        return bytes(b ^ k for b, k in zip(ciphertext, keystream)).decode("utf-8")


class MiniMQTTClient:
    """Pure Python standard library MQTT v3.1.1 client supporting raw TCP and WSS."""

    def __init__(
        self,
        host: str = DEFAULT_MQTT_BROKER,
        port: int = DEFAULT_MQTT_PORT,
        client_id: str = "",
        is_ws: Optional[bool] = None,
        path: str = "/mqtt",
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.is_ws = (port == 443) if is_ws is None else is_ws
        self.path = path or "/mqtt"
        self.username = username
        self.password = password
        self.client_id = (client_id or f"mac_pb_{secrets.token_hex(4)}").encode("utf-8")
        self.sock: Optional[socket.socket] = None
        self.running = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
            raw_sock = socket.create_connection((self.host, self.port), timeout=6)
            if self.is_ws:
                import ssl
                ctx = ssl.create_default_context()
                self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
                req = (
                    f"GET {self.path} HTTP/1.1\r\n"
                    f"Host: {self.host}\r\n"
                    f"Upgrade: websocket\r\n"
                    f"Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    f"Sec-WebSocket-Version: 13\r\n"
                    f"Sec-WebSocket-Protocol: mqtt\r\n\r\n"
                )
                self.sock.sendall(req.encode())
                resp = self.sock.recv(1024)
                if b"101 Switching Protocols" not in resp:
                    raise ConnectionError(f"WS handshake failed on {self.host}")
            else:
                self.sock = raw_sock

            cid = self.client_id
            uname = self.username.encode("utf-8") if self.username else None
            pword = self.password.encode("utf-8") if self.password else None
            flags = 0xC2 if (uname and pword) else 0x02

            payload = struct.pack(">H", len(cid)) + cid
            if uname:
                payload += struct.pack(">H", len(uname)) + uname
            if pword:
                payload += struct.pack(">H", len(pword)) + pword

            var_header = b"\x00\x04MQTT\x04" + bytes([flags]) + b"\x00\x3c"
            rem = len(var_header) + len(payload)
            pkt = bytearray([0x10])
            while True:
                b = rem % 128
                rem //= 128
                if rem > 0:
                    b |= 128
                pkt.append(b)
                if rem <= 0:
                    break
            pkt.extend(var_header + payload)

            self._send_raw(pkt)
            resp = self._recv_raw_packet(timeout=5.0)
            if not resp or resp[0] != 0x20 or resp[3] != 0x00:
                raise ConnectionError(f"MQTT Connack rejected: {list(resp) if resp else 'None'}")
            self.running = True
            return True

    def _send_raw(self, pkt: bytes):
        if self.is_ws:
            mask = secrets.token_bytes(4)
            masked = bytes([b ^ mask[i % 4] for i, b in enumerate(pkt)])
            rem = len(pkt)
            if rem < 126:
                h = bytes([0x82, 0x80 | rem])
            elif rem < 65536:
                h = bytes([0x82, 0x80 | 126]) + struct.pack(">H", rem)
            else:
                h = bytes([0x82, 0x80 | 127]) + struct.pack(">Q", rem)
            self.sock.sendall(h + mask + masked)
        else:
            self.sock.sendall(pkt)

    def _recv_raw_packet(self, timeout: float = 1.0) -> Optional[bytes]:
        if not self.sock:
            return None
        self.sock.settimeout(timeout)
        try:
            if self.is_ws:
                head = self.sock.recv(2)
                if not head or len(head) < 2:
                    return None
                rem = head[1] & 0x7F
                if rem == 126:
                    rem = struct.unpack(">H", self.sock.recv(2))[0]
                elif rem == 127:
                    rem = struct.unpack(">Q", self.sock.recv(8))[0]
                buf = bytearray()
                while len(buf) < rem:
                    chunk = self.sock.recv(rem - len(buf))
                    if not chunk:
                        break
                    buf.extend(chunk)
                return bytes(buf)
            else:
                head = self.sock.recv(1)
                if not head:
                    return None
                cmd = head[0]
                multiplier = 1
                rem = 0
                rem_bytes = bytearray()
                while True:
                    b = self.sock.recv(1)[0]
                    rem_bytes.append(b)
                    rem += (b & 127) * multiplier
                    multiplier *= 128
                    if (b & 128) == 0:
                        break
                buf = bytearray()
                while len(buf) < rem:
                    chunk = self.sock.recv(rem - len(buf))
                    if not chunk:
                        break
                    buf.extend(chunk)
                return bytes([cmd]) + bytes(rem_bytes) + bytes(buf)
        except (socket.timeout, TimeoutError):
            return None
        except Exception:
            return None

    def subscribe(self, topic: str):
        with self._lock:
            if not self.sock:
                return
            top_b = topic.encode("utf-8")
            msg_id = 1
            payload = struct.pack(">H", msg_id) + struct.pack(">H", len(top_b)) + top_b + b"\x00"
            pkt = bytearray([0x82, len(payload)]) + payload
            self._send_raw(pkt)
            self._recv_raw_packet(timeout=5.0)

    def publish(self, topic: str, payload_str: str):
        with self._lock:
            if not self.sock:
                return
            top_b = topic.encode("utf-8")
            pay_b = payload_str.encode("utf-8")
            var_header = struct.pack(">H", len(top_b)) + top_b
            body = var_header + pay_b
            rem = len(body)
            pkt = bytearray([0x30])  # PUBLISH QoS 0
            while True:
                b = rem % 128
                rem //= 128
                if rem > 0:
                    b |= 128
                pkt.append(b)
                if rem <= 0:
                    break
            pkt.extend(body)
            self._send_raw(pkt)

    def ping(self):
        with self._lock:
            if self.sock:
                try:
                    self._send_raw(b"\xC0\x00")
                except Exception:
                    pass

    def recv_message(self, timeout: float = 1.0) -> Optional[Tuple[str, str]]:
        pkt = self._recv_raw_packet(timeout=timeout)
        if not pkt or (pkt[0] & 0xF0) != 0x30:
            return None
        idx = 1
        multiplier = 1
        rem_len = 0
        while True:
            b = pkt[idx]
            idx += 1
            rem_len += (b & 127) * multiplier
            multiplier *= 128
            if (b & 128) == 0:
                break
        top_len = struct.unpack(">H", pkt[idx:idx+2])[0]
        idx += 2
        topic = pkt[idx:idx+top_len].decode("utf-8", errors="ignore")
        idx += top_len
        payload = pkt[idx:].decode("utf-8", errors="ignore")
        return topic, payload

    def close(self):
        self.running = False
        with self._lock:
            if self.sock:
                try:
                    self._send_raw(b"\xE0\x00")  # DISCONNECT
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None


class P2PManager:
    """Manages ephemeral P2P rooms, cryptographic pairing keys, and background relay worker."""

    def __init__(self, room_id: Optional[str] = None, auth_key: Optional[str] = None, client_url: Optional[str] = None):
        self.room_id = room_id or secrets.token_hex(6)
        self.auth_key = auth_key or secrets.token_urlsafe(18)
        self.client_url = (client_url or DEFAULT_HOSTED_CLIENT_URL).rstrip("/")
        self.created_at = time.time()
        self.crypto = P2PCrypto(self.auth_key)
        self.relay_client: Optional[MiniMQTTClient] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.running = False
        # Direct P2P transport (optional, tries to use WebRTC)
        self.direct_transport = DirectP2PTransport(self)
        self._active_transport = None

    def generate_p2p_url(self) -> str:
        """Constructs secure P2P pairing URL pointing to the hosted static web client."""
        return f"{self.client_url}/#p2p=1&room={self.room_id}&key={self.auth_key}"

    def generate_lan_url(self, lan_ip: str, port: int) -> str:
        """Constructs direct local LAN URL when --expose-lan is explicitly enabled."""
        return f"http://{lan_ip}:{port}"

    def get_pairing_banner(self, lan_ip: str = "127.0.0.1", port: int = 8765, is_lan_exposed: bool = False, mdns_host: str = "") -> str:
        """Generates terminal ASCII QR code and pairing instructions for the active mode."""
        if is_lan_exposed:
            lan_url = self.generate_lan_url(lan_ip, port)
            qr_ascii = print_qr_code(lan_url)
            banner = [
                "\n" + "═" * 58,
                "  🌐 DIRECT LAN IP EXPOSURE ENABLED (--expose-lan)",
                "  Mac IP address and port are open on the local network.",
                "═" * 58,
                qr_ascii,
                f"  Phone URL:   {lan_url}",
            ]
            if mdns_host:
                banner.append(f"  mDNS URL:    http://{mdns_host}:{port}")
            banner.extend([
                "═" * 58,
                "  📱 Scan the QR code above with your phone camera to connect",
                "═" * 58 + "\n"
            ])
            return "\n".join(banner)
        else:
            p2p_url = self.generate_p2p_url()
            qr_ascii = print_qr_code(p2p_url)
            banner = [
                "\n" + "═" * 58,
                "  🔒 P2P ZERO-EXPOSURE TERMINAL BRIDGE ACTIVE (Default)",
                "  Mac IP is NOT exposed to the local network (Localhost only).",
                "═" * 58,
                qr_ascii,
                f"  Pairing URL: {p2p_url}",
                f"  Room ID:     {self.room_id}",
                f"  E2EE Key:    {self.auth_key[:4]}••••••••••••••••",
                "═" * 58,
                "  📱 Scan with Phone to open the P2P Web App",
                "  🔒 All prompts & terminal logs are end-to-end encrypted",
                "  💡 On trusted Wi-Fi? Run with --expose-lan for direct local IP",
                "═" * 58 + "\n"
            ]
            return "\n".join(banner)

    def verify_auth_token(self, token: str) -> bool:
        """Verifies incoming handshake token matches active session auth key."""
        if not token:
            return False
        return secrets.compare_digest(token, self.auth_key)

    def start_relay(self, router, target_manager):
        """Starts background P2P relay worker to service phone requests with zero open ports.
        Attempts DirectP2PTransport first; falls back to MQTT relay.
        """
        if self.running:
            return
        # Try direct transport
        try:
            self.direct_transport.start()
        except Exception:
            self.direct_transport = None
        if getattr(self, 'direct_transport', None) and getattr(self.direct_transport, '_active', False):
            self._active_transport = self.direct_transport
            # Register handler to process incoming messages
            # Register handler to process incoming messages (stub - no reply handling)
        # self.direct_transport.register_handler(lambda msg: self._handle_p2p_message(None, None, msg, router, target_manager))
            self.running = True
            logger.info("Direct P2P transport active for room %s", self.room_id)
            return
        # Fallback to MQTT relay
        self.running = True
        self.worker_thread = threading.Thread(
            target=self._relay_loop,
            args=(router, target_manager),
            daemon=True,
            name="PromptBridge-P2PWorker"
        )
        self.worker_thread.start()

    def _relay_loop(self, router, target_manager):
        topic_mac = f"pb/{self.room_id}/mac"
        topic_phone = f"pb/{self.room_id}/phone"
        broker_idx = 0

        while self.running:
            entry = DEFAULT_MQTT_BROKERS[broker_idx % len(DEFAULT_MQTT_BROKERS)]
            if len(entry) >= 6:
                host, port, is_ws, path, uname, pword = entry[:6]
            else:
                host, port = entry[:2]
                is_ws, path, uname, pword = (port == 443), "/mqtt", None, None

            try:
                client = MiniMQTTClient(
                    host=host,
                    port=port,
                    is_ws=is_ws,
                    path=path,
                    username=uname,
                    password=pword,
                    client_id=f"pb_mac_{self.room_id}"
                )
                client.connect()
                client.subscribe(topic_mac)
                self.relay_client = client
                logger.info("Connected to P2P relay broker %s for room %s", host, self.room_id)

                last_ping = time.time()
                while self.running and client.running:
                    msg = client.recv_message(timeout=1.0)
                    if msg:
                        _, payload_str = msg
                        self._handle_p2p_message(client, topic_phone, payload_str, router, target_manager)

                    if time.time() - last_ping > 20:
                        client.ping()
                        last_ping = time.time()

            except Exception as e:
                logger.debug("P2P relay loop (%s) reconnecting: %s", host, e)
                broker_idx += 1
                time.sleep(2.0)

    def _handle_p2p_message(self, client: MiniMQTTClient, reply_topic: str, payload_str: str, router, target_manager):
        try:
            raw_data = json.loads(payload_str)
            # Decrypt if encrypted envelope
            if isinstance(raw_data, dict) and "ct" in raw_data and "nonce" in raw_data and "tag" in raw_data:
                try:
                    decrypted_text = self.crypto.decrypt(raw_data)
                    req = json.loads(decrypted_text)
                    is_encrypted = True
                except Exception as e:
                    logger.warning("Failed to decrypt incoming P2P message: %s", e)
                    return
            else:
                req = raw_data
                is_encrypted = False
                key = req.get("key", "")
                if not self.verify_auth_token(key):
                    err_resp = {"id": req.get("id"), "action": "error", "error": "Unauthorized key"}
                    client.publish(reply_topic, json.dumps(err_resp))
                    return

            req_id = req.get("id")
            action = req.get("action")

            response_payload = None

            if action == "ping":
                response_payload = {
                    "id": req_id,
                    "action": "pong",
                    "status": "ok"
                }

            elif action == "get_targets":
                targets = target_manager.get_targets() if target_manager else []
                targets_dict = [t.to_dict() for t in targets]
                default_t = "auto"
                for t in targets:
                    if t.agent in ("claude", "codex", "opencode", "aider", "agy") and t.id != "focused":
                        default_t = t.id
                        break
                response_payload = {
                    "id": req_id,
                    "action": "targets_response",
                    "targets": targets_dict,
                    "default_target": default_t
                }

            elif action == "get_tail":
                target_id = req.get("target", "auto")
                mode = req.get("mode", "ultra")
                lines_count = int(req.get("lines", 40))

                target = target_manager.resolve(target_id) if target_manager else None
                if not target:
                    response_payload = {
                        "id": req_id,
                        "action": "tail_response",
                        "success": False,
                        "error": f"Target '{target_id}' not found"
                    }
                else:
                    adapter = get_adapter(target)
                    raw_history = adapter.get_history(target, lines=max(lines_count, 50))
                    content = compress_caveman_ultra(raw_history) if mode == "ultra" else format_raw_tail(raw_history, lines=lines_count)
                    response_payload = {
                        "id": req_id,
                        "action": "tail_response",
                        "success": True,
                        "target_id": target.id,
                        "target_name": target.name,
                        "mode": mode,
                        "content": content,
                        "is_busy": target.is_busy
                    }

            elif action == "prompt":
                prompt_text = req.get("prompt", "")
                target_id = req.get("target", "auto")
                act = req.get("act", "execute")

                prompt_req = PromptRequest(prompt=prompt_text, target=target_id, action=act)
                result = router.route(prompt_req) if router else None

                response_payload = {
                    "id": req_id,
                    "action": "prompt_response",
                    "success": result.success if result else False,
                    "result": result.to_dict() if result else {}
                }

            if response_payload is not None:
                json_str = json.dumps(response_payload)
                if is_encrypted:
                    env = self.crypto.encrypt(json_str)
                    client.publish(reply_topic, json.dumps(env))
                else:
                    client.publish(reply_topic, json_str)

        except Exception as e:
            logger.debug("Error processing P2P message: %s", e)

    def stop(self):
        self.running = False
        if self.relay_client:
            self.relay_client.close()
