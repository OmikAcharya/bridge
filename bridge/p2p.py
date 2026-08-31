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


class P2PManager:
    """Manages ephemeral P2P rooms, cryptographic pairing keys, and WebRTC signaling."""

    def __init__(self, room_id: Optional[str] = None, auth_key: Optional[str] = None):
        self.room_id = room_id or secrets.token_hex(6)
        self.auth_key = auth_key or secrets.token_urlsafe(18)
        self.created_at = time.time()
        self.signaling_messages: Dict[str, list] = {}
        self.peer_connected = False

    def generate_pairing_url(self, base_url: str) -> str:
        """Constructs secure pairing URL with zero-exposure fragment hash (#room=...&key=...)."""
        clean_base = base_url.rstrip("/")
        # Key in URL fragment hash is NEVER sent to server in HTTP headers (client-side only)
        return f"{clean_base}/#p2p=1&room={self.room_id}&key={self.auth_key}"

    def get_pairing_banner(self, base_url: str) -> str:
        """Generates terminal ASCII QR code and pairing instructions."""
        url = self.generate_pairing_url(base_url)
        qr_ascii = print_qr_code(url)
        
        banner = [
            "\n" + "═" * 58,
            "  🔒 P2P ZERO-EXPOSURE TERMINAL BRIDGE ACTIVE",
            "═" * 58,
            qr_ascii,
            f"  Pairing URL: {url}",
            f"  Room ID:     {self.room_id}",
            f"  E2EE Key:    {self.auth_key[:4]}••••••••••••••••",
            "═" * 58,
            "  📱 Scan the QR code above with your phone camera to pair",
            "  🔒 All prompts & logs are end-to-end encrypted (DTLS-SRTP)",
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
