#!/usr/bin/env python3
"""
Prompt Bridge: Voice dictation & text relay from mobile (Wispr Flow) to Mac.
Direct input router for specific, already-running terminal agent instances.
"""

import sys
from bridge.server import run

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
    run(port=port)
