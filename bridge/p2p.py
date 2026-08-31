"""
Peer-to-Peer (P2P) WebRTC & Zero-Exposure Manager for Prompt Bridge.
Enables end-to-end encrypted direct data channels between mobile devices and terminals
without exposing ports to public untrusted networks.
"""

import os
import secrets
import json
import time
from typing import Dict, Any, Optional
from bridge.qrcode import print_qr_code


DEFAULT_HOSTED_CLIENT_URL = os.environ.get("BRIDGE_CLIENT_URL", "https://omikacharya.github.io/bridge")


class P2PManager:
    """Manages ephemeral P2P rooms, cryptographic pairing keys, and WebRTC signaling."""

    def __init__(self, room_id: Optional[str] = None, auth_key: Optional[str] = None, client_url: Optional[str] = None):
        self.room_id = room_id or secrets.token_hex(6)
        self.auth_key = auth_key or secrets.token_urlsafe(18)
        self.client_url = (client_url or DEFAULT_HOSTED_CLIENT_URL).rstrip("/")
        self.created_at = time.time()
        self.signaling_messages: Dict[str, list] = {}
        self.peer_connected = False

    def generate_p2p_url(self) -> str:
        """Constructs secure P2P pairing URL on the hosted static web client."""
        return f"{self.client_url}/#p2p=1&room={self.room_id}&key={self.auth_key}"

    def generate_lan_url(self, lan_ip: str, port: int) -> str:
        """Constructs direct local LAN URL when --expose-lan is explicitly enabled."""
        return f"http://{lan_ip}:{port}"

    def generate_pairing_url(self, base_url: str) -> str:
        """Legacy helper for backwards compatibility."""
        clean_base = base_url.rstrip("/")
        return f"{clean_base}/#p2p=1&room={self.room_id}&key={self.auth_key}"

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

    def post_signal(self, sender: str, payload: Dict[str, Any]):
        """Queues an SDP offer, answer, or ICE candidate for the peer."""
        target = "phone" if sender == "host" else "host"
        if target not in self.signaling_messages:
            self.signaling_messages[target] = []
        self.signaling_messages[target].append({
            "sender": sender,
            "payload": payload,
            "timestamp": time.time()
        })

    def get_signals(self, receiver: str) -> list:
        """Fetches and clears queued signaling messages for the receiver."""
        messages = self.signaling_messages.get(receiver, [])
        self.signaling_messages[receiver] = []
        return messages

    def verify_auth_token(self, token: str) -> bool:
        """Verifies incoming handshake token matches active session auth key."""
        if not token:
            return False
        return secrets.compare_digest(token, self.auth_key)
