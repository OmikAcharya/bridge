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
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Optional

from bridge.models import PromptRequest, DeliveryResult
from bridge.config import Config
from bridge.discovery import SessionDiscovery
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory, get_adapter
from bridge.router import PromptRouter
from bridge.compressor import compress_caveman_ultra, format_raw_tail
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



HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content">
    <meta name="theme-color" content="#09090b">
    <title>Prompt Bridge</title>
    <script src="https://unpkg.com/mqtt@5.3.5/dist/mqtt.min.js"></script>
    <style>
        :root {
            --app-height: 100dvh;
            --bg: #09090b;
            --surface: #141417;
            --surface-hover: #1c1c20;
            --surface-active: #222228;
            --surface-border: #27272a;
            --surface-border-focus: #52525b;
            --text-main: #f4f4f5;
            --text-muted: #8e8e93;
            --text-dim: #52525b;
            --accent: #ffffff;
            --accent-text: #09090b;
            --green: #22c55e;
            --green-glow: rgba(34, 197, 94, 0.35);
            --yellow: #eab308;
            --yellow-glow: rgba(234, 179, 8, 0.35);
            --red: #ef4444;
            --blue: #3b82f6;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            --font-mono: ui-monospace, "SF Mono", Menlo, monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        html, body {
            height: 100%;
            height: var(--app-height, 100dvh);
            max-height: var(--app-height, 100dvh);
            overflow: hidden;
        }

        body {
            font-family: var(--font-sans);
            background-color: var(--bg);
            color: var(--text-main);
            display: flex;
            flex-direction: column;
            padding: calc(8px + env(safe-area-inset-top)) 14px calc(10px + env(safe-area-inset-bottom)) 14px;
            transition: padding 0.15s ease;
        }

        /* Header */
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 2px 2px 8px 2px;
            flex-shrink: 0;
            transition: padding 0.15s ease;
        }

        .title-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 8px var(--green-glow);
            transition: background-color 0.2s, box-shadow 0.2s;
        }

        .status-dot.offline {
            background: var(--red);
            box-shadow: 0 0 8px rgba(239, 68, 68, 0.4);
        }

        .title {
            font-size: 14px;
            font-weight: 600;
            letter-spacing: -0.01em;
            color: var(--text-main);
        }

        .conn-badge {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            border-radius: 4px;
            padding: 1px 5px;
            letter-spacing: 0.02em;
            display: inline-flex;
            align-items: center;
            gap: 3px;
            transition: all 0.2s ease;
        }

        .conn-badge.p2p {
            color: var(--green);
            background: rgba(34, 197, 94, 0.12);
            border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .conn-badge.lan {
            color: var(--yellow);
            background: rgba(234, 179, 8, 0.12);
            border: 1px solid rgba(234, 179, 8, 0.3);
        }

        .conn-badge.local {
            color: var(--blue);
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn-icon-subtle {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            color: var(--text-muted);
            padding: 5px 8px;
            font-size: 11px;
            font-family: var(--font-mono);
            display: flex;
            align-items: center;
            gap: 5px;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
        }

        .btn-icon-subtle:active {
            background: var(--surface-hover);
            color: var(--text-main);
        }

        /* Bento Grid for Sessions */
        .bento-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            margin-bottom: 10px;
            flex-shrink: 0;
            transition: opacity 0.15s ease, max-height 0.2s ease, margin 0.15s ease;
        }

        .bento-tile {
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 12px;
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            cursor: pointer;
            transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.1s ease;
            position: relative;
            user-select: none;
        }

        .bento-tile.active {
            background: #1c1c22;
            border-color: var(--text-main);
            box-shadow: 0 0 12px rgba(255, 255, 255, 0.05);
        }

        .bento-tile:active {
            transform: scale(0.98);
        }

        .bento-tile.full-width {
            grid-column: span 2;
        }

        .tile-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 6px;
        }

        .tile-name-group {
            display: flex;
            align-items: center;
            gap: 6px;
            min-width: 0;
        }

        .tile-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--green);
            flex-shrink: 0;
        }

        .tile-dot.busy {
            background: var(--yellow);
        }

        .tile-dot.offline {
            background: var(--red);
        }

        .tile-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .tile-badge {
            font-family: var(--font-mono);
            font-size: 9px;
            font-weight: 600;
            padding: 2px 5px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.06);
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.03em;
            flex-shrink: 0;
        }

        .tile-path {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .tile-cmd {
            font-family: var(--font-mono);
            font-size: 10px;
            color: var(--text-dim);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* Keyboard Active Mini Session Bar */
        .keyboard-mini-bar {
            display: none;
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            padding: 4px 10px;
            margin-bottom: 6px;
            font-size: 11px;
            font-family: var(--font-mono);
            color: var(--text-muted);
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
        }

        .keyboard-mini-bar .mini-target-name {
            color: var(--text-main);
            font-weight: 600;
        }

        /* Keyboard Open Layout Mode */
        body.keyboard-active {
            padding-top: calc(4px + env(safe-area-inset-top));
            padding-bottom: 6px;
        }

        body.keyboard-active header {
            padding-bottom: 4px;
        }

        body.keyboard-active .bento-grid {
            display: none;
        }

        body.keyboard-active .keyboard-mini-bar {
            display: flex;
        }

        body.keyboard-active .quick-actions-bar {
            padding-top: 4px;
            padding-bottom: 2px;
        }

        body.keyboard-active .controls {
            margin-top: 4px;
            gap: 4px;
        }

        body.keyboard-active .send-btn {
            height: 48px;
        }

        body.keyboard-active .send-btn-title {
            font-size: 14px;
        }

        /* Standalone Live Activity Banner */
        .activity-banner-btn {
            width: 100%;
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 12px;
            padding: 8px 12px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            cursor: pointer;
            margin-bottom: 8px;
            flex-shrink: 0;
            user-select: none;
            transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.1s ease;
        }

        .activity-banner-btn:active {
            background: var(--surface-hover);
            border-color: var(--surface-border-focus);
            transform: scale(0.985);
        }

        .keyboard-active .activity-banner-btn {
            display: none;
        }

        .banner-left {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }

        .banner-text-group {
            display: flex;
            align-items: center;
            gap: 7px;
            min-width: 0;
        }

        .banner-agent-name {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 160px;
        }

        .banner-status-tag {
            font-size: 10px;
            font-family: var(--font-mono);
            color: var(--text-muted);
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--surface-border);
            padding: 2px 6px;
            border-radius: 4px;
            white-space: nowrap;
        }

        .banner-right {
            display: flex;
            align-items: center;
            gap: 4px;
            color: var(--text-muted);
            font-size: 11px;
            font-family: var(--font-mono);
            flex-shrink: 0;
        }

        .banner-arrow {
            font-size: 11px;
            color: var(--text-main);
        }

        /* Editor Area */
        .editor-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 12px;
            overflow: hidden;
            transition: border-color 0.15s ease;
            min-height: 80px;
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
            font-size: 17px;
            line-height: 1.4;
            padding: 12px 14px;
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
            padding: 5px 12px 6px 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 11px;
            color: var(--text-muted);
            font-family: var(--font-mono);
            flex-shrink: 0;
        }

        .editor-actions {
            display: flex;
            align-items: center;
            gap: 10px;
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

        /* Action Bar */
        .quick-actions-bar {
            display: flex;
            gap: 6px;
            overflow-x: auto;
            scrollbar-width: none;
            padding: 6px 0 4px 0;
            flex-shrink: 0;
        }

        .quick-actions-bar::-webkit-scrollbar {
            display: none;
        }

        .action-chip {
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 8px;
            padding: 6px 11px;
            font-size: 12px;
            font-weight: 500;
            color: var(--text-muted);
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.12s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            font-family: var(--font-sans);
        }

        .action-chip:active {
            background: var(--surface-hover);
            color: var(--text-main);
            transform: scale(0.96);
        }

        .action-chip.danger:active {
            background: rgba(239, 68, 68, 0.2);
            color: var(--red);
            border-color: var(--red);
        }

        /* Controls & Enter Toggle */
        .controls {
            margin-top: 6px;
            display: flex;
            flex-direction: column;
            gap: 6px;
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
            font-size: 12px;
            color: var(--text-muted);
            cursor: pointer;
            user-select: none;
        }

        .toggle-switch {
            position: relative;
            width: 32px;
            height: 18px;
            background: #27272a;
            border-radius: 10px;
            transition: background 0.2s;
            display: inline-block;
        }

        .toggle-switch::after {
            content: '';
            position: absolute;
            width: 14px;
            height: 14px;
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
            background: var(--blue);
        }

        input[type="checkbox"]:checked + .toggle-switch::after {
            transform: translateX(14px);
        }

        .send-btn {
            width: 100%;
            height: 52px;
            border-radius: 12px;
            border: none;
            background: var(--accent);
            color: var(--accent-text);
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.01em;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 1px;
            transition: background 0.15s, transform 0.1s, opacity 0.15s;
            box-shadow: 0 4px 14px rgba(255, 255, 255, 0.08);
        }

        .send-btn:active {
            transform: scale(0.985);
        }

        .send-btn-title {
            font-size: 15px;
            font-weight: 600;
        }

        .send-btn-target {
            font-size: 11px;
            font-weight: 400;
            font-family: var(--font-mono);
            opacity: 0.7;
        }

        .send-btn.success {
            background: var(--green);
            color: white;
            box-shadow: 0 4px 14px var(--green-glow);
        }

        .send-btn.error {
            background: var(--red);
            color: white;
        }

        .send-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .activity-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--green);
            flex-shrink: 0;
        }

        .activity-dot.busy {
            background: var(--blue);
            animation: pulse 1.5s infinite;
        }

        /* Full Screen Activity Cockpit Modal */
        .cockpit-modal {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            height: 100dvh;
            background: var(--bg);
            z-index: 95;
            display: flex;
            flex-direction: column;
            opacity: 0;
            pointer-events: none;
            transform: scale(0.99);
            transition: opacity 0.15s ease, transform 0.15s ease;
        }

        .cockpit-modal.open {
            opacity: 1;
            pointer-events: auto;
            transform: scale(1);
        }

        .cockpit-header {
            height: 48px;
            border-bottom: 1px solid var(--surface-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 12px;
            background: var(--surface);
            flex-shrink: 0;
        }

        .cockpit-target-group {
            display: flex;
            align-items: center;
            gap: 7px;
            min-width: 0;
        }

        .cockpit-target-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-main);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 150px;
        }

        .cockpit-header-actions {
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* Segmented Mode Pill */
        .mode-segmented {
            display: flex;
            background: var(--bg);
            border: 1px solid var(--surface-border);
            border-radius: 6px;
            padding: 2px;
            gap: 2px;
        }

        .mode-pill {
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 10px;
            font-family: var(--font-mono);
            font-weight: 500;
            padding: 2px 7px;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.12s ease;
        }

        .mode-pill.active {
            background: var(--surface-hover);
            color: var(--text-main);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
        }

        .btn-icon-micro {
            background: var(--surface-hover);
            border: 1px solid var(--surface-border);
            color: var(--text-muted);
            width: 26px;
            height: 26px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.12s ease;
        }

        .btn-icon-micro:active {
            color: var(--text-main);
            border-color: var(--surface-border-focus);
        }

        .cockpit-activity-content {
            flex: 1;
            overflow-y: auto;
            padding: 14px;
            font-size: 13px;
            line-height: 1.55;
            color: var(--text-main);
            white-space: pre-wrap;
            word-break: break-word;
            -webkit-overflow-scrolling: touch;
            background: var(--bg);
        }

        .cockpit-activity-content.raw-view {
            font-family: var(--font-mono);
            font-size: 11px;
            color: var(--text-muted);
            white-space: pre;
            overflow-x: auto;
        }

        .activity-empty {
            color: var(--text-dim);
            font-size: 12px;
            font-family: var(--font-mono);
            font-style: italic;
        }

        /* Bottom Dictation Dialogue Bar */
        .cockpit-bottom-dock {
            background: var(--surface);
            border-top: 1px solid var(--surface-border);
            padding: 8px 12px calc(8px + env(safe-area-inset-bottom)) 12px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex-shrink: 0;
        }

        .cockpit-quick-chips {
            display: flex;
            align-items: center;
            gap: 6px;
            overflow-x: auto;
            scrollbar-width: none;
            padding-bottom: 2px;
        }

        .cockpit-quick-chips::-webkit-scrollbar {
            display: none;
        }

        .chip-mini {
            background: var(--surface-hover);
            border: 1px solid var(--surface-border);
            border-radius: 6px;
            color: var(--text-muted);
            font-size: 11px;
            font-family: var(--font-sans);
            font-weight: 500;
            padding: 4px 9px;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.1s ease;
        }

        .chip-mini:active {
            background: var(--surface-active);
            color: var(--text-main);
            transform: scale(0.96);
        }

        .chip-mini.danger {
            color: #f87171;
            border-color: rgba(239, 68, 68, 0.2);
        }

        .chip-mini.danger:active {
            background: rgba(239, 68, 68, 0.15);
        }

        .cockpit-input-row {
            display: flex;
            align-items: flex-end;
            gap: 8px;
        }

        #cockpitPrompt {
            flex: 1;
            min-height: 38px;
            max-height: 90px;
            resize: none;
            background: var(--bg);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            color: var(--text-main);
            font-family: var(--font-sans);
            font-size: 14px;
            padding: 9px 12px;
            line-height: 1.35;
            outline: none;
            transition: border-color 0.15s ease;
        }

        #cockpitPrompt:focus {
            border-color: var(--surface-border-focus);
        }

        .cockpit-send-btn {
            width: 38px;
            height: 38px;
            border-radius: 10px;
            border: none;
            background: var(--accent);
            color: var(--accent-text);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            flex-shrink: 0;
            transition: transform 0.1s ease, background 0.15s ease;
        }

        .cockpit-send-btn:active {
            transform: scale(0.92);
        }

        .cockpit-send-btn.success {
            background: var(--green);
            color: white;
        }

        /* History Modal */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 100;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
        }

        .modal-overlay.open {
            opacity: 1;
            pointer-events: auto;
        }

        .bottom-sheet {
            background: #141418;
            border-top: 1px solid var(--surface-border-focus);
            border-top-left-radius: 20px;
            border-top-right-radius: 20px;
            max-height: 80dvh;
            display: flex;
            flex-direction: column;
            transform: translateY(100%);
            transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
            padding: 12px 16px calc(16px + env(safe-area-inset-bottom)) 16px;
        }

        .modal-overlay.open .bottom-sheet {
            transform: translateY(0);
        }

        .sheet-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding-bottom: 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .sheet-title {
            font-size: 15px;
            font-weight: 600;
        }

        .sheet-close {
            background: rgba(255, 255, 255, 0.06);
            border: none;
            color: var(--text-muted);
            border-radius: 50%;
            width: 28px;
            height: 28px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }

        .history-list {
            overflow-y: auto;
            padding: 10px 0;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .history-card {
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 10px;
            padding: 10px 12px;
            cursor: pointer;
            transition: background 0.15s;
            font-size: 13px;
            line-height: 1.4;
            color: var(--text-main);
        }

        .history-card:active {
            background: var(--surface-hover);
        }
    </style>
</head>
<body>

    <!-- Top Bar -->
    <header>
        <div class="title-group">
            <div id="statusDot" class="status-dot"></div>
            <span class="title">Prompt Bridge</span>
            <div id="connBadge" class="conn-badge p2p" title="Connection Mode">🔒 P2P</div>
        </div>
        <div class="header-actions">
            <button id="historyBtn" class="btn-icon-subtle" title="Prompt History">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <polyline points="12 6 12 12 16 14"></polyline>
                </svg>
                <span>History</span>
            </button>
            <button id="refreshBtn" class="btn-icon-subtle" title="Refresh Sessions">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="23 4 23 10 17 10"></polyline>
                    <polyline points="1 20 1 14 7 14"></polyline>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                </svg>
            </button>
        </div>
    </header>

    <!-- Bento Grid Sessions -->
    <div id="bentoGrid" class="bento-grid">
        <!-- Injected dynamically via JS -->
    </div>

    <!-- Keyboard Open Mini Bar -->
    <div id="keyboardMiniBar" class="keyboard-mini-bar">
        <span>Target: <span id="miniTargetName" class="mini-target-name">Auto</span></span>
        <span id="miniTargetPath">~/Developer/bridge</span>
    </div>

    <!-- Full-Screen Activity & Dictation Cockpit Modal -->
    <div id="cockpitModal" class="cockpit-modal">
        <!-- Cockpit Header -->
        <div class="cockpit-header">
            <div class="cockpit-target-group">
                <div id="cockpitAgentDot" class="activity-dot"></div>
                <span id="cockpitTargetTitle" class="cockpit-target-title">Terminal Monitor</span>
            </div>
            <div class="cockpit-header-actions">
                <div class="mode-segmented">
                    <button type="button" id="pillUltra" class="mode-pill active">Ultra</button>
                    <button type="button" id="pillRaw" class="mode-pill">Raw</button>
                </div>
                <button id="refreshCockpitBtn" class="btn-icon-micro" title="Refresh Output">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="23 4 23 10 17 10"></polyline>
                        <polyline points="1 20 1 14 7 14"></polyline>
                        <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                    </svg>
                </button>
                <button id="closeCockpitBtn" class="btn-icon-micro" title="Close Log View">✕</button>
            </div>
        </div>

        <!-- Scrollable Full-Height Activity / Log Content -->
        <div id="cockpitActivityContent" class="cockpit-activity-content caveman-view">
            <div class="activity-empty">Connecting to terminal session...</div>
        </div>

        <!-- Thin Bottom Dictation Dialogue Bar -->
        <div class="cockpit-bottom-dock">
            <!-- Compact Quick Actions -->
            <div class="cockpit-quick-chips">
                <button id="cockpitBtnEnter" class="chip-mini" title="Send Return">↵ Return</button>
                <button id="cockpitBtnContinue" class="chip-mini" title="Send continue">Continue</button>
                <button id="cockpitBtnYes" class="chip-mini" title="Send 'y'">Yes</button>
                <button id="cockpitBtnNo" class="chip-mini" title="Send 'n'">No</button>
                <button id="cockpitBtnInterrupt" class="chip-mini danger" title="Send Ctrl+C">Ctrl+C</button>
            </div>

            <!-- Single/Multi-line Thin Dictation Input Row -->
            <div class="cockpit-input-row">
                <textarea 
                    id="cockpitPrompt" 
                    placeholder="Dictate prompt with Wispr Flow..." 
                    rows="1" 
                    autocomplete="off" 
                    autocorrect="on" 
                    spellcheck="true"
                ></textarea>
                <button id="cockpitSendBtn" class="cockpit-send-btn" title="Send to Agent">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13"></line>
                        <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                    </svg>
                </button>
            </div>
        </div>
    </div>

    <!-- Standalone Live Activity Banner (Matches Bento Card & Editor border radius and surface tokens) -->
    <button id="openCockpitBtn" class="activity-banner-btn" title="Open Full Live Terminal Cockpit">
        <div class="banner-left">
            <div id="headerAgentDot" class="activity-dot"></div>
            <div class="banner-text-group">
                <span id="headerAgentName" class="banner-agent-name">Antigravity — bridge</span>
                <span id="headerAgentStatus" class="banner-status-tag">Live Log ↗</span>
            </div>
        </div>
        <div class="banner-right">
            <span class="banner-hint">View Terminal</span>
            <span class="banner-arrow">↗</span>
        </div>
    </button>

    <!-- Editor -->
    <div class="editor-container">
        <textarea 
            id="prompt" 
            placeholder="Dictate with Wispr Flow or type..." 
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

    <!-- Quick Action Bar -->
    <div class="quick-actions-bar">
        <button id="btnEnterOnly" class="action-chip" title="Send Return">
            <span>Return ↵</span>
        </button>
        <button id="btnContinue" class="action-chip" title="Send continue">
            <span>Continue</span>
        </button>
        <button id="btnYes" class="action-chip" title="Send 'y'">
            <span>Yes</span>
        </button>
        <button id="btnNo" class="action-chip" title="Send 'n'">
            <span>No</span>
        </button>
        <button id="btnInterrupt" class="action-chip danger" title="Send Ctrl+C">
            <span>Ctrl+C</span>
        </button>
    </div>

    <!-- Send Button & Enter Toggle -->
    <div class="controls">
        <div class="options-row">
            <label class="toggle-label">
                <input type="checkbox" id="enterToggle">
                <span class="toggle-switch"></span>
                <span>Press Enter on Mac</span>
            </label>
        </div>

        <button id="sendBtn" class="send-btn">
            <span id="sendTitle" class="send-btn-title">Send & Execute</span>
            <span id="sendSubtitle" class="send-btn-target">to Active Agent</span>
        </button>
    </div>

    <!-- History Bottom Sheet -->
    <div id="historyModal" class="modal-overlay">
        <div class="bottom-sheet">
            <div class="sheet-header">
                <span class="sheet-title">Recent Prompts</span>
                <button id="closeHistoryModal" class="sheet-close">✕</button>
            </div>
            <div id="historyList" class="history-list">
                <!-- Populated dynamically -->
            </div>
        </div>
    </div>

    <script>
        const promptEl = document.getElementById('prompt');
        const sendBtn = document.getElementById('sendBtn');
        const sendTitle = document.getElementById('sendTitle');
        const sendSubtitle = document.getElementById('sendSubtitle');
        const metricsEl = document.getElementById('metrics');
        const clearBtn = document.getElementById('clearBtn');
        const undoBtn = document.getElementById('undoBtn');
        const enterToggle = document.getElementById('enterToggle');
        const statusDot = document.getElementById('statusDot');
        const refreshBtn = document.getElementById('refreshBtn');

        const bentoGrid = document.getElementById('bentoGrid');
        const miniTargetName = document.getElementById('miniTargetName');
        const miniTargetPath = document.getElementById('miniTargetPath');

        const historyModal = document.getElementById('historyModal');
        const historyList = document.getElementById('historyList');
        const historyBtn = document.getElementById('historyBtn');
        const closeHistoryModal = document.getElementById('closeHistoryModal');
        const btnEnterOnly = document.getElementById('btnEnterOnly');
        const btnContinue = document.getElementById('btnContinue');
        const btnYes = document.getElementById('btnYes');
        const btnNo = document.getElementById('btnNo');
        const btnInterrupt = document.getElementById('btnInterrupt');

        const openCockpitBtn = document.getElementById('openCockpitBtn');
        const headerAgentDot = document.getElementById('headerAgentDot');
        const headerAgentName = document.getElementById('headerAgentName');
        const headerAgentStatus = document.getElementById('headerAgentStatus');

        const cockpitModal = document.getElementById('cockpitModal');
        const cockpitAgentDot = document.getElementById('cockpitAgentDot');
        const cockpitTargetTitle = document.getElementById('cockpitTargetTitle');
        const cockpitActivityContent = document.getElementById('cockpitActivityContent');
        const cockpitPrompt = document.getElementById('cockpitPrompt');
        const cockpitSendBtn = document.getElementById('cockpitSendBtn');
        const closeCockpitBtn = document.getElementById('closeCockpitBtn');
        const refreshCockpitBtn = document.getElementById('refreshCockpitBtn');

        const cockpitBtnEnter = document.getElementById('cockpitBtnEnter');
        const cockpitBtnContinue = document.getElementById('cockpitBtnContinue');
        const cockpitBtnYes = document.getElementById('cockpitBtnYes');
        const cockpitBtnNo = document.getElementById('cockpitBtnNo');
        const cockpitBtnInterrupt = document.getElementById('cockpitBtnInterrupt');

        const pillUltra = document.getElementById('pillUltra');
        const pillRaw = document.getElementById('pillRaw');

        let lastCleared = '';
        let availableTargets = [];
        let selectedTargetId = localStorage.getItem('bridge_target_id') || 'auto';
        let promptHistory = JSON.parse(localStorage.getItem('bridge_prompt_history') || '[]');
        let lastSignature = '';

        let isCavemanUltra = localStorage.getItem('bridge_caveman_output') !== 'false';
        updateModeUI();

        function updateModeUI() {
            if (isCavemanUltra) {
                pillUltra.classList.add('active');
                pillRaw.classList.remove('active');
                cockpitActivityContent.className = 'cockpit-activity-content caveman-view';
            } else {
                pillRaw.classList.add('active');
                pillUltra.classList.remove('active');
                cockpitActivityContent.className = 'cockpit-activity-content raw-view';
            }
        }

        pillUltra.addEventListener('click', () => {
            if (isCavemanUltra) return;
            isCavemanUltra = true;
            localStorage.setItem('bridge_caveman_output', 'true');
            updateModeUI();
            fetchActivityTail();
            haptic(10);
        });

        pillRaw.addEventListener('click', () => {
            if (!isCavemanUltra) return;
            isCavemanUltra = false;
            localStorage.setItem('bridge_caveman_output', 'false');
            updateModeUI();
            fetchActivityTail();
            haptic(10);
        });

        function autoResize(el) {
            el.style.height = 'auto';
            el.style.height = Math.min(el.scrollHeight, 100) + 'px';
        }

        function openCockpit() {
            cockpitModal.classList.add('open');
            cockpitPrompt.value = promptEl.value;
            autoResize(cockpitPrompt);
            fetchActivityTail();
            haptic(10);
        }

        function closeCockpit() {
            cockpitModal.classList.remove('open');
            promptEl.value = cockpitPrompt.value;
            updateMetrics();
            haptic(10);
        }

        openCockpitBtn.addEventListener('click', openCockpit);
        closeCockpitBtn.addEventListener('click', closeCockpit);
        refreshCockpitBtn.addEventListener('click', () => {
            fetchActivityTail();
            haptic(10);
        });

        let activityAbortController = null;

        async function fetchActivityTail() {
            if (activityAbortController) {
                activityAbortController.abort();
            }
            activityAbortController = new AbortController();

            try {
                const targetId = selectedTargetId;
                const mode = isCavemanUltra ? 'ultra' : 'raw';
                const res = await fetch(`/terminal/tail?target=${encodeURIComponent(targetId)}&mode=${mode}&lines=40`, {
                    cache: 'no-store',
                    signal: activityAbortController.signal
                });
                if (!res.ok) return;
                const data = await res.json();
                if (targetId !== selectedTargetId) return;

                if (data.success && data.content) {
                    cockpitActivityContent.textContent = data.content;
                    if (data.is_busy) {
                        headerAgentDot.classList.add('busy');
                        cockpitAgentDot.classList.add('busy');
                        if (headerAgentStatus) headerAgentStatus.textContent = 'Busy ↗';
                    } else {
                        headerAgentDot.classList.remove('busy');
                        cockpitAgentDot.classList.remove('busy');
                        if (headerAgentStatus) headerAgentStatus.textContent = 'Live Log ↗';
                    }
                    if (data.target_name) {
                        cockpitTargetTitle.textContent = data.target_name;
                        headerAgentName.textContent = data.target_name;
                    }
                    cockpitActivityContent.scrollTop = cockpitActivityContent.scrollHeight;
                }
            } catch (e) {
                if (e.name === 'AbortError') return;
            }
        }

        // Dynamic Viewport & Purely Height-Driven Grid Collapse
        let baseViewportHeight = window.innerHeight;

        function updateViewportHeight() {
            const currentH = window.visualViewport ? window.visualViewport.height : window.innerHeight;
            document.documentElement.style.setProperty('--app-height', `${currentH}px`);

            if (currentH > baseViewportHeight) {
                baseViewportHeight = currentH;
            }

            // Grid collapses purely based on viewport height (e.g. keyboard presence or compact display)
            const isHeightRestricted = (baseViewportHeight - currentH > 130) || (currentH < 500);

            if (isHeightRestricted) {
                document.body.classList.add('keyboard-active');
            } else {
                document.body.classList.remove('keyboard-active');
            }
        }

        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', updateViewportHeight);
            window.visualViewport.addEventListener('scroll', updateViewportHeight);
        }
        window.addEventListener('resize', updateViewportHeight);

        if (localStorage.getItem('bridge_enter') === 'false') {
            enterToggle.checked = false;
        } else {
            enterToggle.checked = true;
        }

        enterToggle.addEventListener('change', () => {
            localStorage.setItem('bridge_enter', enterToggle.checked);
            updateSendButtonLabel();
            haptic(10);
        });

        function haptic(pattern = 12) {
            if (navigator.vibrate) {
                try { navigator.vibrate(pattern); } catch (e) {}
            }
        }

        function savePromptToHistory(text) {
            if (!text || text.trim().length < 2) return;
            promptHistory = promptHistory.filter(p => p !== text);
            promptHistory.unshift(text);
            if (promptHistory.length > 30) promptHistory.pop();
            localStorage.setItem('bridge_prompt_history', JSON.stringify(promptHistory));
        }

        function updateMetrics() {
            const val = promptEl.value;
            const words = val.trim() ? val.trim().split(/\\s+/).length : 0;
            const chars = val.length;
            metricsEl.textContent = `${words} ${words === 1 ? 'word' : 'words'} · ${chars} chars`;
        }

        promptEl.addEventListener('input', () => {
            cockpitPrompt.value = promptEl.value;
            autoResize(cockpitPrompt);
            updateMetrics();
        });

        cockpitPrompt.addEventListener('input', () => {
            promptEl.value = cockpitPrompt.value;
            autoResize(cockpitPrompt);
            updateMetrics();
        });

        clearBtn.addEventListener('click', () => {
            if (!promptEl.value) return;
            lastCleared = promptEl.value;
            promptEl.value = '';
            cockpitPrompt.value = '';
            autoResize(cockpitPrompt);
            undoBtn.style.display = 'inline';
            updateMetrics();
            promptEl.focus();
            haptic(10);
        });

        undoBtn.addEventListener('click', () => {
            if (!lastCleared) return;
            promptEl.value = lastCleared;
            cockpitPrompt.value = lastCleared;
            autoResize(cockpitPrompt);
            lastCleared = '';
            undoBtn.style.display = 'none';
            updateMetrics();
            promptEl.focus();
            haptic(10);
        });

        function getResolvedTarget() {
            if (selectedTargetId === 'auto') {
                return availableTargets.find(t => t.agent && t.agent !== 'shell' && t.agent !== 'legacy' && t.id !== 'focused') ||
                       availableTargets.find(t => t.id !== 'focused') ||
                       availableTargets[0] || null;
            }
            return availableTargets.find(t => t.id === selectedTargetId) || null;
        }

        function renderBentoGrid() {
            bentoGrid.innerHTML = '';

            // 1. Auto Tile (Full width on top)
            const autoResolved = availableTargets.find(t => t.agent && t.agent !== 'shell' && t.agent !== 'legacy' && t.id !== 'focused') || availableTargets[0];
            const autoTile = document.createElement('div');
            autoTile.className = `bento-tile full-width ${selectedTargetId === 'auto' ? 'active' : ''}`;
            const resolvedName = autoResolved ? (autoResolved.agent_name || autoResolved.name) : 'Searching...';
            const resolvedPath = autoResolved ? ((autoResolved.metadata && autoResolved.metadata.compact_cwd) || autoResolved.folder || '~') : '';
            
            autoTile.innerHTML = `
                <div class="tile-header">
                    <div class="tile-name-group">
                        <div class="tile-dot"></div>
                        <span class="tile-title">Auto-detect Agent</span>
                    </div>
                    <span class="tile-badge">AUTO</span>
                </div>
                <div class="tile-path">Routing to ${resolvedName}${resolvedPath ? ' (' + resolvedPath + ')' : ''}</div>
            `;
            autoTile.addEventListener('click', () => selectTarget('auto'));
            bentoGrid.appendChild(autoTile);

            // 2. Discovered Session Tiles
            availableTargets.forEach(t => {
                const tile = document.createElement('div');
                const isSelected = (selectedTargetId === t.id);
                tile.className = `bento-tile ${isSelected ? 'active' : ''}`;
                const isBusy = (t.status === 'busy' || t.is_busy);
                const dotClass = isBusy ? 'tile-dot busy' : 'tile-dot';
                const compactPath = (t.metadata && t.metadata.compact_cwd) || t.folder || '~';
                const ttyStr = t.tty ? t.tty.replace('/dev/', '') : '';
                const shortName = t.agent_name || t.name;
                const cmdStr = (t.metadata && t.metadata.short_cmd) || t.cmd || '';

                if (t.id === 'focused') {
                    tile.innerHTML = `
                        <div class="tile-header">
                            <div class="tile-name-group">
                                <div class="tile-dot"></div>
                                <span class="tile-title">Focused App</span>
                            </div>
                            <span class="tile-badge">MAC</span>
                        </div>
                        <div class="tile-path">Active Window</div>
                    `;
                } else {
                    tile.innerHTML = `
                        <div class="tile-header">
                            <div class="tile-name-group">
                                <div class="${dotClass}"></div>
                                <span class="tile-title">${shortName}</span>
                            </div>
                            <span class="tile-badge">${ttyStr.toUpperCase()}</span>
                        </div>
                        <div class="tile-path">${compactPath}</div>
                        ${cmdStr ? `<div class="tile-cmd">${cmdStr}</div>` : ''}
                    `;
                }
                tile.addEventListener('click', () => selectTarget(t.id));
                bentoGrid.appendChild(tile);
            });

            updateSendButtonLabel();
        }

        function updateSendButtonLabel() {
            const resolved = getResolvedTarget();
            const willEnter = enterToggle.checked;

            if (selectedTargetId === 'focused') {
                sendTitle.textContent = willEnter ? 'Paste & Enter on Mac' : 'Paste to Focused Window';
                sendSubtitle.textContent = 'Active application on Mac';
                miniTargetName.textContent = 'Focused App';
                miniTargetPath.textContent = 'Active Window';
                return;
            }

            if (resolved) {
            if (resolved) {
                let targetDisplay = resolved.name;
                if (selectedTargetId === 'auto') {
                    targetDisplay = `${resolved.agent_name || resolved.name}`;
                }
                sendTitle.textContent = 'Send Prompt';
                sendSubtitle.textContent = `Route to ${targetDisplay}`;
                miniTargetName.textContent = targetDisplay;
                miniTargetPath.textContent = resolved.cwd || resolved.tty || '--';
            } else {
                sendTitle.textContent = 'Send Prompt';
                sendSubtitle.textContent = 'No terminal target';
                miniTargetName.textContent = 'Offline';
                miniTargetPath.textContent = '--';
            }
        }

        function updateActivityHeaderOptimistic() {
            const resolved = getResolvedTarget();
            if (resolved) {
                const name = (selectedTargetId === 'auto' ? (resolved.agent_name || resolved.name) : resolved.name) || 'Live Log';
                if (headerAgentName) headerAgentName.textContent = name;
                if (cockpitTargetTitle) cockpitTargetTitle.textContent = name;
                const isBusy = (resolved.status === 'busy' || resolved.is_busy);
                if (isBusy) {
                    headerAgentDot.classList.add('busy');
                    cockpitAgentDot.classList.add('busy');
                    if (headerAgentStatus) headerAgentStatus.textContent = 'Busy ↗';
                } else {
                    headerAgentDot.classList.remove('busy');
                    cockpitAgentDot.classList.remove('busy');
                    if (headerAgentStatus) headerAgentStatus.textContent = 'Live Log ↗';
                }
            }
        }

        function selectTarget(targetId) {
            selectedTargetId = targetId;
            localStorage.setItem('bridge_target_id', selectedTargetId);
            haptic(15);
            renderBentoGrid();
            updateActivityHeaderOptimistic();
            fetchActivityTail();
        }

        function openHistorySheet() {
            historyList.innerHTML = '';
            if (promptHistory.length === 0) {
                historyList.innerHTML = `<div style="color:var(--text-dim); text-align:center; padding: 20px; font-family:var(--font-mono); font-size:12px;">No recent prompts</div>`;
            } else {
                promptHistory.forEach(text => {
                    const card = document.createElement('div');
                    card.className = 'history-card';
                    card.textContent = text;
                    card.addEventListener('click', () => {
                        promptEl.value = text;
                        updateMetrics();
                        closeModal(historyModal);
                        promptEl.focus();
                        haptic(12);
                    });
                    historyList.appendChild(card);
                });
            }
            openModal(historyModal);
        }

        function openModal(el) {
            el.classList.add('open');
            haptic(10);
        }

        function closeModal(el) {
            el.classList.remove('open');
        }

        historyBtn.addEventListener('click', openHistorySheet);
        closeHistoryModal.addEventListener('click', () => closeModal(historyModal));
        historyModal.addEventListener('click', (e) => { if (e.target === historyModal) closeModal(historyModal); });

        async function fetchTargets(force = false) {
            try {
                let data = null;
                if (isP2P) {
                    data = await p2pRequest('get_targets');
                } else {
                    const res = await fetch('/targets', { cache: 'no-store' });
                    if (!res.ok) throw new Error();
                    data = await res.json();
                }
                availableTargets = data.targets || [];

                const newSignature = JSON.stringify(availableTargets.map(t => [
                    t.id, t.name, t.status, t.is_busy, t.cwd, t.cmd, t.tty
                ]));

                if (!force && newSignature === lastSignature) {
                    updateSendButtonLabel();
                    updateActivityHeaderOptimistic();
                    return;
                }

                lastSignature = newSignature;
                renderBentoGrid();
                updateActivityHeaderOptimistic();
            } catch (e) {
                // Keep UI stable if offline
            }
        }

        refreshBtn.addEventListener('click', async () => {
            haptic(10);
            refreshBtn.style.transform = 'rotate(180deg)';
            refreshBtn.style.transition = 'transform 0.3s ease';
            await fetchTargets(true);
            setTimeout(() => {
                refreshBtn.style.transform = 'none';
                refreshBtn.style.transition = 'none';
            }, 300);
        });

        // Core Send function
        async function executePrompt(customText = null, action = null) {
            const text = (customText !== null) ? customText : promptEl.value.trim();
            if (!text && action === null) {
                promptEl.focus();
                return;
            }

            haptic(20);
            const initialTitle = sendTitle.textContent;
            const initialSubtitle = sendSubtitle.textContent;

            sendBtn.disabled = true;
            sendTitle.textContent = 'Sending...';

            try {
                const sendEnter = enterToggle.checked;
                const resolvedAction = action || (sendEnter ? 'execute' : 'paste');
                let data = null;

                if (isP2P) {
                    const res = await p2pRequest('prompt', {
                        target: selectedTargetId,
                        prompt: text,
                        act: resolvedAction
                    });
                    if (!res || !res.success) {
                        throw new Error((res && res.error) ? res.error : 'P2P delivery failed');
                    }
                    data = res.result || { success: true, message: 'Delivered directly to session' };
                } else {
                    const res = await fetch('/prompt', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            target: selectedTargetId,
                            prompt: text,
                            action: resolvedAction
                        })
                    });
                    data = await res.json();
                    if (!res.ok || !data.success) {
                        throw new Error(data.error || 'Delivery failed');
                    }
                }

                haptic([30, 40, 30]);
                sendBtn.classList.add('success');
                cockpitSendBtn.classList.add('success');
                sendTitle.textContent = 'Sent ✓';
                sendSubtitle.textContent = data.message || 'Delivered directly to session';

                if (customText === null) {
                    savePromptToHistory(text);
                    promptEl.value = '';
                    cockpitPrompt.value = '';
                    autoResize(cockpitPrompt);
                    undoBtn.style.display = 'none';
                    updateMetrics();
                }

                setTimeout(fetchActivityTail, 350);

                setTimeout(() => {
                    sendBtn.classList.remove('success');
                    cockpitSendBtn.classList.remove('success');
                    sendBtn.disabled = false;
                    updateSendButtonLabel();
                    if (!cockpitModal.classList.contains('open')) {
                        promptEl.focus();
                    }
                }, 600);

            } catch (err) {
                haptic([60, 60, 60]);
                sendBtn.classList.add('error');
                sendTitle.textContent = 'Delivery Error';
                sendSubtitle.textContent = err.message || 'Check terminal session';
                setTimeout(() => {
                    sendBtn.classList.remove('error');
                    sendBtn.disabled = false;
                    sendTitle.textContent = initialTitle;
                    sendSubtitle.textContent = initialSubtitle;
                }, 2000);
            }
        }

        // Instant Touch execution on mobile (prevents losing focus/keyboard lag)
        function attachInstantTap(btn, callback) {
            btn.addEventListener('pointerdown', (e) => {
                e.preventDefault();
                callback();
            });
        }

        attachInstantTap(sendBtn, () => executePrompt(null, null));
        attachInstantTap(btnEnterOnly, () => executePrompt('', 'raw_enter'));
        attachInstantTap(btnContinue, () => executePrompt('continue', 'execute'));
        attachInstantTap(btnYes, () => executePrompt('y', 'execute'));
        attachInstantTap(btnNo, () => executePrompt('n', 'execute'));
        attachInstantTap(btnInterrupt, () => executePrompt('', 'interrupt'));

        // Cockpit Dock actions
        attachInstantTap(cockpitSendBtn, () => executePrompt(null, null));
        attachInstantTap(cockpitBtnEnter, () => executePrompt('', 'raw_enter'));
        attachInstantTap(cockpitBtnContinue, () => executePrompt('continue', 'execute'));
        attachInstantTap(cockpitBtnYes, () => executePrompt('y', 'execute'));
        attachInstantTap(cockpitBtnNo, () => executePrompt('n', 'execute'));
        attachInstantTap(cockpitBtnInterrupt, () => executePrompt('', 'interrupt'));

        window.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                executePrompt(null, null);
            }
        });

        let consecutivePingFails = 0;
        async function ping() {
            if (isP2P) {
                try {
                    if (isP2PReady) {
                        await p2pRequest('ping');
                        consecutivePingFails = 0;
                        statusDot.classList.remove('offline');
                    }
                } catch (e) {
                    consecutivePingFails++;
                    if (consecutivePingFails >= 2) {
                        statusDot.classList.add('offline');
                    }
                }
                return;
            }

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 2500);
                const res = await fetch('/ping', { cache: 'no-store', signal: controller.signal });
                clearTimeout(timeoutId);
                if (res.ok) {
                    consecutivePingFails = 0;
                    statusDot.classList.remove('offline');
                } else {
                    throw new Error();
                }
            } catch (e) {
                consecutivePingFails++;
                if (consecutivePingFails >= 2) {
                    statusDot.classList.add('offline');
                }
            }
        }

        // Connection Security & Mode Indicator
        const connBadge = document.getElementById('connBadge');
        const hashParams = new URLSearchParams(window.location.hash.replace('#', ''));
        const p2pRoom = hashParams.get('room');
        const p2pKey = hashParams.get('key');
        const isP2P = Boolean(p2pRoom) || window.location.hostname.includes('github.io');

        let mqttClient = null;
        let isP2PReady = false;
        let reqSeq = 1;
        const pendingRequests = new Map();

        function updateConnectionBadge(state = null) {
            if (!connBadge) return;
            const host = window.location.hostname;
            if (isP2PReady || state === 'p2p') {
                connBadge.textContent = '🔒 P2P E2EE';
                connBadge.className = 'conn-badge p2p';
                connBadge.title = 'Direct End-to-End Encrypted Relay';
            } else if (isP2P) {
                connBadge.textContent = '🔒 P2P (Connecting...)';
                connBadge.className = 'conn-badge p2p';
                connBadge.title = 'Connecting to P2P relay...';
            } else if (host === 'localhost' || host === '127.0.0.1') {
                connBadge.textContent = '💻 Localhost';
                connBadge.className = 'conn-badge local';
                connBadge.title = 'Connected locally on Mac';
            } else {
                connBadge.textContent = '🌐 LAN Direct';
                connBadge.className = 'conn-badge lan';
                connBadge.title = 'Connected over Exposed LAN IP';
            }
        }

        if (isP2P && p2pRoom && typeof mqtt !== 'undefined') {
            initP2PRelay(p2pRoom, p2pKey);
        } else {
            updateConnectionBadge();
        }

        function initP2PRelay(room, key) {
            updateConnectionBadge('p2p_connecting');
            try {
                mqttClient = mqtt.connect('wss://broker.emqx.io:8084/mqtt', {
                    clientId: 'phone_' + Math.random().toString(16).slice(2, 10),
                    clean: true,
                    reconnectPeriod: 2000,
                });

                mqttClient.on('connect', () => {
                    mqttClient.subscribe(`pb/${room}/phone`, { qos: 0 });
                    isP2PReady = true;
                    statusDot.classList.remove('offline');
                    updateConnectionBadge('p2p');
                    fetchTargets(true);
                    fetchActivityTail();
                });

                mqttClient.on('message', (topic, payload) => {
                    try {
                        const data = JSON.parse(payload.toString());
                        if (data.id && pendingRequests.has(data.id)) {
                            const { resolve } = pendingRequests.get(data.id);
                            pendingRequests.delete(data.id);
                            resolve(data);
                        }
                    } catch (err) {}
                });

                mqttClient.on('offline', () => {
                    isP2PReady = false;
                    statusDot.classList.add('offline');
                    updateConnectionBadge('p2p_offline');
                });
            } catch (e) {
                console.error('MQTT P2P error:', e);
            }
        }

        function p2pRequest(action, params = {}) {
            return new Promise((resolve, reject) => {
                if (!mqttClient || !isP2PReady) {
                    return reject(new Error('P2P not connected'));
                }
                const id = reqSeq++;
                const timeout = setTimeout(() => {
                    if (pendingRequests.has(id)) {
                        pendingRequests.delete(id);
                        reject(new Error('P2P request timeout'));
                    }
                }, 4500);

                pendingRequests.set(id, {
                    resolve: (data) => {
                        clearTimeout(timeout);
                        resolve(data);
                    }
                });

                const msg = Object.assign({ id, action, key: p2pKey }, params);
                mqttClient.publish(`pb/${p2pRoom}/mac`, JSON.stringify(msg));
            });
        }

        // Instant reconnection when phone unlocks, wakes up from sleep, or tab regains focus
        function handleMobileWakeup() {
            consecutivePingFails = 0;
            ping();
            fetchTargets(false);
        }

        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                handleMobileWakeup();
            }
        });
        window.addEventListener('focus', handleMobileWakeup);
        window.addEventListener('online', handleMobileWakeup);

        // Initialize
        updateViewportHeight();
        ping();
        fetchTargets(true);
        fetchActivityTail();
        setInterval(ping, 4000);
        setInterval(() => fetchTargets(false), 5000);
        setInterval(fetchActivityTail, 2500);
        updateMetrics();
    </script>
