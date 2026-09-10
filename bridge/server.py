"""
HTTP Server and Web Interface for Prompt Bridge.
"""

import sys
import os
import json
import socket
import secrets
import logging
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Optional

from bridge.models import PromptRequest, DeliveryResult
from bridge.config import Config
from bridge.discovery import SessionDiscovery
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory, get_adapter
from bridge.router import PromptRouter
from bridge.compressor import format_raw_tail
from bridge.p2p import P2PManager

logger = logging.getLogger("PromptBridge.Server")


def get_lan_ip() -> str:
    """Detects primary LAN IPv4 address with fallback to local interface inspection."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def get_mdns_hostname() -> str:
    """Returns local mDNS hostname (e.g. my-mac.local) for reliable LAN addressing."""
    try:
        h = socket.gethostname()
        if not h.endswith(".local"):
            return f"{h}.local"
        return h
    except Exception:
        return ""



HTML_PATH = Path(__file__).resolve().parent.parent / "docs" / "index.html"


def get_html_bytes() -> bytes:
    """Loads frontend HTML content from docs/index.html with fallback."""
    if HTML_PATH.is_file():
        return HTML_PATH.read_bytes()
    return b"<!DOCTYPE html><html><body><h1>Prompt Bridge</h1><p>docs/index.html not found.</p></body></html>"


# Module-level alias for backward compatibility
HTML_TEMPLATE = get_html_bytes().decode("utf-8")


class BridgeServer(ThreadingHTTPServer):
    """Threading HTTP server with graceful client disconnect handling and TCP_NODELAY."""
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        sock, addr = super().get_request()
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        return sock, addr

    def handle_error(self, request, client_address):
        """Suppress noisy tracebacks for normal socket disconnects/resets."""
        exc_type, exc_val, _ = sys.exc_info()
        if exc_type and (
            issubclass(exc_type, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError, socket.error))
            or isinstance(exc_val, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError, socket.error))
        ):
            logger.debug("Client connection reset/aborted (%s): %s", client_address, exc_val)
            return
        super().handle_error(request, client_address)


MAX_BODY_SIZE = 64 * 1024  # 64 KB limit to prevent memory exhaustion DoS


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for the bridge with HTTP/1.1 keep-alive."""
    protocol_version = "HTTP/1.1"
    timeout = 60

    router: PromptRouter = None
    target_manager: TargetManager = None
    config: Config = None
    p2p_manager: P2PManager = None

    def log_message(self, format, *args):
        return

    def handle(self):
        """Handle incoming connection, suppressing abrupt client resets."""
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError, socket.error) as e:
            logger.debug("Client connection closed abruptly (%s): %s", self.client_address, e)

    def handle_one_request(self):
        """Handle a single HTTP request, catching disconnects during header read."""
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, TimeoutError, socket.error) as e:
            self.close_connection = True
            logger.debug("Client reset connection during request parse (%s): %s", self.client_address, e)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth-Token")

    def _is_authenticated(self) -> bool:
        if not self.config or not self.config.auth_token:
            return True
        auth_hdr = self.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
            if secrets.compare_digest(token, self.config.auth_token):
                return True
        x_token = self.headers.get("X-Auth-Token", "")
        if x_token and secrets.compare_digest(x_token, self.config.auth_token):
            return True
        return False

    def _is_csrf_safe(self) -> bool:
        """Protects local HTTP daemon against browser Cross-Site Request Forgery (CSRF)."""
        sec_site = self.headers.get("Sec-Fetch-Site", "").lower()
        if sec_site == "cross-site":
            return False

        origin = self.headers.get("Origin", "")
        if origin:
            parsed = urllib.parse.urlparse(origin)
            host = parsed.hostname or ""
            # Allowed origins: loopback, local LAN, mDNS, or hosted client on github.io
            if (
                host not in ("localhost", "127.0.0.1", get_lan_ip(), get_mdns_hostname())
                and not host.endswith("github.io")
                and not host.endswith(".local")
            ):
                return False
        return True

    def do_OPTIONS(self):
        try:
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
            self.close_connection = True

    def do_HEAD(self):
        clean_path = self.path.split("?")[0]
        try:
            if clean_path in ("/", "/index.html"):
                data = get_html_bytes()
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
            elif clean_path == "/ping":
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "15")
                self.end_headers()
            elif clean_path in ("/favicon.ico", "/favicon.svg", "/favicon.png", "/apple-touch-icon.png"):
                static_file = HTML_PATH.parent / clean_path.lstrip("/")
                if static_file.is_file():
                    content_type = "image/svg+xml" if clean_path.endswith(".svg") else ("image/png" if clean_path.endswith(".png") else "image/x-icon")
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(static_file.stat().st_size))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    return
            else:
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
            self.close_connection = True

    def do_GET(self):
        clean_path = self.path.split("?")[0]

        try:
            if clean_path in ("/", "/index.html"):
                data = get_html_bytes()
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            elif clean_path == "/ping":
                data = b'{"status":"ok"}'
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            elif clean_path in ("/favicon.ico", "/favicon.svg", "/favicon.png", "/apple-touch-icon.png"):
                static_file = HTML_PATH.parent / clean_path.lstrip("/")
                if static_file.is_file():
                    content_type = "image/svg+xml" if clean_path.endswith(".svg") else ("image/png" if clean_path.endswith(".png") else "image/x-icon")
                    data = static_file.read_bytes()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return

            elif clean_path == "/targets":
                if not self._is_authenticated():
                    self.send_response(401)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "23")
                    self.end_headers()
                    self.wfile.write(b'{"error":"Unauthorized"}')
                    return

                targets = self.target_manager.get_targets() if self.target_manager else []
                targets_dict = [t.to_dict() for t in targets]

                default_t = "auto"
                for t in targets:
                    if t.agent in ("claude", "codex", "opencode", "aider", "agy") and t.id != "focused":
                        default_t = t.id
                        break

                payload = json.dumps({
                    "targets": targets_dict,
                    "default_target": default_t
                }).encode("utf-8")

                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            elif clean_path == "/terminal/tail":
                if not self._is_authenticated():
                    self.send_response(401)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":"Unauthorized"}')
                    return

                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                target_id = params.get("target", ["auto"])[0]
                try:
                    raw_lines = int(params.get("lines", ["40"])[0])
                    lines_count = min(max(1, raw_lines), 200)
                except ValueError:
                    lines_count = 40

                target = self.target_manager.resolve(target_id) if self.target_manager else None
                if not target:
                    err_payload = json.dumps({"success": False, "error": f"Target '{target_id}' not found."}).encode("utf-8")
                    self.send_response(404)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err_payload)))
                    self.end_headers()
                    self.wfile.write(err_payload)
                    return

                adapter = get_adapter(target)
                raw_history = adapter.get_history(target, lines=max(lines_count, 50))
                content = format_raw_tail(raw_history, lines=lines_count)

                payload = json.dumps({
                    "success": True,
                    "target_id": target.id,
                    "target_name": target.name,
                    "mode": "raw",
                    "content": content,
                    "is_busy": target.is_busy
                }).encode("utf-8")

                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            elif clean_path == "/p2p/info":
                payload = json.dumps({
                    "success": True,
                    "room": self.p2p_manager.room_id if self.p2p_manager else "",
                    "stun": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]
                }).encode("utf-8")
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            elif clean_path == "/p2p/poll":
                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                target = params.get("target", ["phone"])[0]
                key = params.get("key", [""])[0]
                if self.p2p_manager and key and not self.p2p_manager.verify_auth_token(key):
                    err = b'{"success":false,"error":"Unauthorized"}'
                    self.send_response(401)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return

                messages = self.p2p_manager.get_signals(target) if self.p2p_manager else []
                payload = json.dumps({"success": True, "messages": messages}).encode("utf-8")
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            else:
                self.send_response(404)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
            self.close_connection = True

    def do_POST(self):
        clean_path = self.path.split("?")[0]

        if clean_path == "/p2p/signal":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body.decode("utf-8")) if body else {}

                parsed_url = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed_url.query)
                sender = params.get("sender", ["phone"])[0]
                key = params.get("key", [""])[0]

                if self.p2p_manager and key and not self.p2p_manager.verify_auth_token(key):
                    err = b'{"success":false,"error":"Unauthorized"}'
                    self.send_response(401)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return

                if self.p2p_manager:
                    self.p2p_manager.post_signal(sender, data)

                resp = b'{"success":true}'
                self.send_response(200)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
            except Exception:
                self.close_connection = True
            return

        if clean_path != "/prompt":
            try:
                self.send_response(404)
                self._send_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
                self.close_connection = True
            return

        if not self._is_csrf_safe():
            try:
                err_b = b'{"success":false,"error":"Cross-site requests prohibited"}'
                self.send_response(403)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_b)))
                self.end_headers()
                self.wfile.write(err_b)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
                self.close_connection = True
            return

        if not self._is_authenticated():
            try:
                err_b = b'{"success":false,"error":"Unauthorized"}'
                self.send_response(401)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_b)))
                self.end_headers()
                self.wfile.write(err_b)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
                self.close_connection = True
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY_SIZE:
                err_b = b'{"success":false,"error":"Payload exceeds maximum allowed size (64KB)"}'
                self.send_response(413)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_b)))
                self.end_headers()
                self.wfile.write(err_b)
                return

            body = self.rfile.read(max(0, length))
            data = json.loads(body.decode("utf-8"))

            prompt = data.get("prompt", "")
            target_id = data.get("target", "auto")
            action = data.get("action", "execute")

            if not prompt and action not in ("interrupt", "raw_enter"):
                err_b = b'{"success":false,"error":"Prompt cannot be empty"}'
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_b)))
                self.end_headers()
                self.wfile.write(err_b)
                return

            req = PromptRequest(prompt=prompt, target=target_id, action=action)
            result: DeliveryResult = self.router.route(req)

            resp_bytes = json.dumps(result.to_dict()).encode("utf-8")
            status_code = 200 if result.success else 400

            self.send_response(status_code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, socket.error):
            self.close_connection = True
        except json.JSONDecodeError as e:
            try:
                err_payload = json.dumps({"success": False, "error": f"Invalid JSON body: {str(e)}"}).encode("utf-8")
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_payload)))
                self.end_headers()
                self.wfile.write(err_payload)
            except Exception:
                self.close_connection = True
        except Exception as e:
            logger.exception("Error handling /prompt POST")
            try:
                err_payload = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
                self.send_response(500)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_payload)))
                self.end_headers()
                self.wfile.write(err_payload)
            except Exception:
                self.close_connection = True


