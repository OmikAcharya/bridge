"""
macOS Session Discovery module for Prompt Bridge.
Inspects running terminal sessions, processes, working directories, and active coding agents.
"""

import os
import re
import time
import subprocess
from typing import List, Dict, Any, Optional, Tuple

from bridge.models import Target, SessionInfo


AGENT_PATTERNS: List[Tuple[str, str, str]] = [
    (r"\bclaude(\.js|\.mjs|\.ts)?\b|@anthropic-ai/claude-code", "Claude Code", "claude"),
    (r"\bcodex\b", "Codex", "codex"),
    (r"\bopencode\b", "OpenCode", "opencode"),
    (r"\baider\b", "Aider", "aider"),
    (r"\bagy\b|\bantigravity\b", "Antigravity", "agy"),
    (r"\bipython3?\b", "IPython", "python"),
    (r"\bpython3?(\.app)?\b", "Python", "python"),
    (r"\bnode\b", "Node", "node"),
    (r"-?zsh\b", "Zsh", "shell"),
    (r"-?bash\b", "Bash", "shell"),
    (r"-?fish\b", "Fish", "shell"),
    (r"-?sh\b", "Shell", "shell"),
]


def classify_command(cmd_line: str) -> Tuple[str, str]:
    """Classifies a command line string into (agent_name, agent_type)."""
    for pattern, name, agent_type in AGENT_PATTERNS:
        if re.search(pattern, cmd_line, re.IGNORECASE):
            return name, agent_type
    return "Terminal Session", "terminal"


def pretty_path(path: str) -> str:
    """Replaces user home directory with ~ for compact display."""
    if not path:
        return ""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


