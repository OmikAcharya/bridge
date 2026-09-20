# bridge

A lightweight, non-intrusive input router and terminal monitor for macOS. Dispatches mobile voice dictation and prompt text directly into active terminal sessions without switching window focus or altering clipboard state.

---

## Overview

Software development with interactive CLI agents (such as Claude Code, Antigravity, Aider, Codex, or standard shells) often involves long, structured prompts. While mobile speech-to-text engines (e.g., mobile dictation) enable rapid thought-to-text capture, transferring text from a phone to a specific terminal tab on a Mac typically introduces workflow friction:

- **Window Management**: Shifting GUI focus to the terminal window, finding the right tab, pasting, and pressing Return.
- **Screen Sharing / VNC**: Heavy on bandwidth and power, with desktop UI scaled down to unreadable mobile viewports.
- **Terminal Multiplexers (`tmux`)**: Imposes non-native keybindings and disrupts native GUI terminal integrations.
- **Network Exposure**: Binding an unauthenticated HTTP or SSH server to local interfaces exposes machines to untrusted LAN or public Wi-Fi traffic.

`bridge` addresses these issues with a focused daemon and web client:

- **Direct PTY Injection**: Sends keystrokes and commands directly to the controlling pseudo-terminal (`/dev/ttys00X`) via background AppleScript/IPC. macOS window focus and clipboard state remain untouched.
- **Process & Agent Discovery**: Continuously inspects macOS process trees to identify active interactive sessions (Claude Code, Antigravity, Aider, Codex, OpenCode, Python REPLs, active shells) alongside their working directories.
- **Dual Connection Modes**:
  - **Zero-Exposure E2EE (Default)**: Daemon binds strictly to `127.0.0.1`. Remote mobile connections route through an end-to-end encrypted relay over WebSockets using CTR-HMAC-SHA256 authenticated envelopes. Zero open listening ports on the local network.
  - **Direct LAN (`--expose-lan`)**: Binds to the local Wi-Fi interface for direct HTTP access within trusted networks.
- **Zero Runtime Dependencies**: The host daemon uses only the Python standard library (`socket`, `struct`, `hmac`, `hashlib`, `secrets`, `threading`). The web frontend uses vanilla JavaScript with native WebCrypto (`crypto.subtle`) and standard WebSockets.

---

## System Architecture

```text
┌────────────────────────────────────────────────────────────────────────┐
│                              Mobile Client                             │
│       (WebCrypto CTR-HMAC-SHA256 + Native WebSocket NanoMQTTWS)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Encrypted Payload {nonce, ct, tag}
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        Public Relay Broker (WSS)                       │
│                  (broker.emqx.io / broker.hivemq.com)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Outbound Socket Connection
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       macOS Host Daemon (main.py)                      │
│                                                                        │
│   ├── Discovery Engine: Parses process trees, CWDs, and TTY devices    │
│   ├── Target Manager: Tracks active agents and alias routes            │
│   ├── Crypto Engine: CTR stream cipher + HMAC-SHA256 verification      │
│   ├── Formatter: Terminal output ANSI stripping and tail formatting    │
│   └── Terminal Adapters:                                               │
│       ├── Terminal.app Adapter (Background AppleScript)                │
│       ├── iTerm2 Adapter (Background OSA IPC)                          │
│       └── Legacy Paste Adapter (Focused window fallback)               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    │ Target PTY Injection
                                    ▼
               ┌────────────────────┴────────────────────┐
               │                                         │
               ▼                                         ▼
    ┌──────────────────────┐                  ┌──────────────────────┐
    │  Claude Code Session │                  │  Antigravity Session │
    │   (ttys001 @ backend)│                  │   (ttys002 @ bridge) │
    └──────────────────────┘                  └──────────────────────┘
```

---

## Core Mechanics

### 1. Process Discovery & Target Resolution
The daemon crawls the process hierarchy using `ps -eo pid,ppid,tty,args` and `/proc` inspection:
- Resolves process trees rooted at `Terminal.app` and `iTerm2` instances.
- Detects foreground foreground processes and matches them against known interactive agent signatures (`claude`, `agy`, `aider`, `codex`, `opencode`, `python`, `node`, `zsh`, `bash`, `fish`).
- Identifies active working directories via `lsof` and `proc_pidinfo`.
- Assigns persistent logical IDs and human-readable labels (`Claude — backend`, `Antigravity — bridge`).

### 2. Background Terminal IPC
Prompt delivery operates via background application scripting:
- **Terminal.app**: Uses AppleScript commands directed at specific window and tab indices corresponding to the target TTY, executing `do script text in tab X of window Y` without calling `activate`.
- **iTerm2**: Dispatches text via iTerm2's OSA object model to target sessions matching the discovered TTY identifier.
- **Sanitization**: All input strings pass through an escaping pipeline that strips control characters, null bytes, and escapes quote sequences prior to AppleScript execution.

