"""Tests for PTYAdapter and PTY proxy integration."""

import os
import pty
import fcntl
import signal
import socket
import termios
import time
import unittest

from bridge.models import Target, DeliveryResult
from bridge.adapters.pty_adapter import PTYAdapter, _find_socket


def _make_target(tty="", pid=None, metadata=None):
    return Target(
        id="test-target",
        name="Test Target",
        display_name="Test Target [ttys099]",
        agent="shell",
        agent_name="Test Shell",
        tty=tty,
        pid=pid,
        metadata=metadata or {}
    )


class TestPTYAdapter(unittest.TestCase):
    """Tests PTYAdapter send/interrupt against a real PTY pair + Unix socket."""

    def setUp(self):
        self.adapter = PTYAdapter()
        # Create PTY pair
        self.master_fd, self.slave_fd = pty.openpty()
        self.slave_name = os.ttyname(self.slave_fd)
        self.tty_short = self.slave_name.replace("/dev/", "")

        # Fork a cat process on slave
        self.child_pid = os.fork()
        if self.child_pid == 0:
            os.close(self.master_fd)
            os.setsid()
            fcntl.ioctl(self.slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)
            if self.slave_fd > 2:
                os.close(self.slave_fd)
            os.execvp("cat", ["cat"])
            os._exit(127)

        os.close(self.slave_fd)
        time.sleep(0.1)

        # Set up Unix socket (mimics pty_proxy)
        self.sock_path = f"/tmp/bridge_pty_{self.tty_short}.sock"
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.sock_path)
        self.srv.listen(5)
        self.srv.setblocking(False)

        # Server thread: accept and forward to master
        import threading
        self._running = True

        def relay():
            while self._running:
                try:
                    r, _, _ = __import__("select").select([self.srv], [], [], 0.1)
                    if r:
                        conn, _ = self.srv.accept()
                        data = conn.recv(65536)
                        if data:
                            os.write(self.master_fd, data)
                        conn.close()
                except Exception:
                    break

        self._thread = threading.Thread(target=relay, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._running = False
        self._thread.join(timeout=1)
        self.srv.close()
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        try:
            os.kill(self.child_pid, signal.SIGTERM)
            os.waitpid(self.child_pid, 0)
        except (OSError, ChildProcessError):
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass

    def _read_master(self, timeout=1.5):
        import select
        deadline = time.time() + timeout
        buf = ""
        while time.time() < deadline:
            rem = max(0.05, deadline - time.time())
            r, _, _ = select.select([self.master_fd], [], [], rem)
            if r:
                try:
                    chunk = os.read(self.master_fd, 8192).decode(errors="replace")
                    buf += chunk
                    if buf:
                        return buf
                except OSError:
                    break
        return buf

    def test_can_handle_with_socket(self):
        target = _make_target(tty=self.slave_name)
        self.assertTrue(self.adapter.can_handle(target))

    def test_can_handle_without_socket(self):
        target = _make_target(tty="/dev/ttys999")
        self.assertFalse(self.adapter.can_handle(target))

    def test_can_handle_via_metadata(self):
        target = _make_target(metadata={"pty_sock": self.sock_path})
        self.assertTrue(self.adapter.can_handle(target))

    def test_send_execute(self):
        target = _make_target(tty=self.slave_name)
        result = self.adapter.send(target, "hello world", action="execute")
        self.assertTrue(result.success)
        self.assertEqual(result.adapter_used, "PTYAdapter")
        time.sleep(0.3)
        output = self._read_master()
        self.assertIn("hello world", output)

    def test_send_paste_no_newline(self):
        target = _make_target(tty=self.slave_name)
        result = self.adapter.send(target, "no enter", action="paste")
        self.assertTrue(result.success)
        # Flush the canonical line buffer with Enter so cat outputs the echoed line
        self.adapter.send(target, "", action="raw_enter")
        time.sleep(0.3)
        output = self._read_master()
        self.assertIn("no enter", output)

    def test_send_raw_enter(self):
        target = _make_target(tty=self.slave_name)
        result = self.adapter.send(target, "", action="raw_enter")
        self.assertTrue(result.success)

    def test_send_empty_text_error(self):
        target = _make_target(tty=self.slave_name)
        result = self.adapter.send(target, "", action="execute")
        self.assertFalse(result.success)
        self.assertIn("empty", result.error.lower())

    def test_send_no_socket_error(self):
        target = _make_target(tty="/dev/ttys999")
        result = self.adapter.send(target, "test", action="execute")
        self.assertFalse(result.success)
        self.assertIn("No PTY proxy socket", result.error)

    def test_interrupt(self):
        target = _make_target(tty=self.slave_name, pid=self.child_pid)
        result = self.adapter.send(target, "\x03", action="interrupt")
        self.assertTrue(result.success)
        self.assertIn("Interrupt", result.message)


class TestFindSocket(unittest.TestCase):
    def test_find_by_metadata(self):
        path = "/tmp/bridge_pty_fake.sock"
        # Create a temp file to simulate socket
        with open(path, "w") as f:
            f.write("")
        try:
            target = _make_target(metadata={"pty_sock": path})
            self.assertEqual(_find_socket(target), path)
        finally:
            os.unlink(path)

    def test_find_returns_none_when_missing(self):
        target = _make_target(tty="/dev/ttys999")
        self.assertIsNone(_find_socket(target))


if __name__ == "__main__":
    unittest.main()