</body>
</html>
"""


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
                data = HTML_TEMPLATE.encode("utf-8")
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
                data = HTML_TEMPLATE.encode("utf-8")
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
                mode = params.get("mode", ["ultra"])[0].lower()
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
                
                if mode == "ultra":
                    content = compress_caveman_ultra(raw_history)
                else:
                    content = format_raw_tail(raw_history, lines=lines_count)

                payload = json.dumps({
                    "success": True,
                    "target_id": target.id,
                    "target_name": target.name,
                    "mode": mode,
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
        print(f"\n🌐 Direct LAN IP Exposure Enabled (--expose-lan):")
        print(f"  • Local:   http://localhost:{config.port}")
        print(f"  • Phone:   http://{lan_ip}:{config.port}")
        if mdns_host:
            print(f"  • mDNS:    http://{mdns_host}:{config.port}\n")
    else:
        print(f"\n🔒 P2P Zero-Exposure Active (Default - Localhost Only):")
        print(f"  • Local:   http://localhost:{config.port}")
        print(f"  • Network: Zero listening ports on LAN / Public Wi-Fi")
        print(f"  • Tip:     Pass --expose-lan to exclusively open port on LAN IP\n")

    if p2p_manager:
        p2p_manager.start_relay(BridgeRequestHandler.router, BridgeRequestHandler.target_manager)
        print(p2p_manager.get_pairing_banner(lan_ip=lan_ip, port=config.port, is_lan_exposed=config.expose_lan, mdns_host=mdns_host))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPrompt Bridge stopped.")
    finally:
        if p2p_manager:
            p2p_manager.stop()