class SessionDiscovery:
    """Discovers active macOS terminal sessions and running coding agents."""

    def __init__(self, cache_ttl: float = 1.5):
        self.cache_ttl = cache_ttl
        self._last_discovery_time: float = 0.0
        self._cached_targets: List[Target] = []
        self._cached_sessions: Dict[str, SessionInfo] = {}

    def get_active_targets(self, force_refresh: bool = False) -> List[Target]:
        """Returns a list of active Target instances."""
        now = time.time()
        if not force_refresh and (now - self._last_discovery_time < self.cache_ttl):
            return list(self._cached_targets)

        targets, sessions = self._discover()
        self._cached_targets = targets
        self._cached_sessions = sessions
        self._last_discovery_time = now
        return list(targets)

    def get_session_for_tty(self, tty: str) -> Optional[SessionInfo]:
        """Returns runtime session info for a given TTY path."""
        self.get_active_targets()
        return self._cached_sessions.get(tty)

    def _discover(self) -> Tuple[List[Target], Dict[str, SessionInfo]]:
        """Performs full discovery across Terminal.app, iTerm, and OS process tree."""
        terminal_tabs = self._discover_apple_terminal()
        iterm_sessions = self._discover_iterm()
        procs_by_tty = self._discover_processes_by_tty()

        all_ttys = set(terminal_tabs.keys()) | set(iterm_sessions.keys()) | set(procs_by_tty.keys())
        user_ttys = [t for t in all_ttys if t.startswith("/dev/tty") or t.startswith("ttys")]
        normalized_ttys = set()
        for t in user_ttys:
            if not t.startswith("/dev/"):
                normalized_ttys.add(f"/dev/{t}")
            else:
                normalized_ttys.add(t)

        targets: List[Target] = []
        sessions_map: Dict[str, SessionInfo] = {}
        seen_ids: Dict[str, int] = {}

        for tty in sorted(normalized_ttys):
            tab_info = terminal_tabs.get(tty) or iterm_sessions.get(tty) or {}
            procs = procs_by_tty.get(tty, [])
            app_name = tab_info.get("app", "Terminal" if tty in terminal_tabs else "iTerm" if tty in iterm_sessions else "Terminal")

            # Determine foreground / most specific agent process
            best_proc = None
            agent_name = "Terminal"
            agent_type = "terminal"
            cwd = ""

            # Check processes from child to parent (deepest first)
            for p in reversed(procs):
                cmd = p["cmd"]
                if "main.py" in cmd or "hi.py" in cmd or "test_discovery" in cmd or "test_classifier" in cmd:
                    continue
                name, atype = classify_command(cmd)
                if atype not in ("shell", "terminal"):
                    best_proc = p
                    agent_name = name
                    agent_type = atype
                    cwd = p.get("cwd", "")
                    break

            if not best_proc and procs:
                # Find any process with cwd
                for p in reversed(procs):
                    if p.get("cwd"):
                        cwd = p.get("cwd")
                        break
                # Fall back to top non-bridge process
                for p in reversed(procs):
                    if "main.py" not in p["cmd"] and "hi.py" not in p["cmd"] and "test_" not in p["cmd"]:
                        best_proc = p
                        name, atype = classify_command(p["cmd"])
                        agent_name = name
                        agent_type = atype
                        break

            folder_name = os.path.basename(cwd) if cwd else ""
            if folder_name == os.environ.get("USER", ""):
                folder_name = "~"

            tty_short = tty.replace("/dev/", "")
            compact_cwd = pretty_path(cwd)

            # Build readable display names
            if compact_cwd:
                name_label = f"{agent_name} — {folder_name or compact_cwd}"
                full_display = f"{agent_name} — {compact_cwd} [{tty_short}]"
            else:
                name_label = f"{agent_name} ({tty_short})"
                full_display = f"{agent_name} [{tty_short}]"

            # Build stable target ID
            slug_agent = agent_type.lower()
            slug_folder = re.sub(r'[^a-zA-Z0-9_-]', '', folder_name.lower()) if folder_name else ""
            base_id = f"{slug_agent}-{slug_folder}" if slug_folder and slug_folder != "~" else f"{slug_agent}-{tty_short}"
            
            if base_id in seen_ids:
                seen_ids[base_id] += 1
                target_id = f"{base_id}-{seen_ids[base_id]}"
            else:
                seen_ids[base_id] = 1
                target_id = base_id

            is_busy = tab_info.get("busy", False)
            status = "busy" if is_busy else "ready"
            win_title = tab_info.get("win_name", "")
            raw_cmd = best_proc["cmd"] if best_proc else ""
            # Clean cmd for UI
            short_cmd = raw_cmd.split()[0] if raw_cmd else ""
            if "/" in short_cmd:
                short_cmd = os.path.basename(short_cmd)

            target = Target(
                id=target_id,
                name=name_label,
                display_name=full_display,
                agent=agent_type,
                agent_name=agent_name,
                cwd=cwd,
                folder=folder_name,
                tty=tty,
                application=app_name,
                status=status,
                is_busy=is_busy,
                pid=best_proc["pid"] if best_proc else None,
                cmd=raw_cmd,
                win_idx=tab_info.get("win_idx"),
                tab_idx=tab_info.get("tab_idx"),
                adapter="AppleTerminalAdapter" if app_name == "Terminal" else "ITermAdapter" if app_name == "iTerm" else "auto",
                metadata={
                    "tty_short": tty_short,
                    "compact_cwd": compact_cwd,
                    "win_name": win_title,
                    "short_cmd": short_cmd,
                    "procs": [p["cmd"] for p in procs]
                }
            )
            targets.append(target)

            session = SessionInfo(
                tty=tty,
                application=app_name,
                win_idx=tab_info.get("win_idx"),
                tab_idx=tab_info.get("tab_idx"),
                win_name=win_title,
                selected=tab_info.get("selected", False),
                busy=is_busy,
                procs=[p["cmd"] for p in procs],
                pids=[p["pid"] for p in procs],
                cwd=cwd,
                foreground_pid=best_proc["pid"] if best_proc else None,
                foreground_cmd=raw_cmd
            )
            sessions_map[tty] = session

        return targets, sessions_map

    def _discover_apple_terminal(self) -> Dict[str, Dict[str, Any]]:
        """Queries Terminal.app tabs via AppleScript."""
        script = '''
        tell application "System Events"
            set termRunning to (count of (every process whose bundle identifier is "com.apple.Terminal")) > 0
        end tell
        if not termRunning then
            return ""
        end if

        tell application "Terminal"
            set outText to ""
            set wIdx to 1
            repeat with w in every window
                set tIdx to 1
                repeat with t in every tab of w
                    set ttyName to tty of t
                    set winName to name of w
                    set customTitle to custom title of t
                    set isSelected to selected of t
                    set isBusy to busy of t
                    set procList to processes of t
                    set procStr to ""
                    repeat with p in procList
                        set procStr to procStr & p & ","
                    end repeat
                    set outText to outText & wIdx & "<SEP>" & tIdx & "<SEP>" & ttyName & "<SEP>" & isSelected & "<SEP>" & isBusy & "<SEP>" & procStr & "<SEP>" & winName & "<END_ROW>"
                    set tIdx to tIdx + 1
                end repeat
                set wIdx to wIdx + 1
            end repeat
            return outText
        end tell
        '''
        tabs = {}
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.5)
            if res.returncode == 0 and res.stdout.strip():
                for row in res.stdout.strip().split("<END_ROW>"):
                    if not row.strip():
                        continue
                    parts = row.strip().split("<SEP>")
                    if len(parts) >= 7:
                        w_idx, t_idx, tty, sel, busy, procs, win_name = parts[:7]
                        tabs[tty] = {
                            "app": "Terminal",
                            "win_idx": int(w_idx) if w_idx.isdigit() else 1,
                            "tab_idx": int(t_idx) if t_idx.isdigit() else 1,
                            "tty": tty,
                            "selected": sel.lower() == "true",
                            "busy": busy.lower() == "true",
                            "procs": [p.strip() for p in procs.split(",") if p.strip()],
                            "win_name": win_name
                        }
        except Exception:
            pass
        return tabs

    def _discover_iterm(self) -> Dict[str, Dict[str, Any]]:
        """Queries iTerm2 sessions if running."""
        script = '''
        tell application "System Events"
            set itermRunning to (count of (every process whose bundle identifier is "com.googlecode.iterm2")) > 0
        end tell
        if not itermRunning then
            return ""
        end if

        tell application "iTerm"
            set outText to ""
            set wIdx to 1
            repeat with w in every window
                set tIdx to 1
                repeat with t in every tab of w
                    set sIdx to 1
                    repeat with s in every session of t
                        set ttyName to tty of s
                        set sessName to name of s
                        set isAtPrompt to is at shell prompt of s
                        set outText to outText & wIdx & "<SEP>" & tIdx & "<SEP>" & sIdx & "<SEP>" & ttyName & "<SEP>" & (not isAtPrompt) & "<SEP>" & sessName & "<END_ROW>"
                        set sIdx to sIdx + 1
                    end repeat
                    set tIdx to tIdx + 1
                end repeat
                set wIdx to wIdx + 1
            end repeat
            return outText
        end tell
        '''
        sessions = {}
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.5)
            if res.returncode == 0 and res.stdout.strip():
                for row in res.stdout.strip().split("<END_ROW>"):
                    if not row.strip():
                        continue
                    parts = row.strip().split("<SEP>")
                    if len(parts) >= 6:
                        w_idx, t_idx, s_idx, tty, busy, sess_name = parts[:6]
                        sessions[tty] = {
                            "app": "iTerm",
                            "win_idx": int(w_idx) if w_idx.isdigit() else 1,
                            "tab_idx": int(t_idx) if t_idx.isdigit() else 1,
                            "sess_idx": int(s_idx) if s_idx.isdigit() else 1,
                            "tty": tty,
                            "busy": busy.lower() == "true",
                            "win_name": sess_name
                        }
        except Exception:
            pass
        return sessions

    def _discover_processes_by_tty(self) -> Dict[str, List[Dict[str, Any]]]:
        """Discovers processes running on all TTYs and their working directories."""
        try:
            res = subprocess.run(
                ["ps", "-eo", "pid,ppid,tty,args"],
                capture_output=True,
                text=True,
                check=True,
                timeout=2.5
            )
            lines = res.stdout.strip().splitlines()
        except Exception:
            return {}

        tty_procs: Dict[str, List[Dict[str, Any]]] = {}
        pids = []
        for line in lines[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) >= 4:
                try:
                    pid, ppid, tty, cmd = int(parts[0]), int(parts[1]), parts[2], parts[3]
                except ValueError:
                    continue
                if tty.startswith("??"):
                    continue
                tty_path = f"/dev/{tty}" if not tty.startswith("/dev/") else tty
                if tty_path not in tty_procs:
                    tty_procs[tty_path] = []
                tty_procs[tty_path].append({
                    "pid": pid,
                    "ppid": ppid,
                    "cmd": cmd
                })
                pids.append(pid)

        if pids:
            try:
                cwds = {}
                for i in range(0, len(pids), 50):
                    batch = pids[i:i+50]
                    pid_arg = ",".join(str(p) for p in batch)
                    lsof_res = subprocess.run(
                        ["lsof", "-a", "-d", "cwd", "-p", pid_arg, "-Fn"],
                        capture_output=True,
                        text=True,
                        timeout=2.0
                    )
                    cur_pid = None
                    for l in lsof_res.stdout.splitlines():
                        if l.startswith('p'):
                            try:
                                cur_pid = int(l[1:])
                            except ValueError:
                                cur_pid = None
                        elif l.startswith('n') and cur_pid is not None:
                            cwds[cur_pid] = l[1:]

                for tty_path, procs in tty_procs.items():
                    for p in procs:
                        p["cwd"] = cwds.get(p["pid"], "")
            except Exception:
                pass

        return tty_procs