def create_server(config: Optional[Config] = None, p2p_manager: Optional[P2PManager] = None, expose_lan: bool = False) -> BridgeServer:
    """Creates and configures the Prompt Bridge server instance."""
    if config is None:
        config = Config()

    discovery = SessionDiscovery()
    target_manager = TargetManager(discovery=discovery, config=config)
    adapter_factory = AdapterFactory()
    router = PromptRouter(target_manager=target_manager, adapter_factory=adapter_factory)

    BridgeRequestHandler.router = router
    BridgeRequestHandler.target_manager = target_manager
    BridgeRequestHandler.config = config
    if p2p_manager is not None:
        BridgeRequestHandler.p2p_manager = p2p_manager

    # By default, bind exclusively to localhost (127.0.0.1) for zero exposure.
    # Only bind to 0.0.0.0 if expose_lan is explicitly declared True.
    host = "0.0.0.0" if (expose_lan or config.expose_lan) else "127.0.0.1"
    server = BridgeServer((host, config.port), BridgeRequestHandler)
    return server


def run(port: Optional[int] = None, expose_lan: bool = False, p2p: bool = True):
    """Starts the Prompt Bridge HTTP server with default P2P Zero-Exposure WebRTC pairing."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    config = Config()
    if port:
        config.port = port
    if expose_lan:
        config.expose_lan = True

    lan_ip = get_lan_ip()
    mdns_host = get_mdns_hostname()
    p2p_manager = P2PManager() if p2p else None
    server = create_server(config, p2p_manager=p2p_manager, expose_lan=config.expose_lan)

    if config.expose_lan:
        print(f"\n🌐 Direct LAN IP Exposure Enabled (--expose-lan):", flush=True)
        print(f"  • Local:   http://localhost:{config.port}", flush=True)
        print(f"  • Phone:   http://{lan_ip}:{config.port}", flush=True)
        if mdns_host:
            print(f"  • mDNS:    http://{mdns_host}:{config.port}\n", flush=True)
    else:
        print(f"\n🔒 P2P Zero-Exposure Active (Default - Localhost Only):", flush=True)
        print(f"  • Local:   http://localhost:{config.port}", flush=True)
        print(f"  • Network: Zero listening ports on LAN / Public Wi-Fi", flush=True)
        print(f"  • Tip:     Pass --expose-lan to exclusively open port on LAN IP\n", flush=True)

    if p2p_manager:
        p2p_manager.start_relay(BridgeRequestHandler.router, BridgeRequestHandler.target_manager)
        print(p2p_manager.get_pairing_banner(lan_ip=lan_ip, port=config.port, is_lan_exposed=config.expose_lan, mdns_host=mdns_host), flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPrompt Bridge stopped.")
    finally:
        if p2p_manager:
            p2p_manager.stop()
