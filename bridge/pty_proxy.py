#!/usr/bin/env python3
"""
PTY Proxy — bridge-managed PTY wrapper for focus-independent stdin injection.

Creates a PTY pair, runs a child command on the slave side, and exposes the
master fd via a Unix domain socket. Any process that connects to the socket
and writes bytes injects those bytes as stdin to the child.

Normal terminal I/O (keyboard input from Terminal.app, output displayed in
Terminal.app) is relayed transparently. The user sees no difference from
running the command directly.

Usage:
    python3 -m bridge.pty_proxy <command> [args...]

    # Then inject from another process:
    echo "injected prompt" | socat - UNIX-CONNECT:/tmp/bridge_pty_<tty>.sock

Environment:
    BRIDGE_PTY_SOCK_DIR  — socket directory (default: /tmp)
"""

import fcntl
import os
import pty
import select
import signal
import socket
import sys
import termios
import tty

SOCK_DIR = os.environ.get("BRIDGE_PTY_SOCK_DIR", "/tmp")
SOCK_PREFIX = "bridge_pty_"
BUF_SIZE = 65536


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <command> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1:]

    # Create PTY pair
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    tty_short = slave_name.replace("/dev/", "")

    # Propagate parent terminal size to slave
    if os.isatty(0):
        winsize = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\x00" * 8)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    pid = os.fork()
    if pid == 0:
        # Child: attach to slave PTY
        os.close(master_fd)
        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)
        if slave_fd > 2:
            os.close(slave_fd)
        os.execvp(cmd[0], cmd)
        sys.exit(127)

    # Parent: close slave, keep master
    os.close(slave_fd)

    # Socket path: named after the slave TTY for discovery
    sock_path = os.path.join(SOCK_DIR, f"{SOCK_PREFIX}{tty_short}.sock")
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(5)
    srv.setblocking(False)

    print(f"[bridge-pty] child={pid} tty={slave_name} sock={sock_path}", file=sys.stderr)

    # Set our stdin to raw mode if it's a TTY
    stdin_is_tty = os.isatty(0)
    old_attrs = None
    if stdin_is_tty:
        old_attrs = termios.tcgetattr(0)
        tty.setraw(0)
        old_flags = fcntl.fcntl(0, fcntl.F_GETFL)
        fcntl.fcntl(0, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

    injection_clients: list[socket.socket] = []
    running = True
    child_exit_code = 0

    def on_sigchld(signum, frame):
        nonlocal running, child_exit_code
        try:
            _, status = os.waitpid(pid, os.WNOHANG)
            if os.WIFEXITED(status):
                child_exit_code = os.WEXITSTATUS(status)
            elif os.WIFSIGNALED(status):
                child_exit_code = 128 + os.WTERMSIG(status)
        except ChildProcessError:
            pass
        running = False

    def on_sigwinch(signum, frame):
        """Propagate terminal resize to child PTY."""
        if stdin_is_tty:
            try:
                winsize = fcntl.ioctl(0, termios.TIOCGWINSZ, b"\x00" * 8)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                os.kill(pid, signal.SIGWINCH)
            except OSError:
                pass

    signal.signal(signal.SIGCHLD, on_sigchld)
    signal.signal(signal.SIGWINCH, on_sigwinch)

    try:
        while running:
            read_fds = [master_fd, srv.fileno()]
            if stdin_is_tty:
                read_fds.append(0)
            for c in injection_clients:
                read_fds.append(c.fileno())

            try:
                readable, _, _ = select.select(read_fds, [], [], 0.1)
            except (OSError, ValueError, InterruptedError):
                if not running:
                    break
                continue

            for fd in readable:
                if fd == master_fd:
                    try:
                        data = os.read(master_fd, BUF_SIZE)
                        if data:
                            os.write(1, data)
                        else:
                            running = False
                    except OSError:
                        running = False

                elif fd == 0:
                    try:
                        data = os.read(0, BUF_SIZE)
                        if data:
                            os.write(master_fd, data)
                    except OSError:
                        pass

                elif fd == srv.fileno():
                    try:
                        conn, _ = srv.accept()
                        conn.setblocking(False)
                        injection_clients.append(conn)
                    except OSError:
                        pass

                else:
                    client = None
                    for c in injection_clients:
                        if c.fileno() == fd:
                            client = c
                            break
                    if client:
                        try:
                            data = client.recv(BUF_SIZE)
                            if data:
                                os.write(master_fd, data)
                            else:
                                injection_clients.remove(client)
                                client.close()
                        except OSError:
                            injection_clients.remove(client)
                            try:
                                client.close()
                            except OSError:
                                pass
    finally:
        # Restore terminal
        if old_attrs:
            termios.tcsetattr(0, termios.TCSAFLUSH, old_attrs)

        # Cleanup socket
        srv.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        # Cleanup child
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGTERM)
            os.waitpid(pid, 0)
        except (OSError, ChildProcessError):
            pass

    sys.exit(child_exit_code)


if __name__ == "__main__":
    main()
