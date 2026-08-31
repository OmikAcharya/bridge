# bridge

> Voice-dictate prompts on your phone with Wispr Flow. Route them directly into specific, already-running terminal agents on your Mac—without tmux, window switching, or losing GUI focus.

---

## Why this exists

Dictating prompts on your phone using voice tools like Wispr Flow is fast, but getting those prompts into your terminal workflow usually sucks:
- You have to switch windows on your Mac, click the right terminal tab, paste, and press Enter.
- If you're reading docs in Chrome or watching logs in another window, pasting steals focus.
- Most remote solutions force you to migrate everything into `tmux` or re-launch your agents in custom wrappers.

**`bridge` solves this.** It runs as a lightweight local server that turns your phone into a dedicated remote input device for your existing terminal sessions.

```text
📱 Android / iOS (Wispr Flow)
   │
   │  HTTP / Wi-Fi / Tailscale
   ▼
⚡ Prompt Bridge (Mac)
   ├── Session Discovery (PIDs, TTYs, CWDs, Active Agents)
   ├── Router & Bento Grid Target Manager
   └── Terminal Adapters (Terminal.app, iTerm2, PTY, Clipboard)
   │
   ▼ Direct background injection (No focus change, no tmux)
🖥️ Terminal Tab [Claude Code / Codex / OpenCode / Shell]
```

---

## What it does

- **Direct Terminal Injection**: Delivers prompts straight into the target terminal process's input buffer. Your Mac stays focused on whatever you're currently doing.
- **Auto-Discovery**: Automatically inspects macOS process trees and terminal tabs to identify running agents (**Claude Code**, **Codex**, **OpenCode**, **Aider**, **Antigravity**, **Python REPLs**, and **Shells**) along with their project directories (`cwd`).
- **Bento Grid Mobile UI**: Clean, dark-mode mobile interface with 2-column session tiles. Tap any tile to route your next prompt there, or leave it on **Auto** to target your most active agent.
- **Keyboard-Adaptive Viewport**: When your mobile keyboard / Wispr Flow button pops up, the session grid collapses so the **Send button, Enter toggle, and quick chips stay permanently visible above your keyboard**.
- **Quick Action Chips**: Instant, zero-latency touch buttons for terminal control:
  - `Return ↵` — Send an empty Return key
  - `Continue` — Send "continue" to coding agents
  - `Yes` / `No` — Quick `y` / `n` approvals
  - `Ctrl+C` — Hardware interrupt (`SIGINT`) sent directly to the process
  - `Clear` — Instantly wipe dictated text
- **Prompt History**: Tap **History** in the top bar to pull up recent prompts and re-send or edit them in one tap.

---

## Quick Start

### 1. Run the bridge on your Mac

```bash
python3 hi.py
```

Optional custom port:
```bash
python3 hi.py 8765
```

The server will print your local and LAN URLs:
```text
⚡ Prompt Bridge running with direct Terminal Agent routing:
  • Local:   http://localhost:8765
  • Phone:   http://192.168.1.50:8765
```

### 2. Open on your phone

1. Navigate to `http://<YOUR_MAC_IP>:8765` in your mobile browser (add to home screen as a PWA for quick access).
2. Dictate your prompt with Wispr Flow.
3. Tap **Send & Execute**. Your prompt appears and runs in that exact terminal session on your Mac.

---

## Configuration (Optional)

You can customize aliases and defaults by creating `~/.bridge_config.json`:

```json
{
  "port": 8765,
  "auth_token": "optional-secret-token",
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
- `BRIDGE_PORT` / `PORT`: Server port (default `8765`).
- `BRIDGE_AUTH_TOKEN`: Optional Bearer token for authentication.
- `BRIDGE_ENABLE_LEGACY`: Set to `false` to disable the focused-window clipboard fallback.

---

## Architecture

```text
bridge/
├── server.py        # HTTP server & responsive mobile UI
├── router.py        # Maps logical prompt requests to resolved live sessions
├── targets.py       # Target registry, alias matching & auto-resolution
├── discovery.py     # macOS session discovery (Terminal tabs, PIDs, cwds, agent classifier)
├── models.py        # Domain types (Target, SessionInfo, PromptRequest, DeliveryResult)
├── config.py        # Env & file config manager
└── adapters/
    ├── terminal.py  # Apple Terminal direct session injection (AppleScript background)
    ├── iterm.py     # iTerm2 direct session injection
    ├── pty.py       # Direct TTY character device adapter
    └── legacy.py    # Clipboard + System Events paste fallback
```

---

## Testing

Run the unit and integration test suite:

```bash
python3 -m unittest discover -s tests -v
```
