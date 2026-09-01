# Architecture Ideation: Peer-to-Peer (P2P) Zero-Exposure Remote Bridge

## Problem Statement
On public or untrusted networks (coffee shops, airports, cellular 5G, hotels):
1. **Security Risk**: Exposing an open listening port (`0.0.0.0:8765`) over unencrypted HTTP exposes the machine to local port scanners, packet sniffing, and prompt injection.
2. **NAT / AP Isolation**: Public Wi-Fi networks frequently enable Access Point (AP) isolation (preventing devices on the same Wi-Fi from talking to each other) and carrier-grade NAT on cellular (5G/LTE), preventing direct IP connections.

---

## Proposed P2P & Zero-Exposure Architectures

### Option 1: True P2P WebRTC DataChannel (Browser-to-Terminal)
- **Concept**: Mac binds only to `127.0.0.1` (localhost). A direct, end-to-end encrypted WebRTC DataChannel is established between Mobile Browser and Mac Terminal.
- **Workflow**:
  1. Bridge CLI boots on Mac, generates an ephemeral session key and SDP offer.
  2. CLI renders an ASCII QR code in the terminal.
  3. Phone scans QR code via camera (opening the web client with session secret in URL `#hash`).
  4. Public STUN (`stun.l.google.com:19302`) punches NAT and establishes direct DTLS-SRTP data channel.
- **Pros**:
  - **Zero open ports** on LAN or internet.
  - End-to-end encrypted (DTLS).
  - Works across 5G cellular, Wi-Fi with AP isolation, and firewalls.
  - Lowest possible latency (<15ms direct peer socket).
- **Cons**: Requires WebRTC signaling exchange (can use ephemeral QR code or minimal Cloudflare Worker).

---

### Option 2: Outbound E2EE Cloudflare Worker Relay (Zero-Knowledge)
- **Concept**: Both Mac and Mobile connect *outbound* via WebSockets to a lightweight, free Cloudflare Worker.
- **Workflow**:
  1. Mac server makes outbound WSS connection to relay: `wss://bridge.your-domain.workers.dev/channel/<channel-id>`.
  2. Phone opens the web app and connects to the same channel.
  3. All prompt payloads and terminal logs are encrypted client-side using `AES-GCM-256` or `X25519` with a shared key that never touches the relay (stored only in URL hash fragment `#key=...`).
- **Pros**:
  - **No inbound ports**: Mac firewall blocks all incoming connections.
  - **Zero-knowledge**: Cloudflare Worker sees only encrypted binary ciphertext.
  - 100% reliable across any cellular carrier or corporate proxy.
  - Ultra-simple: ~50 lines of Python on Mac, ~40 lines of JS in client.
- **Cons**: Relies on a free Cloudflare Worker or WebSocket relay.

---

### Option 3: Tailscale / WireGuard Private Mesh (Platform Native - Ponytail Rung 4)
- **Concept**: Use user's authenticated WireGuard overlay network (Tailscale MagicDNS).
- **Workflow**:
  1. Bridge binds to Mac's Tailscale interface (`100.x.y.z`) or runs `tailscale serve --bg 8765`.
  2. Mobile device accesses `https://macbook.tailnet.ts.net`.
- **Pros**:
  - **Zero custom code**: Native OS platform feature.
  - Automatic WireGuard encryption and device-level ACL authentication.
  - Invisible on local public Wi-Fi (no LAN IP exposed).
- **Cons**: Requires Tailscale app installed on both Mac and phone.

---

## Comparison Matrix

| Dimension | Option 1: WebRTC P2P | Option 2: E2EE Worker Relay | Option 3: Tailscale Mesh |
| :--- | :--- | :--- | :--- |
| **Inbound Port Open on Mac** | None (Localhost only) | None (Outbound WSS only) | Tailnet overlay only |
| **End-to-End Encryption** | DTLS-SRTP | AES-256-GCM | WireGuard (ChaCha20) |
| **Works on Cellular 5G** | Yes (via STUN/TURN) | Yes (100% reliable) | Yes |
| **Setup Friction** | Scan QR code | Scan QR code / Open Link | Install Tailscale App |
| **External Dependencies** | WebRTC signaling | Cloudflare Worker (Free) | Tailscale daemon |
| **Code Complexity** | Moderate | Very Low (~90 LOC total) | Zero LOC (Config only) |

---

## Recommended Roadmap

1. **Phase 1 (Instant / Zero Code)**: Support Tailscale IP & MagicDNS auto-detection in Prompt Bridge when available.
2. **Phase 2 (True Zero-Exposure / Zero-Friction)**: Build **Option 2 (E2EE Outbound Relay)** or **Option 1 (WebRTC DataChannel)**:
   - Mac terminal renders an ASCII QR code on launch.
   - Scanning the QR code with phone camera immediately opens the prompt client securely over any network without exposing local ports.
