"""Scan engine: a per-user clamd daemon plus a small clamd socket client.

clamd keeps the signature database in memory so scans start instantly after
the first load.
"""
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from linux_defender import paths

STATE_NO_ENGINE = "no_engine"        # clamd binary not found
STATE_NO_SIGNATURES = "no_signatures"
STATE_STOPPED = "stopped"
STATE_LOADING = "loading"
STATE_READY = "ready"
STATE_ERROR = "error"

SIG_FILES = ("main.cvd", "main.cld", "daily.cvd", "daily.cld", "bytecode.cvd", "bytecode.cld")


def signatures_present() -> bool:
    names = {p.name for p in paths.DB_DIR.glob("*")} if paths.DB_DIR.exists() else set()
    has_main = bool(names & {"main.cvd", "main.cld"})
    has_daily = bool(names & {"daily.cvd", "daily.cld"})
    has_custom = any(n.endswith((".hdb", ".hsb", ".ndb", ".ldb", ".cdb", ".yar")) for n in names)
    return (has_main and has_daily) or has_custom


class ScanResult:
    __slots__ = ("path", "status", "threat", "error")

    def __init__(self, path, status, threat="", error=""):
        self.path, self.status, self.threat, self.error = path, status, threat, error

    @property
    def infected(self):
        return self.status == "FOUND"

    def __repr__(self):
        return f"ScanResult({self.path!r}, {self.status}, {self.threat or self.error})"


class ClamdClient:
    """Minimal clamd protocol client (z-prefixed, NUL-terminated commands)."""

    def __init__(self, sock_path: Path, timeout: float = 600):
        self.sock_path = str(sock_path)
        self.timeout = timeout

    def _cmd(self, payload: bytes, timeout=None) -> bytes:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout or self.timeout)
        try:
            s.connect(self.sock_path)
            s.sendall(payload)
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
                if b.endswith(b"\0"):
                    break
            return b"".join(chunks).rstrip(b"\0\n")
        finally:
            s.close()

    def ping(self) -> bool:
        try:
            return self._cmd(b"zPING\0", timeout=3) == b"PONG"
        except OSError:
            return False

    def version(self) -> str:
        return self._cmd(b"zVERSION\0", timeout=5).decode(errors="replace")

    def reload(self) -> str:
        return self._cmd(b"zRELOAD\0", timeout=10).decode(errors="replace")

    def shutdown(self):
        try:
            self._cmd(b"zSHUTDOWN\0", timeout=3)
        except OSError:
            pass

    def scan_file(self, path: str) -> ScanResult:
        raw = self._cmd(b"zSCAN " + os.fsencode(path) + b"\0")
        return self._parse(path, raw)

    def scan_stream(self, name: str, chunks) -> ScanResult:
        """Scan content without writing it to disk (clamd INSTREAM)."""
        import struct
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.sock_path)
            s.sendall(b"zINSTREAM\0")
            for c in chunks:
                for i in range(0, len(c), 1 << 16):
                    part = c[i:i + (1 << 16)]
                    s.sendall(struct.pack("!L", len(part)) + part)
            s.sendall(struct.pack("!L", 0))
            out = []
            while True:
                b = s.recv(4096)
                if not b:
                    break
                out.append(b)
                if b.endswith(b"\0"):
                    break
            raw = b"".join(out).rstrip(b"\0\n")
        finally:
            s.close()
        r = self._parse("stream", raw)
        r.path = name
        if r.status == "ERROR" and b"size limit exceeded" in raw.lower():
            r.error = "too large to rescan"
        return r

    @staticmethod
    def _parse(path, raw: bytes) -> ScanResult:
        text = raw.decode("utf-8", errors="surrogateescape")
        # "<path>: OK" | "<path>: <Threat> FOUND" | "<path>: <msg> ERROR"
        _, _, tail = text.rpartition(": ")
        tail = tail.strip()
        if tail == "OK":
            return ScanResult(path, "OK")
        if tail.endswith(" FOUND"):
            return ScanResult(path, "FOUND", threat=tail[:-6])
        if tail.endswith(" ERROR"):
            return ScanResult(path, "ERROR", error=tail[:-6])
        if text.endswith("ERROR"):
            return ScanResult(path, "ERROR", error=text)
        return ScanResult(path, "ERROR", error=text or "no reply")


