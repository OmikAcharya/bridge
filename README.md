# bridge

A lightweight input router that pipes mobile voice dictation directly into active terminal sessions on macOS.

---

## Overview

When dictating code or complex prompts from a mobile device (e.g., using Wispr Flow), getting text into a local development environment typically involves manual friction: switching windows on macOS, finding the right tab, pasting from a shared clipboard, and pressing Return. Alternatively, tools attempt to force workflows into terminal multiplexers like `tmux` or steal GUI window focus.

`bridge` eliminates this friction. It runs a local daemon on macOS and exposes a mobile web client over your local network or Tailscale. Prompts dictated on your phone are dispatched directly to the target terminal session in the background via IPC without altering window focus or clipboard state.

---

## How It Works

1. **Session Discovery**: The daemon inspects active macOS terminal sessions (`Terminal.app`, `iTerm2`) and process trees to identify running interactive agents (Claude Code, Codex, OpenCode, Aider, Python REPLs, active shells) alongside their working directories and PTY devices.
2. **Logical Routing**: The mobile interface presents discovered sessions in a compact layout. Prompts can be targeted to a specific session or routed automatically to the foreground agent.
3. **Background Delivery**: Requests are received via HTTP and injected directly into the target session's controlling pseudo-terminal. macOS focus remains undisturbed.

```text
[Mobile Client / Wispr Flow]
              |
         HTTP / JSON
              v
[Bridge Daemon (main.py)]
      ├── Discovery Engine (PIDs, TTYs, CWDs)
      ├── Target Router
      └── Terminal Adapters (Terminal.app, iTerm2, PTY, Legacy)
              |
              +---> Target Session 1 (Claude Code @ backend)
              +---> Target Session 2 (OpenCode @ frontend)
              +---> Target Session 3 (Zsh Shell @ scripts)
```

---

## Interface & Controls

- **Adaptive Viewport**: The interface automatically detects keyboard elevation and compresses non-essential elements, keeping the prompt input, action bar, and Send trigger docked above the software keyboard.
- **Terminal Control Chips**:
  - `Return` : Dispatches a raw newline to the session.
  - `Continue` : Sends a standard continuation command.
  - `Yes` / `No` : Dispatches quick `y` / `n` confirmations for interactive CLI prompts.
  - `Ctrl+C` : Sends a `SIGINT` interrupt to the target process.
  - `Clear` : Clears the prompt input.
- **Enter Toggle**: Toggle execution behavior between direct command execution and non-executing text insertion.
- **Prompt History**: Access and re-dispatch recent voice inputs from a local cache.

---

## Getting Started

### 1. Start the Daemon

```bash
python3 main.py
```

To bind to a custom port:

```bash
python3 main.py 8765
```

The console will output your local and LAN URLs:

```text
Prompt Bridge running:
  • Local:   http://localhost:8765
  • LAN:     http://192.168.1.50:8765
```

### 2. Connect from Mobile

Open the LAN URL in your mobile browser. Select your target session, dictate your prompt, and tap Send.

---

## Configuration

Optional configuration can be placed in `~/.bridge_config.json`:

```json
{
  "port": 8765,
  "auth_token": "optional-shared-token",
  "enable_legacy_paste": true,
  "targets": {
    "backend": {
      "name": "Claude — Backend",
      "folder": "backend",
      "agent": "claude"
    }
  }
}
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `BRIDGE_PORT` / `PORT` | Listening HTTP port | `8765` |
| `BRIDGE_AUTH_TOKEN` | Optional Bearer token for access control | `None` |
| `BRIDGE_ENABLE_LEGACY` | Enable/disable focused-window clipboard fallback | `true` |

---

## Repository Structure

```text
bridge/
├── server.py        # HTTP interface, static asset delivery, and routing endpoints
├── router.py        # Maps logical targets to adapters and executes delivery
├── targets.py       # Target registry, alias resolution, and priority selection
├── discovery.py     # Process tree inspection, CWD resolution, and agent classifier
├── models.py        # Shared data structures (Target, SessionInfo, PromptRequest)
├── config.py        # File and environment variable configuration loader
└── adapters/
    ├── terminal.py  # macOS Terminal.app background AppleScript adapter
    ├── iterm.py     # iTerm2 background IPC adapter
    ├── pty.py       # Direct character device injection adapter
    └── legacy.py    # System Events clipboard paste fallback
```

---

## Testing

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```
