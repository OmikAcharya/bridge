# Architecture Specification: Peer-to-Peer (P2P) Zero-Exposure Remote Bridge

## Problem Statement

When connecting mobile devices to local development machines over untrusted networks (public Wi-Fi, coffee shops, airports, cellular 5G):
1. **Network Exposure Risk**: Binding an unencrypted HTTP or SSH server to local network interfaces (`0.0.0.0`) exposes listening ports to local port scanning, packet sniffing, and untrusted network traffic.
2. **Access Point (AP) Isolation & NAT**: Public Wi-Fi networks frequently enable AP isolation (preventing devices on the same subnet from routing packets to each other), and cellular carrier networks enforce Carrier-Grade NAT (CGNAT), blocking direct inbound TCP connections.

---

## Architecture: Zero-Exposure End-to-End Encrypted Relay

`bridge` implements an outbound zero-knowledge relay architecture combining standard library socket transport with native browser WebCrypto:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              Mobile Client                             │
│       (Browser Native WebCrypto + WebSocket MQTT Client NanoMQTTWS)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Encrypted Payload {nonce, ct, tag}
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Public Relay Broker (WSS)                       │
│                  (broker.emqx.io / broker.hivemq.com)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Outbound Socket Connection (TCP 1883)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       macOS Host Daemon (main.py)                      │
│                  (Pure Python Stdlib MiniMQTTClient)                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Background PTY Injection
                                    ▼
                        Target Terminal Session
```

---

## Cryptographic Protocol Specification

### 1. Key Derivation & Ephemeral Rooms
- On startup, the host generates:
  - `room_id`: 12-character random hex string (`secrets.token_hex(6)`).
  - `auth_key`: 24-character URL-safe random string (`secrets.token_urlsafe(18)`).
- The key is communicated to the mobile client exclusively through the URL hash fragment:
  `https://omikacharya.github.io/bridge/#p2p=1&room=<room_id>&key=<auth_key>`
- RFC 3986 specifies that URL fragments are processed strictly client-side by the user agent and are never transmitted over HTTP request lines or server access logs.

### 2. Subkey Derivation
From the master key $K_{\text{master}}$, separate keys are derived for encryption and authentication:
- $K_{\text{digest}} = \text{SHA-256}(K_{\text{master}})$
- $K_{\text{enc}} = \text{HMAC-SHA256}(K_{\text{digest}}, \text{"enc"})$
- $K_{\text{mac}} = \text{HMAC-SHA256}(K_{\text{digest}}, \text{"mac"})$

### 3. Encryption (CTR Stream Cipher)
- For message plaintext $P$:
  - A 16-byte cryptographically secure random nonce $N$ is generated.
  - Keystream blocks are computed: $B_i = \text{HMAC-SHA256}(K_{\text{enc}}, N \mathbin{\Vert} \text{counter}_{32}(i))$ for $i \in [0, \lceil |P| / 32 \rceil - 1]$.
  - Ciphertext $C = P \oplus \text{truncate}(B_0 \mathbin{\Vert} B_1 \mathbin{\Vert} \dots, |P|)$.

### 4. Authentication (Encrypt-then-MAC)
- The authentication tag is computed over the concatenated nonce and ciphertext:
  $T = \text{HMAC-SHA256}(K_{\text{mac}}, N \mathbin{\Vert} C)$
- The resulting transport envelope is formatted as JSON:
  `{"nonce": "<hex>", "ct": "<hex>", "tag": "<hex>"}`

### 5. Decryption & Tamper Verification
- Upon receipt of an envelope $\{N, C, T\}$:
  1. Compute expected tag $T' = \text{HMAC-SHA256}(K_{\text{mac}}, N \mathbin{\Vert} C)$.
  2. Verify $T' == T$ using constant-time comparison (`secrets.compare_digest`).
  3. If verification fails, the payload is immediately dropped with zero execution or feedback.
  4. If verification passes, keystream is regenerated and ciphertext is XOR-decrypted to recover $P$.

---

## Transport Layer Mechanics

### Host Implementation (`bridge/p2p.py`)
- Uses Python standard library `socket`, `ssl`, `struct`, and `threading`.
- Implements `MiniMQTTClient`, supporting outbound WSS (port 443) and raw TCP (port 1883).
- Connects outbound to `wss://public.cloud.shiftr.io:443/mqtt` with fallback to HiveMQ and EMQX.
- Subscribes to `pb/<room_id>/mac` and publishes responses to `pb/<room_id>/phone`.

### Client Implementation (`bridge/server.py`, `docs/index.html`)
- Uses browser native `WebSocket` over TLS (`wss://public.cloud.shiftr.io:443/mqtt`, fallback to HiveMQ/EMQX).
- Implements `NanoMQTTWS`, a lightweight binary MQTT client with credential support.
- Subscribes to `pb/<room_id>/phone` and publishes requests to `pb/<room_id>/mac`.

---

## Security Guarantees

| Property | Implementation Mechanism |
| :--- | :--- |
| **Zero Inbound Attack Surface** | Daemon binds exclusively to `127.0.0.1:8765`. Both host and mobile make outbound-only connections. |
| **Confidentiality** | CTR mode stream encryption with distinct per-message 128-bit nonces. |
| **Integrity & Authenticity** | HMAC-SHA256 Encrypt-then-MAC verification on every frame. |
| **Replay Protection** | Ephemeral room identifiers and keys regenerated on every host process launch. |
| **Zero Third-Party Trust** | Intermediate MQTT brokers route opaque ciphertext envelopes and possess no knowledge of plaintext or keys. |

