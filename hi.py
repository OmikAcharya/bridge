#!/usr/bin/env python3

from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import json

PORT = 8765

HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Prompt Bridge</title>

    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            margin: 0;
            padding: 20px;
            background: #111;
            color: white;
        }

        textarea {
            width: 100%;
            height: 60vh;
            box-sizing: border-box;
            font-size: 20px;
            padding: 16px;
            border-radius: 12px;
            border: none;
            outline: none;
            resize: vertical;
        }

        button {
            width: 100%;
            margin-top: 15px;
            padding: 18px;
            font-size: 20px;
            border: none;
            border-radius: 12px;
        }
    </style>
</head>

<body>

<textarea id="prompt"
    placeholder="Speak with Wispr Flow..."></textarea>

<button onclick="sendPrompt()">Send to Mac</button>

<script>
async function sendPrompt() {
    const textarea = document.getElementById("prompt");
    const prompt = textarea.value.trim();

    if (!prompt) return;

    await fetch("/prompt", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({prompt})
    });

    textarea.value = "";
    textarea.focus();
}
</script>

</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/":
            data = HTML.encode()

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()

            self.wfile.write(data)

    def do_POST(self):
        if self.path != "/prompt":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        data = json.loads(body)
        prompt = data["prompt"]

        print("\nPROMPT:")
        print(prompt)

        # Put prompt into macOS clipboard
        subprocess.run(
            ["pbcopy"],
            input=prompt.encode(),
            check=True
        )

        # Automatically paste into the currently focused application
        subprocess.run([
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "v" using command down'
        ])

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")


server = HTTPServer(("0.0.0.0", PORT), Handler)

print(f"Prompt bridge running on port {PORT}")
print(f"Open http://<MAC-IP>:{PORT} on your Android")

server.serve_forever()