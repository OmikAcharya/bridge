#!/usr/bin/env python3
"""
Prompt Bridge: Voice dictation & text relay from mobile (Wispr Flow) to Mac.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import json
import socket
import time

PORT = 8765

def get_lan_ip():
    """Detects primary LAN IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="theme-color" content="#09090b">
    <title>Prompt Bridge</title>
    <style>
        :root {
            --bg: #09090b;
            --surface: #141417;
            --surface-border: #27272a;
            --surface-border-focus: #3f3f46;
            --text-main: #f4f4f5;
            --text-muted: #71717a;
            --text-dim: #52525b;
            --accent: #ffffff;
            --accent-text: #09090b;
            --green: #22c55e;
            --red: #ef4444;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            --font-mono: ui-monospace, "SF Mono", Menlo, monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            font-family: var(--font-sans);
            background-color: var(--bg);
            color: var(--text-main);
            height: 100dvh;
            display: flex;
            flex-direction: column;
            padding: calc(12px + env(safe-area-inset-top)) 16px calc(16px + env(safe-area-inset-bottom)) 16px;
            overflow: hidden;
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 4px 0 12px 0;
            flex-shrink: 0;
        }

        .title-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 6px var(--green);
            transition: background-color 0.2s, box-shadow 0.2s;
        }

        .status-dot.offline {
            background: var(--red);
            box-shadow: 0 0 6px var(--red);
        }

        .title {
            font-size: 14px;
            font-weight: 600;
            letter-spacing: -0.01em;
            color: var(--text-main);
        }

        .host-info {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-dim);
        }

        .editor-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 14px;
            overflow: hidden;
            transition: border-color 0.15s ease;
        }

        .editor-container:focus-within {
            border-color: var(--surface-border-focus);
        }

        textarea {
            flex: 1;
            width: 100%;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text-main);
            font-family: var(--font-sans);
            font-size: 19px;
            line-height: 1.5;
            padding: 16px;
            resize: none;
            -webkit-appearance: none;
        }

        textarea::placeholder {
            color: var(--text-dim);
            font-weight: 400;
        }

        .editor-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 14px 10px 14px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 12px;
            color: var(--text-muted);
            font-family: var(--font-mono);
            flex-shrink: 0;
        }

        .editor-actions {
            display: flex;
            align-items: center;
            gap: 12px;
            font-family: var(--font-sans);
        }

        .btn-text {
            background: none;
            border: none;
            color: var(--text-muted);
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            padding: 2px 4px;
        }

        .btn-text:active {
            color: var(--text-main);
        }

        .controls {
            margin-top: 12px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            flex-shrink: 0;
        }

        .options-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 4px;
        }

        .toggle-label {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: var(--text-muted);
            cursor: pointer;
            user-select: none;
        }

        .toggle-switch {
            position: relative;
            width: 36px;
            height: 20px;
            background: #27272a;
            border-radius: 10px;
            transition: background 0.2s;
            display: inline-block;
        }

        .toggle-switch::after {
            content: '';
            position: absolute;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: white;
            top: 2px;
            left: 2px;
            transition: transform 0.2s;
        }

        input[type="checkbox"] {
            display: none;
        }

        input[type="checkbox"]:checked + .toggle-switch {
            background: #3b82f6;
        }

        input[type="checkbox"]:checked + .toggle-switch::after {
            transform: translateX(16px);
        }

        .send-btn {
            width: 100%;
            height: 52px;
            border-radius: 12px;
            border: none;
            background: var(--accent);
            color: var(--accent-text);
            font-size: 16px;
            font-weight: 600;
            letter-spacing: -0.01em;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: background 0.15s, transform 0.1s;
        }

        .send-btn:active {
            transform: scale(0.98);
        }

        .send-btn.success {
            background: var(--green);
            color: white;
        }

        .send-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
    </style>
