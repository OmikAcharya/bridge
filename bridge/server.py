"""
HTTP Server and Web Interface for Prompt Bridge.
"""

import os
import json
import socket
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from bridge.models import PromptRequest, DeliveryResult
from bridge.config import Config
from bridge.discovery import SessionDiscovery
from bridge.targets import TargetManager
from bridge.adapters.factory import AdapterFactory
from bridge.router import PromptRouter

logger = logging.getLogger("PromptBridge.Server")


def get_lan_ip() -> str:
    """Detects primary LAN IPv4 address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover, interactive-widget=resizes-content">
    <meta name="theme-color" content="#09090b">
    <title>Prompt Bridge</title>
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

        /* Editor Area */
        .editor-container {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: var(--surface);
            border: 1px solid var(--surface-border);
            border-radius: 14px;
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

    <!-- Editor -->
    <div class="editor-container">
        <textarea 
            id="prompt" 
            placeholder="Dictate with Wispr Flow or type..." 
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
            <span>Stop (Ctrl+C)</span>
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

        let lastCleared = '';
        let availableTargets = [];
        let selectedTargetId = localStorage.getItem('bridge_target_id') || 'auto';
        let promptHistory = JSON.parse(localStorage.getItem('bridge_prompt_history') || '[]');
        let lastSignature = '';

        // Dynamic Viewport & Keyboard Resizing
        function updateViewportHeight() {
            const h = window.visualViewport ? window.visualViewport.height : window.innerHeight;
            document.documentElement.style.setProperty('--app-height', `${h}px`);
            
            const isKeyboard = (window.innerHeight - h > 120) || (window.screen && window.screen.height - h > 200);
            if (isKeyboard || document.activeElement === promptEl) {
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

        promptEl.addEventListener('focus', () => {
            document.body.classList.add('keyboard-active');
            setTimeout(updateViewportHeight, 60);
        });

        promptEl.addEventListener('blur', () => {
            setTimeout(() => {
                if (document.activeElement !== promptEl) {
                    document.body.classList.remove('keyboard-active');
                    updateViewportHeight();
                }
            }, 180);
        });

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

        promptEl.addEventListener('input', updateMetrics);

        clearBtn.addEventListener('click', () => {
            if (!promptEl.value) return;
            lastCleared = promptEl.value;
            promptEl.value = '';
            undoBtn.style.display = 'inline';
            updateMetrics();
            promptEl.focus();
            haptic(10);
        });

        undoBtn.addEventListener('click', () => {
            if (!lastCleared) return;
            promptEl.value = lastCleared;
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
                const ttyStr = resolved.tty ? resolved.tty.replace('/dev/', '') : '';
                const compactPath = (resolved.metadata && resolved.metadata.compact_cwd) || resolved.folder || '~';
                sendTitle.textContent = willEnter ? 'Send & Execute' : 'Paste Prompt';
                if (selectedTargetId === 'auto') {
                    sendSubtitle.textContent = `to ${resolved.agent_name || resolved.name} [${ttyStr}]`;
                    miniTargetName.textContent = `Auto: ${resolved.agent_name || resolved.name}`;
                } else {
                    sendSubtitle.textContent = `to ${resolved.name} [${ttyStr}]`;
                    miniTargetName.textContent = resolved.name;
                }
                miniTargetPath.textContent = compactPath;
            } else {
                sendTitle.textContent = 'Send to Mac';
                sendSubtitle.textContent = 'No terminal target';
                miniTargetName.textContent = 'Offline';
                miniTargetPath.textContent = '--';
            }
        }

        function selectTarget(targetId) {
            selectedTargetId = targetId;
            localStorage.setItem('bridge_target_id', selectedTargetId);
            haptic(15);
            renderBentoGrid();
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
                const res = await fetch('/targets', { cache: 'no-store' });
                if (!res.ok) throw new Error();
                const data = await res.json();
                availableTargets = data.targets || [];

                const newSignature = JSON.stringify(availableTargets.map(t => [
                    t.id, t.name, t.status, t.is_busy, t.cwd, t.cmd, t.tty
                ]));

                if (!force && newSignature === lastSignature) {
                    updateSendButtonLabel();
                    return;
                }

                lastSignature = newSignature;
                renderBentoGrid();
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

                const res = await fetch('/prompt', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        target: selectedTargetId,
                        prompt: text,
                        action: resolvedAction
                    })
                });

                const data = await res.json();
                if (!res.ok || !data.success) {
                    throw new Error(data.error || 'Delivery failed');
                }

                haptic([30, 40, 30]);
                sendBtn.classList.add('success');
                sendTitle.textContent = 'Sent ✓';
                sendSubtitle.textContent = data.message || 'Delivered directly to session';

                if (customText === null) {
                    savePromptToHistory(text);
                    promptEl.value = '';
                    undoBtn.style.display = 'none';
                    updateMetrics();
                }

                setTimeout(() => {
                    sendBtn.classList.remove('success');
                    sendBtn.disabled = false;
                    updateSendButtonLabel();
                    promptEl.focus();
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

        window.addEventListener('keydown', (e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                executePrompt(null, null);
            }
        });

        async function ping() {
            try {
                const res = await fetch('/ping', { cache: 'no-store' });
                if (res.ok) {
                    statusDot.classList.remove('offline');
                } else {
                    throw new Error();
                }
            } catch (e) {
                statusDot.classList.add('offline');
            }
        }

        // Initialize
        updateViewportHeight();
        ping();
        fetchTargets(true);
        setInterval(ping, 5000);
        setInterval(() => fetchTargets(false), 6000);
        updateMetrics();
    </script>
</body>
</html>
"""


class BridgeRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for the bridge."""

    router: PromptRouter = None
    target_manager: TargetManager = None
    config: Config = None

    def log_message(self, format, *args):
        return

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
            if token == self.config.auth_token:
                return True
        if self.headers.get("X-Auth-Token") == self.config.auth_token:
            return True
        return False

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split("?")[0]

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

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def do_POST(self):
        clean_path = self.path.split("?")[0]

        if clean_path != "/prompt":
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            return

        if not self._is_authenticated():
            self.send_response(401)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success":false,"error":"Unauthorized"}')
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))

            prompt = data.get("prompt", "")
            target_id = data.get("target", "auto")
            action = data.get("action", "execute")

            if not prompt and action not in ("interrupt", "raw_enter"):
                self.send_response(400)
                self._send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"success":false,"error":"Prompt cannot be empty"}')
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

        except Exception as e:
            logger.exception("Error handling /prompt POST")
            err_payload = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_payload)))
            self.end_headers()
            self.wfile.write(err_payload)


def create_server(config: Optional[Config] = None) -> HTTPServer:
    """Creates and configures the Prompt Bridge HTTPServer instance."""
    if config is None:
        config = Config()

    discovery = SessionDiscovery()
    target_manager = TargetManager(discovery=discovery, config=config)
    adapter_factory = AdapterFactory()
    router = PromptRouter(target_manager=target_manager, adapter_factory=adapter_factory)

    BridgeRequestHandler.router = router
    BridgeRequestHandler.target_manager = target_manager
    BridgeRequestHandler.config = config

    server = HTTPServer(("0.0.0.0", config.port), BridgeRequestHandler)
    return server


def run(port: Optional[int] = None):
    """Starts the Prompt Bridge HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    config = Config()
    if port:
        config.port = port

    lan_ip = get_lan_ip()
    server = create_server(config)

    print(f"\n⚡ Prompt Bridge running with direct Terminal Agent routing:")
    print(f"  • Local:   http://localhost:{config.port}")
    print(f"  • Phone:   http://{lan_ip}:{config.port}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPrompt Bridge stopped.")
