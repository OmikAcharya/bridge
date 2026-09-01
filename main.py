#!/usr/bin/env python3
"""
Prompt Bridge: Voice dictation & text relay from mobile (Wispr Flow) to Mac.
Direct input router for specific, already-running terminal agent instances.
"""

import argparse
from bridge.server import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prompt Bridge: Zero-Exposure P2P Remote Dictation for Terminal Agents")
    parser.add_argument("port", nargs="?", type=int, default=None, help="Port to listen on (default: 8765)")
    parser.add_argument("--port", "-p", dest="opt_port", type=int, default=None, help="Port to listen on (default: 8765)")
    parser.add_argument(
        "--expose-lan",
        action="store_true",
        default=False,
        help="Exclusively expose Mac IP address and port on the local network (default: False, P2P localhost only)"
    )

    args = parser.parse_args()
    port = args.opt_port or args.port
    run(port=port, expose_lan=args.expose_lan)