</head>
<body>

    <header>
        <div class="title-group">
            <div id="statusDot" class="status-dot"></div>
            <span class="title">Prompt Bridge</span>
        </div>
        <span id="hostInfo" class="host-info">Mac Connected</span>
    </header>

    <div class="editor-container">
        <textarea 
            id="prompt" 
            placeholder="Speak with Wispr Flow or type..." 
            autofocus 
            autocomplete="off" 
            autocorrect="on" 
            spellcheck="true"
        ></textarea>
        <div class="editor-footer">
            <span id="metrics">0 words · 0 chars</span>
            <div class="editor-actions">
                <button id="undoBtn" class="btn-text" style="display: none;">Undo</button>
                <button id="clearBtn" class="btn-text">Clear</button>
            </div>
        </div>
    </div>

    <div class="controls">
        <div class="options-row">
            <label class="toggle-label">
                <input type="checkbox" id="enterToggle">
                <span class="toggle-switch"></span>
                <span>Press Enter on Mac</span>
            </label>
        </div>

        <button id="sendBtn" class="send-btn">
            <span>Send to Mac</span>
        </button>
    </div>

    <script>
        const promptEl = document.getElementById('prompt');
        const sendBtn = document.getElementById('sendBtn');
        const metricsEl = document.getElementById('metrics');
        const clearBtn = document.getElementById('clearBtn');
        const undoBtn = document.getElementById('undoBtn');
        const enterToggle = document.getElementById('enterToggle');
        const statusDot = document.getElementById('statusDot');
        const hostInfo = document.getElementById('hostInfo');

        let lastCleared = '';

        if (localStorage.getItem('bridge_enter') === 'true') {
            enterToggle.checked = true;
        }

        enterToggle.addEventListener('change', () => {
            localStorage.setItem('bridge_enter', enterToggle.checked);
        });

        function updateMetrics() {
            const val = promptEl.value;
            const words = val.trim() ? val.trim().split(/\s+/).length : 0;
            const chars = val.length;
            metricsEl.textContent = `${words} ${words === 1 ? 'word' : 'words'} · ${chars} chars`;
        }

        promptEl.addEventListener('input', updateMetrics);

        clearBtn.addEventListener('click', () => {
            if (!promptEl.value) return;
            lastCleared = promptEl.value;
            promptEl.value = '';
            undoBtn.style.display = 'inline';
            updateMetrics();
            promptEl.focus();
        });

        undoBtn.addEventListener('click', () => {
            if (!lastCleared) return;
            promptEl.value = lastCleared;
            lastCleared = '';
            undoBtn.style.display = 'none';
            updateMetrics();
            promptEl.focus();
        });

        async function sendPrompt() {
            const text = promptEl.value.trim();
            if (!text) {
                promptEl.focus();
                return;
            }

            const sendEnter = enterToggle.checked;
            sendBtn.disabled = true;
            sendBtn.innerHTML = '<span>Sending...</span>';

            try {
                const res = await fetch('/prompt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        prompt: text,
                        action: sendEnter ? 'paste_and_enter' : 'paste'
                    })
                });

                if (!res.ok) throw new Error('Failed');

                sendBtn.classList.add('success');
                sendBtn.innerHTML = '<span>Sent ✓</span>';
                promptEl.value = '';
                undoBtn.style.display = 'none';
                updateMetrics();

                setTimeout(() => {
                    sendBtn.classList.remove('success');
                    sendBtn.innerHTML = '<span>Send to Mac</span>';
                    sendBtn.disabled = false;
                    promptEl.focus();
                }, 500);

            } catch (err) {
                sendBtn.innerHTML = '<span>Error</span>';
                setTimeout(() => {
                    sendBtn.innerHTML = '<span>Send to Mac</span>';
                    sendBtn.disabled = false;
                }, 1000);
            }
        }

        sendBtn.addEventListener('click', sendPrompt);

        window.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                sendPrompt();
            }
        });

        async function ping() {
            try {
                const res = await fetch('/ping', { cache: 'no-store' });
                if (res.ok) {
                    statusDot.classList.remove('offline');
                    hostInfo.textContent = 'Mac Connected';
                } else {
                    throw new Error();
                }
            } catch (e) {
                statusDot.classList.add('offline');
                hostInfo.textContent = 'Offline';
            }
        }

        ping();
        setInterval(ping, 5000);
        updateMetrics();
    </script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Suppress default noisy access logs
        return

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            data = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/ping":
            data = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/prompt":
            self.send_response(404)
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
            prompt = data.get("prompt", "")
            action = data.get("action", "paste")

            if not prompt:
                self.send_response(400)
                self.end_headers()
                return

            print(f"\n[Prompt Bridge] ({action}):\n{prompt}\n")

            # 1. Put prompt into macOS clipboard
            subprocess.run(
                ["pbcopy"],
                input=prompt.encode("utf-8"),
                check=True
            )

            # 2. Paste into active application
            if action == "paste_and_enter":
                applescript = (
                    'tell application "System Events"\n'
                    '    keystroke "v" using command down\n'
                    '    delay 0.05\n'
                    '    key code 36\n'
                    'end tell'
                )
                subprocess.run(["osascript", "-e", applescript], check=True)
            else:
                subprocess.run([
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "v" using command down'
                ], check=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        except Exception as e:
            print(f"Error handling prompt: {e}")
            self.send_response(500)
            self.end_headers()


def run():
    lan_ip = get_lan_ip()
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Prompt bridge running:")
    print(f"  • Local:   http://localhost:{PORT}")
    print(f"  • Phone:   http://{lan_ip}:{PORT}\n")
    server.serve_forever()


if __name__ == "__main__":
    run()
