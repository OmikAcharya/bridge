# bridge

> **Zero-friction mobile prompt router & terminal monitor for macOS.**  
> Speak into your phone. Prompts inject directly into your active terminal sessions with **zero window switches**, **zero clipboard alteration**, **zero open network ports**, and **zero external dependencies**.

---

## Architecture

```text
┌───────────────────────────────────────────────────────────┐
│                    Mobile Device / Client                 │
│      Voice Dictation · Dynamic Island · Bento Controller  │
│      WebCrypto: CTR-HMAC-SHA256 (Key in URL hash #)       │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              │ Outbound WSS (TLS)
                              │ Encrypted Envelope {nonce, ct, mac}
                              ▼
┌───────────────────────────────────────────────────────────┐
│              Public Ephemeral Relay (WSS)                 │
│         broker.emqx.io / broker.hivemq.com                │
│         (Blind packet forwarder · Zero plaintext)         │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              │ Outbound TCP (TLS)
                              ▼
┌───────────────────────────────────────────────────────────┐
│                 macOS Host Daemon (Python stdlib)         │
│  ├── P2P Relay: Authenticated envelope decrypt & verify   │
│  ├── Process Engine: Discovers interactive CLI agents     │
│  │   (Antigravity, Claude Code, OpenCode, Codex, Shells)  │
│  ├── Disambiguator: Resolves CWD, instance & TTY targets  │
│  └── Driver: Background AppleScript / OSA PTY injection   │
└──────────────┬───────────────────────────────┬────────────┘
               │                               │
    do script  │ (no window focus)  do script  │ (no clipboard touch)
               ▼                               ▼
     ┌───────────────────┐           ┌───────────────────┐
     │   Antigravity     │           │    Claude Code    │
     │ /dev/ttys006 · AGY│           │ /dev/ttys004 · CLI│
     └───────────────────┘           └───────────────────┘
```

---

## Why `bridge`

Modern developers use world-class voice dictation on their phones, but their terminal agents (Claude Code, Antigravity, Aider, Codex) live inside desktop terminal sessions. Moving text between them via screen sharing (VNC), SSH, or `tmux` introduces latency, non-native keybindings, or security exposure.

`bridge` replaces those workarounds with surgical PTY injection:

| Capability | Engineering Reality |
| :--- | :--- |
| **Zero Focus Stealing** | Injects keystrokes directly into target `/dev/ttys00X` buffers via background AppleScript/OSA. Window focus and clipboard contents remain completely undisturbed while you code. |
| **Zero Open Ports (E2EE)** | Daemon binds strictly to `127.0.0.1`. Remote mobile connections route through an outbound end-to-end encrypted relay. 256-bit symmetric keys live exclusively in the client-side URL fragment (`#`), invisible to network hops. |
| **Zero Dependencies** | Host runs on 100% Python standard library (`socket`, `struct`, `hmac`, `hashlib`, `secrets`, `threading`). Client runs on vanilla WebCrypto and WebSockets. |
| **Multi-Session Disambiguation** | Discovers active agents and workspace paths. Sibling sessions in the same directory are automatically tagged and indexed (`bridge · #1`, `bridge · #2`) with idle agents prioritized over running tasks. |
| **Sub-50ms Terminal Telemetry** | Streamlined ANSI tailing engine provides near-instant verification logs on mobile without polling lag. |

---

## Quickstart

### 1. Launch the Daemon
```bash
git clone https://github.com/OmikAcharya/bridge.git
cd bridge
python3 main.py
```

### 2. Pair Mobile Client
Scan the ANSI QR code rendered in your terminal with your phone camera. The pairing URL contains the ephemeral E2EE symmetric key in the hash fragment:
```text
https://omikacharya.github.io/bridge/#p2p=1&room=...&key=...
```

### 3. Dictate & Route
Tap an agent tile or leave selection on **Auto-detect**. Speak your prompt, tap **Send**, and watch commands execute in your target terminal tab instantaneously.

---

## CLI & Runtime Options

```bash
# Default: Zero-exposure P2P relay (no inbound open ports)
python3 main.py

# Direct LAN mode (binds to Wi-Fi interface for trusted local networks)
python3 main.py --expose-lan

# Custom local listening port
python3 main.py 8765
```

### Configuration (`~/.bridge_config.json`)
Optional persistent target aliases and server defaults:
```json
{
  "port": 8765,
  "auth_token": "optional-bearer-token",
  "enable_legacy_paste": true,
  "targets": {
    "backend": {
      "name": "Claude — Backend API",
      "folder": "backend",
      "agent": "claude"
    }
  }
}
```

---

## Security Model

- **End-to-End Authenticated Encryption**: Payloads use an authenticated CTR stream cipher with Encrypt-then-MAC (HMAC-SHA256). Intermediate MQTT relay brokers act as blind pipes and cannot decrypt or tamper with payloads.
- **Zero Key Leakage**: Ephemeral symmetric keys are encoded in the URL hash (`#key=...`), which browsers never transmit over HTTP requests.
- **Strict IPC Sanitization**: Input strings undergo escaping to prevent AppleScript injection prior to dispatch.
- **Zero Daemon Attack Surface**: In default P2P mode, no listening sockets are opened to the outside network.

---

## Test Suite

Run unit and cryptographic interop tests:
```bash
python3 -m unittest discover tests -v
```
```text
Ran 48 tests in 7.3s
OK (skipped=1)
```
100% standard library tests covering E2EE roundtrip, process hierarchy inspection, tamper rejection, and target resolution.

---

## License

[MIT](LICENSE)