class Engine:
    """Owns the clamd child process and its configuration."""

    def __init__(self, settings, on_state=None):
        self.settings = settings
        self.on_state = on_state or (lambda state, info: None)
        self.proc: subprocess.Popen | None = None
        self.state = STATE_STOPPED
        self.info = ""
        self.client = ClamdClient(paths.clamd_socket())
        self._lock = threading.Lock()
        self._restart_guard = threading.Lock()
        self._restarting = False
        self._restart_requested = False
        self._intentional_stop = False

    # -- state -------------------------------------------------------------
    def _set(self, state, info=""):
        self.state, self.info = state, info
        try:
            self.on_state(state, info)
        except Exception:
            pass

    @property
    def ready(self):
        return self.state == STATE_READY

    # -- configuration -----------------------------------------------------
    def write_config(self):
        av = self.settings.get("antivirus")
        sock = paths.clamd_socket()
        mb = lambda n: f"{int(n)}M"
        lines = [
            "# Generated by Linux Defender — edits are overwritten",
            f"LocalSocket {sock}",
            "LocalSocketMode 600",
            "FixStaleSocket yes",
            f"DatabaseDirectory {paths.DB_DIR}",
            *paths.certs_config_lines(),
            f"LogFile {paths.LOG_DIR / 'clamd.log'}",
            "LogFileMaxSize 5M",
            "LogTime yes",
            "LogRotate yes",
            f"PidFile {paths.runtime_dir() / 'clamd.pid'}",
            f"TemporaryDirectory {os.environ.get('TMPDIR', '/tmp')}",
            "Foreground yes",
            "MaxThreads 6",
            "MaxQueue 200",
            "ReadTimeout 300",
            "CommandReadTimeout 30",
            "SelfCheck 0",
            "ConcurrentDatabaseReload no",
            f"ScanArchive {'yes' if av['scan_archives'] else 'no'}",
            f"MaxScanSize {mb(max(av['archive_max_mb'] * 4, av['max_file_mb']))}",
            f"MaxFileSize {mb(av['max_file_mb'])}",
            f"StreamMaxLength {mb(av['max_file_mb'])}",
            f"DetectPUA {'yes' if av['detect_pua'] else 'no'}",
            f"HeuristicAlerts {'yes' if av['heuristic_alerts'] else 'no'}",
            "ScanPE yes",
            "ScanELF yes",
            "ScanOLE2 yes",
            "ScanPDF yes",
            "ScanHTML yes",
            "ScanMail yes",
            "AlertBrokenExecutables no",
            "Bytecode yes",
        ]
        paths.CLAMD_CONF.parent.mkdir(parents=True, exist_ok=True)
        paths.CLAMD_CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        threading.Thread(target=self._start, daemon=True, name="clamd-start").start()

    def _start(self):
        with self._lock:
            clamd = paths.find_tool("clamd")
            if not clamd:
                self._set(STATE_NO_ENGINE, "ClamAV daemon (clamd) not found")
                return
            if not signatures_present():
                self._set(STATE_NO_SIGNATURES, "Threat signatures have not been downloaded yet")
                return
            if self.client.ping() and self.proc is not None and self.proc.poll() is None:
                self._set(STATE_READY, self._version())     # our own engine is already running
                return
            if self.client.ping():
                # a scan engine left over from a crashed session: it may use old settings and log
                # elsewhere, so replace it with a fresh one
                self.client.shutdown()
                for _ in range(40):
                    if not self.client.ping():
                        break
                    time.sleep(0.25)
            self.write_config()
            self._set(STATE_LOADING, "Loading threat signatures…")
            log = open(paths.LOG_DIR / "clamd.stdout.log", "ab")
            self._intentional_stop = False
            proc = subprocess.Popen(
                [clamd, "--config-file", str(paths.CLAMD_CONF), "--foreground"],
                stdout=log, stderr=subprocess.STDOUT, env=paths.tool_env(),
                start_new_session=True,
            )
            self.proc = proc
            deadline = time.time() + 300
            while time.time() < deadline:
                if self.proc is not proc:                 # stopped/replaced while loading
                    return
                if proc.poll() is not None:
                    self._set(STATE_ERROR, f"clamd exited with code {proc.returncode} "
                                           f"(see {paths.LOG_DIR / 'clamd.log'})")
                    return
                if self.client.ping():
                    self._set(STATE_READY, self._version())
                    threading.Thread(target=self._watch, daemon=True).start()
                    return
                time.sleep(0.5)
            self._set(STATE_ERROR, "Timed out waiting for clamd to load signatures")

    def _watch(self):
        p = self.proc
        if not p:
            return
        p.wait()
        if not self._intentional_stop and self.proc is p:
            self._set(STATE_ERROR, f"Scan engine stopped unexpectedly (code {p.returncode})")

    def _version(self):
        try:
            return self.client.version()
        except OSError:
            return ""

    def stop(self):
        self._intentional_stop = True
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            self.client.shutdown()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
        self._set(STATE_STOPPED)

    def restart(self):
        """Restart clamd (e.g. after settings changed). Requests made while a restart is
        already running are merged into one more restart, never run in parallel."""
        with self._restart_guard:
            self._restart_requested = True
            if self._restarting:
                return
            self._restarting = True

        def run():
            while True:
                with self._restart_guard:
                    if not self._restart_requested:
                        self._restarting = False
                        return
                    self._restart_requested = False
                self.stop()
                self._start()
        threading.Thread(target=run, daemon=True, name="clamd-restart").start()

    def reload_signatures(self):
        if self.ready:
            try:
                self.client.reload()
                # clamd answers RELOADING and swaps the DB in the background
                time.sleep(1)
                for _ in range(240):
                    if self.client.ping():
                        break
                    time.sleep(0.5)
                self._set(STATE_READY, self._version())
                return
            except OSError:
                pass
        self.restart()

    def version_info(self) -> dict:
        """Parse 'ClamAV 1.5.4/27801/Sat Oct 31 09:24:55 2026'."""
        v = self.info if self.state == STATE_READY else ""
        parts = v.split("/")
        return {
            "engine": parts[0] if parts else "",
            "db_version": parts[1] if len(parts) > 1 else "",
            "db_date": parts[2] if len(parts) > 2 else "",
        }

    def scan(self, path: str) -> ScanResult:
        return self.client.scan_file(path)

    def scan_stream(self, name: str, chunks) -> ScanResult:
        return self.client.scan_stream(name, chunks)
