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
    <meta name="theme-color" content="#000000">
    <title>Terminal Chat</title>
    <style>
        :root {
            --app-height: 100dvh;
            --bg: #000;
            --surface: #1c1c1e;
            --text: #fff;
            --text-muted: #8e8e93;
            --blue: #0a84ff;
            --blue-pressed: #0060c0;
            --gray-bubble: #262628;
            --border: #38383a;
            --green: #30d158;
            --font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
            --font-mono: ui-monospace, "SF Mono", Menlo, monospace;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
        
        html, body {
            height: 100%; height: var(--app-height, 100dvh); max-height: var(--app-height, 100dvh);
            overflow: hidden; font-family: var(--font-sans); background-color: var(--bg); color: var(--text);
        }

        /* Views */
        .view {
            position: absolute; top: 0; left: 0; width: 100%; height: 100%;
            display: flex; flex-direction: column;
            background: var(--bg);
            transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
        }
        #chatsView { z-index: 10; }
        #chatView { z-index: 20; transform: translateX(100%); }
        #chatView.active { transform: translateX(0); }

        /* Inbox View */
        .inbox-header { padding: calc(env(safe-area-inset-top, 44px) + 20px) 20px 10px; display: flex; align-items: baseline; justify-content: space-between; }
        .inbox-title { font-size: 34px; font-weight: 700; letter-spacing: 0.3px; }
        .conn-badge { font-size: 13px; color: var(--blue); background: rgba(10, 132, 255, 0.15); padding: 4px 10px; border-radius: 12px; font-weight: 600; }
        
        .chats-list { flex-grow: 1; overflow-y: auto; padding: 0 20px; }
        .chat-row { display: flex; align-items: center; padding: 12px 0; border-bottom: 0.5px solid var(--border); cursor: pointer; }
        .chat-row:active { opacity: 0.7; }
        .chat-row.active-row .avatar { border: 2px solid var(--blue); }
        .avatar {
            width: 45px; height: 45px; border-radius: 50%; background: #333;
            display: flex; align-items: center; justify-content: center; font-size: 20px; margin-right: 12px;
            position: relative; flex-shrink: 0;
        }
        .status-dot {
            position: absolute; bottom: 0; right: 0; width: 12px; height: 12px;
            border-radius: 50%; background: var(--green); border: 2px solid var(--bg);
        }
        .status-dot.offline { background: #ff453a; }
        
        .chat-info { flex-grow: 1; overflow: hidden; }
        .chat-name { font-size: 17px; font-weight: 600; margin-bottom: 2px; }
        .chat-preview { font-size: 15px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .chevron { color: var(--border); font-size: 22px; padding-left: 10px; }

        /* Chat View (Cockpit) */
        .chat-nav {
            padding: env(safe-area-inset-top, 44px) 10px 10px;
            background: rgba(28, 28, 30, 0.85); backdrop-filter: blur(20px);
            border-bottom: 0.5px solid var(--border); display: flex; align-items: center; justify-content: space-between;
        }
        .back-btn {
            background: none; border: none; color: var(--blue); font-size: 17px; font-weight: 400;
            display: flex; align-items: center; gap: 4px; cursor: pointer;
        }
        .back-btn svg { margin-bottom: 1px; }
        
        .contact-info { display: flex; flex-direction: column; align-items: center; justify-content: center; flex-grow: 1; margin-right: 30px; }
        .contact-avatar { width: 28px; height: 28px; border-radius: 50%; background: #444; font-size: 14px; display: flex; align-items: center; justify-content: center; margin-bottom: 3px; }
        .contact-name { font-size: 12px; font-weight: 600; }

        .chat-scroll {
            flex-grow: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 16px;
        }
        
        /* Terminal Bubble (Gray Left) */
        .bubble-row { display: flex; width: 100%; margin-bottom: 10px; }
        .bubble-row.term-row { justify-content: flex-start; }
        .bubble-row.user-row { justify-content: flex-end; }
        
        .bubble { max-width: 85%; padding: 10px 14px; position: relative; font-size: 15px; line-height: 1.4; word-wrap: break-word; }
        
        .bubble.terminal {
            background: var(--gray-bubble); align-self: flex-start; border-radius: 18px 18px 18px 4px;
            font-family: var(--font-mono); font-size: 13px; white-space: pre-wrap; overflow-x: auto;
        }
        
        .bubble.user {
            background: var(--blue); align-self: flex-end; border-radius: 18px 18px 4px 18px;
        }

        /* Action Chips (replacing mini bar) */
        .action-chips {
            display: flex; gap: 8px; overflow-x: auto; padding: 8px 16px; padding-bottom: 4px;
            scroll-snap-type: x mandatory; -webkit-overflow-scrolling: touch;
        }
        .action-chips::-webkit-scrollbar { display: none; }
        .action-chip {
            background: var(--surface); color: var(--text); border: none; padding: 6px 14px;
            border-radius: 16px; font-size: 14px; font-weight: 500; white-space: nowrap; cursor: pointer;
        }
        .action-chip:active { background: #333; }
        .action-chip.danger { color: #ff453a; }
        
        /* Input Area */
        .input-bar {
            padding: 8px 16px calc(env(safe-area-inset-bottom, 16px) + 8px);
            background: rgba(28, 28, 30, 0.85); backdrop-filter: blur(20px);
            display: flex; align-items: flex-end; gap: 10px; border-top: 0.5px solid var(--border);
        }
        .input-pill {
            flex-grow: 1; background: #000; border: 1px solid var(--border);
            border-radius: 20px; display: flex; align-items: flex-end; padding: 4px 6px;
        }
        .input-pill textarea {
            flex-grow: 1; background: transparent; border: none; color: var(--text);
            font-family: inherit; font-size: 16px; padding: 6px 10px; max-height: 120px;
            resize: none; outline: none; line-height: 1.3;
        }
        .send-btn {
            width: 28px; height: 28px; border-radius: 50%; background: var(--blue);
            display: flex; align-items: center; justify-content: center;
            border: none; flex-shrink: 0; cursor: pointer; color: white; transition: transform 0.1s;
        }
        .send-btn:active { background: var(--blue-pressed); transform: scale(0.95); }
        .send-btn:disabled { background: #333; color: #666; }
        
        .hidden { display: none !important; }
    </style>
</head>
<body>

    <!-- INBOX VIEW -->
    <div id="chatsView" class="view">
        <div class="inbox-header">
            <div class="inbox-title">Messages</div>
            <div id="connBadge" class="conn-badge">🔒 P2P</div>
        </div>
        <div id="bentoGrid" class="chats-list">
            <!-- Populated by renderBentoGrid() -->
            <div style="padding: 20px; text-align:center; color: #666;">Connecting...</div>
        </div>
    </div>

    <!-- CHAT VIEW -->
    <div id="chatView" class="view">
        <div class="chat-nav">
            <button class="back-btn" onclick="document.getElementById('chatView').classList.remove('active'); stopTail()">
                <svg width="12" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
                Messages
            </button>
            <div class="contact-info">
                <div class="contact-avatar">💻</div>
                <div id="cockpitTargetTitle" class="contact-name">Terminal</div>
            </div>
            <div style="width: 70px;"></div> <!-- spacer -->
        </div>

        <div class="chat-scroll" id="chatScroll">
            <!-- Terminal Output Bubble -->
            <div class="bubble-row term-row">
                <div class="bubble terminal" id="cockpitActivityContent">
                    Loading terminal...
                </div>
            </div>
        </div>

        <div class="action-chips" id="keyboardMiniBar">
            <button class="action-chip" id="btnEnterOnly">Return ⏎</button>
            <button class="action-chip danger" id="btnInterrupt">Ctrl+C</button>
            <button class="action-chip" id="btnYes">Yes</button>
            <button class="action-chip" id="btnNo">No</button>
            <button class="action-chip" id="btnContinue">Continue</button>
        </div>

        <div class="input-bar">
            <div class="input-pill">
                <textarea id="prompt" rows="1" placeholder="iMessage" oninput="this.style.height='auto';this.style.height=this.scrollHeight+'px'"></textarea>
                <button id="sendBtn" class="send-btn">
                    <svg width="12" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
                </button>
            </div>
        </div>
    </div>
    
    <!-- Dummy elements to keep original JS intact -->
    <div id="statusDot" class="hidden"></div>
    <div id="sendTitle" class="hidden"></div>
    <div id="sendSubtitle" class="hidden"></div>
    <div id="metrics" class="hidden"></div>
    <div id="clearBtn" class="hidden"></div>
    <div id="undoBtn" class="hidden"></div>
    <div id="enterToggle" class="hidden"></div>
    <div id="cockpitModal" class="hidden"></div>
    <div id="openCockpitBtn" class="hidden"></div>
    <div id="closeCockpitBtn" class="hidden"></div>
    <div id="cockpitPrompt" class="hidden"></div>
    <div id="cockpitSendBtn" class="hidden"></div>
    <div id="cockpitAgentDot" class="hidden"></div>
    <div id="headerAgentDot" class="hidden"></div>
    <div id="headerAgentName" class="hidden"></div>
    <div id="headerAgentStatus" class="hidden"></div>
    <div id="historyBtn" class="hidden"></div>
    <div id="refreshBtn" class="hidden"></div>
    <div id="historyModal" class="hidden"></div>
    <div id="historyList" class="hidden"></div>
    <div id="closeHistoryModal" class="hidden"></div>
    <div id="miniTargetName" class="hidden"></div>
    <div id="miniTargetPath" class="hidden"></div>
    <div id="pillRaw" class="hidden"></div>
    <div id="pillUltra" class="hidden"></div>
    <div id="cockpitBtnEnter" class="hidden"></div>
    <div id="cockpitBtnInterrupt" class="hidden"></div>
    <div id="cockpitBtnYes" class="hidden"></div>
    <div id="cockpitBtnNo" class="hidden"></div>
    <div id="cockpitBtnContinue" class="hidden"></div>
    <div id="refreshCockpitBtn" class="hidden"></div>

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

            // Auto-detect row
            const autoResolved = availableTargets.find(t => t.agent && t.agent !== 'shell' && t.agent !== 'legacy' && t.id !== 'focused') || availableTargets[0];
            const autoRow = document.createElement('div');
            autoRow.className = 'chat-row';
            const resolvedName = autoResolved ? (autoResolved.agent_name || autoResolved.name) : 'Searching...';
            autoRow.innerHTML = `
                <div class="avatar">✨</div>
                <div class="chat-info">
                    <div class="chat-name">Auto-detect</div>
                    <div class="chat-preview">Routing to ${resolvedName}</div>
                </div>
                <div class="chevron">›</div>
            `;
            autoRow.addEventListener('click', () => {
                selectTarget('auto');
                document.getElementById('chatView').classList.add('active');
            });
            bentoGrid.appendChild(autoRow);

            // Session rows
            availableTargets.forEach(t => {
                const row = document.createElement('div');
                row.className = 'chat-row';
                const isBusy = (t.status === 'busy' || t.is_busy);
                const dot = isBusy ? '<div class="status-dot"></div>' : '';
                const compactPath = (t.metadata && t.metadata.compact_cwd) || t.folder || '~';
                const shortName = t.agent_name || t.name;

                row.innerHTML = `
                    <div class="avatar">💻${dot}</div>
                    <div class="chat-info">
                        <div class="chat-name">${t.id === 'focused' ? 'Focused App' : shortName}</div>
                        <div class="chat-preview">${t.id === 'focused' ? (t.metadata && t.metadata.window_title || 'Active Window') : compactPath}</div>
                    </div>
                    <div class="chevron">›</div>
                `;
                row.addEventListener('click', () => {
                    selectTarget(t.id);
                    document.getElementById('chatView').classList.add('active');
                });
                bentoGrid.appendChild(row);
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

        // WebCrypto E2EE Authenticated Encryption (CTR-HMAC-SHA256)
        class E2EECryptoClient {
            constructor(rawKey) {
                this.rawKey = rawKey;
                this.kEnc = null;
                this.kMac = null;
                this.readyPromise = this.init();
            }

            async init() {
                const enc = new TextEncoder();
                const masterDigest = await crypto.subtle.digest('SHA-256', enc.encode(this.rawKey));
                const masterKey = await crypto.subtle.importKey('raw', masterDigest, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
                const kEncBytes = await crypto.subtle.sign('HMAC', masterKey, enc.encode('enc'));
                const kMacBytes = await crypto.subtle.sign('HMAC', masterKey, enc.encode('mac'));
                this.kEnc = await crypto.subtle.importKey('raw', kEncBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
                this.kMac = await crypto.subtle.importKey('raw', kMacBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
            }

            async encrypt(plaintext) {
                await this.readyPromise;
                const enc = new TextEncoder();
                const data = enc.encode(plaintext);
                const nonce = new Uint8Array(16);
                crypto.getRandomValues(nonce);

                const numBlocks = Math.ceil(data.length / 32);
                const ksChunks = [];
                for (let i = 0; i < numBlocks; i++) {
                    const ctr = new Uint8Array(20);
                    ctr.set(nonce, 0);
                    new DataView(ctr.buffer).setUint32(16, i, false);
                    const block = await crypto.subtle.sign('HMAC', this.kEnc, ctr);
                    ksChunks.push(new Uint8Array(block));
                }

                const totalKs = new Uint8Array(numBlocks * 32);
                let off = 0;
                for (const c of ksChunks) { totalKs.set(c, off); off += c.length; }

                const ct = new Uint8Array(data.length);
                for (let i = 0; i < data.length; i++) {
                    ct[i] = data[i] ^ totalKs[i];
                }

                const macInput = new Uint8Array(nonce.length + ct.length);
                macInput.set(nonce, 0);
                macInput.set(ct, nonce.length);
                const tagBytes = await crypto.subtle.sign('HMAC', this.kMac, macInput);

                const tagHex = Array.from(new Uint8Array(tagBytes)).map(b => b.toString(16).padStart(2, '0')).join('');
                const nonceHex = Array.from(nonce).map(b => b.toString(16).padStart(2, '0')).join('');
                const ctHex = Array.from(ct).map(b => b.toString(16).padStart(2, '0')).join('');

                return { nonce: nonceHex, ct: ctHex, tag: tagHex };
            }

            async decrypt(envelope) {
                await this.readyPromise;
                const dec = new TextDecoder();
                const nonce = new Uint8Array(envelope.nonce.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));
                const ct = new Uint8Array(envelope.ct.match(/.{1,2}/g).map(byte => parseInt(byte, 16)));

                const macInput = new Uint8Array(nonce.length + ct.length);
                macInput.set(nonce, 0);
                macInput.set(ct, nonce.length);
                const tagBytes = await crypto.subtle.sign('HMAC', this.kMac, macInput);
                const expectedTag = Array.from(new Uint8Array(tagBytes)).map(b => b.toString(16).padStart(2, '0')).join('');

                if (expectedTag !== envelope.tag) {
                    throw new Error('MAC verification failed - message tampered');
                }

                const numBlocks = Math.ceil(ct.length / 32);
                const ksChunks = [];
                for (let i = 0; i < numBlocks; i++) {
                    const ctr = new Uint8Array(20);
                    ctr.set(nonce, 0);
                    new DataView(ctr.buffer).setUint32(16, i, false);
                    const block = await crypto.subtle.sign('HMAC', this.kEnc, ctr);
                    ksChunks.push(new Uint8Array(block));
                }

                const totalKs = new Uint8Array(numBlocks * 32);
                let off = 0;
                for (const c of ksChunks) { totalKs.set(c, off); off += c.length; }

                const pt = new Uint8Array(ct.length);
                for (let i = 0; i < ct.length; i++) {
                    pt[i] = ct[i] ^ totalKs[i];
                }
                return dec.decode(pt);
            }
        }

        // Native Zero-Dependency MQTT v3.1.1 WebSocket Client
        class NanoMQTTWS {
            constructor(brokers, clientId, onMessage, onConnect, onDisconnect) {
                this.brokers = Array.isArray(brokers) ? brokers : [brokers];
                this.brokerIdx = 0;
                this.clientId = clientId;
                this.onMessage = onMessage;
                this.onConnect = onConnect;
                this.onDisconnect = onDisconnect;
                this.ws = null;
                this.pingTimer = null;
                this.enc = new TextEncoder();
                this.dec = new TextDecoder();
                this.connect();
            }

            connect() {
                if (this.ws) {
                    try { this.ws.close(); } catch(e) {}
                    this.ws = null;
                }
                clearInterval(this.pingTimer);
                const url = this.brokers[this.brokerIdx % this.brokers.length];
                try {
                    this.ws = new WebSocket(url, ['mqtt']);
                    this.ws.binaryType = 'arraybuffer';
                    this.ws.onopen = () => this._sendConnect();
                    this.ws.onmessage = (e) => this._handleMessage(new Uint8Array(e.data));
                    this.ws.onclose = () => {
                        clearInterval(this.pingTimer);
                        if (this.onDisconnect) this.onDisconnect();
                        this.brokerIdx++;
                        setTimeout(() => this.connect(), 2000);
                    };
                    this.ws.onerror = () => {
                        try { this.ws.close(); } catch(e) {}
                    };
                } catch(e) {
                    this.brokerIdx++;
                    setTimeout(() => this.connect(), 2000);
                }
            }

            _encodeLength(len) {
                const bytes = [];
                let num = len;
                do {
                    let byte = num % 128;
                    num = Math.floor(num / 128);
                    if (num > 0) byte |= 128;
                    bytes.push(byte);
                } while (num > 0);
                return new Uint8Array(bytes);
            }

            _decodeLength(buf, offset) {
                let multiplier = 1, value = 0, idx = offset;
                while (idx < buf.length) {
                    const byte = buf[idx++];
                    value += (byte & 127) * multiplier;
                    multiplier *= 128;
                    if ((byte & 128) === 0) break;
                }
                return { length: value, nextOffset: idx };
            }

            _sendConnect() {
                const cid = this.enc.encode(this.clientId);
                const varHeader = new Uint8Array([0x00, 0x04, 0x4D, 0x51, 0x54, 0x54, 0x04, 0x02, 0x00, 0x3C]);
                const payload = new Uint8Array(2 + cid.length);
                payload[0] = (cid.length >> 8) & 0xff; payload[1] = cid.length & 0xff;
                payload.set(cid, 2);
                const remLen = varHeader.length + payload.length;
                const lenBytes = this._encodeLength(remLen);
                const pkt = new Uint8Array(1 + lenBytes.length + remLen);
                pkt[0] = 0x10;
                pkt.set(lenBytes, 1);
                pkt.set(varHeader, 1 + lenBytes.length);
                pkt.set(payload, 1 + lenBytes.length + varHeader.length);
                this.ws.send(pkt);
            }

            subscribe(topic) {
                if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
                const top = this.enc.encode(topic);
                const payload = new Uint8Array(2 + 2 + top.length + 1);
                payload[0] = 0x00; payload[1] = 0x01;
                payload[2] = (top.length >> 8) & 0xff; payload[3] = top.length & 0xff;
                payload.set(top, 4);
                payload[4 + top.length] = 0x00;
                const lenBytes = this._encodeLength(payload.length);
                const pkt = new Uint8Array(1 + lenBytes.length + payload.length);
                pkt[0] = 0x82;
                pkt.set(lenBytes, 1);
                pkt.set(payload, 1 + lenBytes.length);
                this.ws.send(pkt);
            }

            publish(topic, payloadStr) {
                if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
                const top = this.enc.encode(topic);
                const pay = this.enc.encode(payloadStr);
                const body = new Uint8Array(2 + top.length + pay.length);
                body[0] = (top.length >> 8) & 0xff; body[1] = top.length & 0xff;
                body.set(top, 2);
                body.set(pay, 2 + top.length);
                const lenBytes = this._encodeLength(body.length);
                const pkt = new Uint8Array(1 + lenBytes.length + body.length);
                pkt[0] = 0x30;
                pkt.set(lenBytes, 1);
                pkt.set(body, 1 + lenBytes.length);
                this.ws.send(pkt);
            }

            _handleMessage(buf) {
                const cmd = buf[0] & 0xf0;
                if (cmd === 0x20) {
                    clearInterval(this.pingTimer);
                    this.pingTimer = setInterval(() => {
                        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                            this.ws.send(new Uint8Array([0xC0, 0x00]));
                        }
                    }, 20000);
                    if (this.onConnect) this.onConnect();
                } else if (cmd === 0x30) {
                    const { length: remLen, nextOffset: headerEnd } = this._decodeLength(buf, 1);
                    const topLen = (buf[headerEnd] << 8) | buf[headerEnd + 1];
                    const topic = this.dec.decode(buf.subarray(headerEnd + 2, headerEnd + 2 + topLen));
                    const payload = this.dec.decode(buf.subarray(headerEnd + 2 + topLen, headerEnd + remLen));
                    if (this.onMessage) this.onMessage(topic, payload);
                }
            }
        }

        let p2pCrypto = null;

        function initP2PRelay(room, key) {
            updateConnectionBadge('p2p_connecting');
            try {
                p2pCrypto = new E2EECryptoClient(key);
                const brokers = [
                    'wss://broker.hivemq.com:8884/mqtt',
                    'wss://broker.emqx.io:8084/mqtt'
                ];
                const clientId = 'phone_' + Math.random().toString(16).slice(2, 10);
                mqttClient = new NanoMQTTWS(
                    brokers,
                    clientId,
                    async (topic, payload) => {
                        try {
                            const raw = JSON.parse(payload);
                            let data = raw;
                            if (raw && raw.ct && raw.nonce && raw.tag && p2pCrypto) {
                                const decryptedJson = await p2pCrypto.decrypt(raw);
                                data = JSON.parse(decryptedJson);
                            }
                            if (data.id && pendingRequests.has(data.id)) {
                                const { resolve } = pendingRequests.get(data.id);
                                pendingRequests.delete(data.id);
                                resolve(data);
                            }
                        } catch (err) {}
                    },
                    () => {
                        mqttClient.subscribe(`pb/${room}/phone`);
                        isP2PReady = true;
                        statusDot.classList.remove('offline');
                        updateConnectionBadge('p2p');
                        fetchTargets(true);
                        fetchActivityTail();
                    },
                    () => {
                        isP2PReady = false;
                        statusDot.classList.add('offline');
                        updateConnectionBadge('p2p_offline');
                    }
                );
            } catch (e) {
                console.error('P2P relay init error:', e);
            }
        }

        async function p2pRequest(action, params = {}) {
            if (!mqttClient || !isP2PReady || !p2pCrypto) {
                throw new Error('P2P not connected');
            }
            const id = reqSeq++;
            const msg = Object.assign({ id, action, key: p2pKey }, params);
            const encryptedEnvelope = await p2pCrypto.encrypt(JSON.stringify(msg));

            return new Promise((resolve, reject) => {
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

                mqttClient.publish(`pb/${p2pRoom}/mac`, JSON.stringify(encryptedEnvelope));
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
