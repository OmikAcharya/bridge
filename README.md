# Prompt Bridge: Direct Mobile → Terminal Agent Bridge

Prompt Bridge enables dictating prompts on Android (via Wispr Flow or any browser) and routing them directly into specific, already-running interactive terminal agent instances (e.g. **Claude Code**, **Codex**, **OpenCode**, **Aider**, **Antigravity**, or shells) on macOS.

---

## Key Features

- **Direct Session Injection**: Prompts are injected directly into the selected terminal session without requiring GUI focus, window switching, tab activation, clipboard manipulation, or manual keystrokes.
- **No tmux Required**: Works with your existing terminal windows, tabs, and processes.
- **Dynamic Session Discovery**: Automatically discovers active terminal tabs, running agents (Claude Code, Codex, OpenCode, Aider, Python REPL, Shells), working directories, and process states on macOS.
- **Preserved Mobile UX**: Dark-mode mobile web UI with target selector, status badges, word/character metrics, undo/clear, and auto-restored preferences.
- **Multi-Terminal Support**: Native support for macOS `Terminal.app` and `iTerm2`, with fallback to focused application pasting.
- **Backward Compatible**: Existing endpoints (`/ping`, `/prompt`, legacy paste) continue to work seamlessly.

---

## Quick Start

### 1. Launch the Bridge

```bash
python3 hi.py
```

Or specify a custom port:

```bash
python3 hi.py 8765
```

The terminal will display your local and LAN URLs:
```text
⚡ Prompt Bridge running with direct Terminal Agent routing:
  • Local:   http://localhost:8765
  • Phone:   http://192.168.1.50:8765
```

### 2. Open on Android / Mobile

Open `http://<YOUR_MAC_IP>:8765` in Chrome on your Android device (or add it as a PWA / home screen shortcut).

1. Select your target agent from the dropdown (e.g., `● Claude Code — backend`).
2. Dictate your prompt using Wispr Flow or voice typing.
3. Tap **Send**.
4. The prompt will immediately appear and execute in that specific terminal session on your Mac.

---

## Architecture

```text
Android (Wispr Flow)
       │
       ▼ (HTTP/JSON)
┌────────────────────────────────────────┐
│  Prompt Bridge Server (hi.py)          │
│                                        │
│  • Session Discovery (macOS / TTY)     │
│  • Target Manager (Dynamic & Aliases)  │
│  • Prompt Router                       │
└──────────────────┬─────────────────────┘
                   │
                   ▼
┌────────────────────────────────────────┐
│  Terminal Adapters                     │
│  • AppleTerminalAdapter (Direct tab)   │
│  • ITermAdapter (Direct session)       │
│  • PTYAdapter (Direct TTY)             │
│  • LegacyPasteAdapter (Fallback)       │
└──────────────────┬─────────────────────┘
                   │ (No GUI focus change)
                   ▼
  Existing Terminal Agent Instance
  (Claude Code / Codex / OpenCode / Shell)
```

---

## Configuration (Optional)

You can customize the bridge by creating a `~/.bridge_config.json` file or setting environment variables:

### Configuration File (`~/.bridge_config.json`):

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
    },
    "frontend": {
      "name": "Claude — Frontend",
      "folder": "frontend",
      "agent": "claude"
    }
  }
}
```

### Environment Variables:

- `BRIDGE_PORT` or `PORT`: HTTP server port (default: `8765`).
- `BRIDGE_AUTH_TOKEN`: Optional bearer authentication token.
- `BRIDGE_ENABLE_LEGACY`: Enable/disable fallback "Focused Mac Application" target (`true`/`false`).

---

## API Endpoints

### `GET /targets`
Returns active discovered targets and configured aliases.

```json
{
  "targets": [
    {
      "id": "claude-backend",
      "name": "Claude Code — backend",
      "display_name": "Claude Code — backend [ttys001]",
      "agent": "claude",
      "agent_name": "Claude Code",
      "cwd": "/Users/mac/Projects/backend",
      "folder": "backend",
      "tty": "/dev/ttys001",
      "application": "Terminal",
      "status": "ready",
      "is_busy": false
    },
    {
      "id": "focused",
      "name": "Focused Mac Application",
      "display_name": "Focused Application (Active Window)",
      "agent": "legacy",
      "status": "available"
    }
  ],
  "default_target": "claude-backend"
}
```

### `POST /prompt`
Sends a prompt to the specified target.

**Request:**
```json
{
  "target": "claude-backend",
  "prompt": "Inspect the authentication middleware and refactor token refresh.",
  "action": "execute"
}
```

**Response:**
```json
{
  "success": true,
  "target_id": "claude-backend",
  "target_name": "Claude Code — backend",
  "adapter_used": "AppleTerminalAdapter",
  "message": "Delivered directly to Claude Code — backend (/dev/ttys001)"
}
```

### `GET /ping`
Health check endpoint returning `{"status": "ok"}`.

---

## Running Tests

```bash
python3 -m unittest discover -s tests -v
```