### 3. End-to-End Encrypted P2P Relay
When operating in default zero-exposure mode:
- **Key Generation**: Generates an ephemeral 256-bit symmetric key (`auth_key`) and random 12-character room ID (`room_id`) on daemon startup.
- **Key Distribution**: The key is encoded strictly into the URL hash fragment (`#p2p=1&room=<room>&key=<key>`). The fragment is processed client-side and is never transmitted in HTTP request paths or headers.
- **Authenticated Encryption**:
  - Key derivation: $K_{\text{enc}} = \text{HMAC-SHA256}(K_{\text{master}}, \text{"enc"})$, $K_{\text{mac}} = \text{HMAC-SHA256}(K_{\text{master}}, \text{"mac"})$.
  - Encryption: CTR mode keystream generation using counter blocks $\text{HMAC-SHA256}(K_{\text{enc}}, \text{nonce} \mathbin{\Vert} \text{counter}_{32})$.
  - Authentication: Encrypt-then-MAC via $\text{HMAC-SHA256}(K_{\text{mac}}, \text{nonce} \mathbin{\Vert} \text{ciphertext})$.
  - Verification: Constant-time comparison rejects tampered or mismatched payloads prior to deserialization.
- **Relay Transport**: Both host and client connect outbound to public MQTT WebSocket endpoints (`broker.emqx.io:8084`, `broker.hivemq.com:8084`). Host listens on TCP 1883 with automatic failover.

### 4. Live Output Monitoring
The web client includes an activity log drawer for tracking terminal output history and verification directly from mobile.

---

## Installation & Usage

### Prerequisites
- macOS 12+ (Monterey, Ventura, Sonoma, Sequoia)
- Python 3.9+ (System Python or Homebrew)
- Terminal access permissions for AppleScript / System Events (prompted on first run)

### Running the Daemon

Start the daemon in zero-exposure P2P mode (default):

```bash
python3 main.py
```

Expose directly on local network (trusted Wi-Fi only):

```bash
python3 main.py --expose-lan
```

Bind to a custom port:

```bash
python3 main.py 8765
```

### Pairing with Mobile Device

1. The terminal displays a startup banner with an ANSI QR code and pairing URL.
2. Scan the QR code with your phone camera to open the web client (`https://omikacharya.github.io/bridge/#...`).
3. Select an active session from the Bento grid or leave selection on **Auto-detect**.
4. Dictate or type your prompt, then tap **Send & Execute** (or use action chips: `Return ↵`, `Ctrl+C`, `Yes`, `No`, `Continue`).

---

## Configuration

Custom target aliases and server defaults can be configured via `~/.bridge_config.json`:

```json
{
  "port": 8765,
  "auth_token": "optional-shared-bearer-token",
  "enable_legacy_paste": true,
  "targets": {
    "backend": {
      "name": "Claude — Backend API",
      "folder": "backend",
      "agent": "claude"
    },
    "frontend": {
      "name": "Antigravity — Web UI",
      "folder": "frontend",
      "agent": "agy"
    }
  }
}
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `BRIDGE_PORT` / `PORT` | Local HTTP listening port | `8765` |
| `BRIDGE_AUTH_TOKEN` | Optional Bearer token for HTTP API endpoints | `None` |
| `BRIDGE_ENABLE_LEGACY` | Enable/disable focused-window clipboard paste fallback | `true` |

---

## Security Model

| Threat | Safeguard |
| :--- | :--- |
| **Local Port Scanning / LAN Interception** | Default daemon configuration binds exclusively to `127.0.0.1`. No open listening ports on LAN. |
| **Relay Interception / MITM** | All P2P messages use authenticated CTR-HMAC-SHA256 envelopes. Intermediate brokers cannot read or modify payloads. |
| **AppleScript / Command Injection** | Input sanitization escapes quotes, slashes, null bytes, and non-printable control characters before OSA execution. |
| **CSRF / Origin Spoofing** | HTTP request handler validates `Origin` headers and drops cross-site `Sec-Fetch-Site` requests. |
| **Replay & Key Longevity** | Ephemeral keys and room identifiers are generated in memory on each launch and discarded upon process termination. |

---

## Repository Structure

```text
.
├── main.py                  # Entrypoint, CLI parsing, terminal QR banner
├── bridge/
│   ├── discovery.py         # Process hierarchy inspection, TTY and CWD resolution
│   ├── targets.py           # Target registration, alias mapping, priority sorting
│   ├── router.py            # Prompt routing and adapter execution
│   ├── server.py            # HTTP server, API endpoints, embedded web client
│   ├── p2p.py               # E2EE crypto (CTR-HMAC-SHA256) & stdlib MQTT TCP client
│   ├── qrcode.py            # ANSI Unicode QR generator
│   ├── compressor.py        # Terminal output ANSI stripping and tail formatter
│   ├── models.py            # Target, PromptRequest, DeliveryResult dataclasses
│   ├── config.py            # File and environment configuration loader
│   └── adapters/
│       ├── factory.py       # Adapter resolver
│       ├── terminal.py      # Terminal.app background AppleScript adapter
│       ├── iterm.py         # iTerm2 background IPC adapter
│       └── legacy.py        # Focused-window clipboard fallback
├── docs/
│   ├── index.html           # Hosted static web client (GitHub Pages)
│   └── P2P_ARCHITECTURE.md  # Detailed P2P protocol and crypto specification
└── tests/
    ├── test_p2p.py          # Unit tests for P2P manager, QR, and crypto
    ├── test_p2p_e2ee.py     # E2EE roundtrip, tamper rejection, WebCrypto interop
    ├── test_server.py       # HTTP endpoints and routing tests
    ├── test_security.py     # CSRF, auth timing, escaping, sanitization
    └── test_bridge.py       # Core router, target discovery, compressor tests
```

---

## Testing

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

All tests execute against standard library components with zero external test runners:

```text
Ran 39 tests in 4.78s

OK
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.

