"""Shield — user-level real-time protection.

Uses Linux inotify (via ctypes) to watch the protected folders recursively and
scans every file that is written, moved in or downloaded, through clamd.
No root privileges are required.
"""
import ctypes
import ctypes.util
import os
import select
import struct
import threading
import time

IN_CLOSE_WRITE = 0x00000008
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE_SELF = 0x00000400
IN_IGNORED = 0x00008000
IN_ISDIR = 0x40000000
IN_Q_OVERFLOW = 0x00004000
IN_NONBLOCK = 0x800
IN_CLOEXEC = 0x80000
MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE | IN_DELETE_SELF

_EVENT = struct.Struct("iIII")
SKIP_DIRS = {".git", "node_modules", ".cache", "__pycache__", ".venv", "venv", ".local/share/Trash"}
MAX_WATCHES = 20000


class Shield:
    def __init__(self, engine, settings, quarantine, on_threat=None, on_status=None):
        self.engine = engine
        self.settings = settings
        self.quarantine = quarantine
        self.on_threat = on_threat or (lambda path, name, action: None)
        self.on_status = on_status or (lambda active, info: None)
        self._libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        self.fd = -1
        self._run = None
        self._thread = None
        self._pending: dict[str, float] = {}
        self._plock = threading.Lock()
        self.files_scanned = 0
        self.active = False

    # -- lifecycle ---------------------------------------------------------
    # Each start() creates its own inotify fd, watch table and stop flag, so threads of a
    # previous run can never pick up the fd of a new one (off → on toggles in quick succession).
    def start(self):
        if self.active:
            return
        fd = self._libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            self.on_status(False, f"inotify unavailable: {os.strerror(ctypes.get_errno())}")
            return
        run = {"fd": fd, "stop": threading.Event(), "wd": {}, "ready": False}
        self._run = run
        self.fd = fd
        self.active = True
        self.on_status(True, "Starting…")
        self._thread = threading.Thread(target=self._loop, args=(run,), daemon=True, name="shield")
        self._thread.start()
        threading.Thread(target=self._scanner_loop, args=(run,), daemon=True, name="shield-scan").start()

    def stop(self):
        run, self._run = getattr(self, "_run", None), None
        self.active = False
        self.fd = -1
        if run:
            run["stop"].set()
            try:
                os.close(run["fd"])
            except OSError:
                pass
        with self._plock:
            self._pending.clear()
        self.on_status(False, "Shield is turned off")

    def restart(self):
        self.stop()
        self.start()

    @property
    def wd_to_path(self) -> dict:
        run = getattr(self, "_run", None)
        return run["wd"] if run else {}

    @property
    def watching(self) -> bool:
        run = getattr(self, "_run", None)
        return bool(run and run["ready"])

    # -- watches -----------------------------------------------------------
    def _add_watch(self, run, path):
        if len(run["wd"]) >= MAX_WATCHES or run["stop"].is_set():
            return
        wd = self._libc.inotify_add_watch(run["fd"], os.fsencode(path), MASK)
        if wd >= 0:
            run["wd"][wd] = path

    def _add_tree(self, run, root):
        for dirpath, dirnames, _ in os.walk(root, onerror=lambda e: None):
            if run["stop"].is_set():
                return
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
            if self.settings.is_excepted(dirpath):
                dirnames[:] = []
                continue
            self._add_watch(run, dirpath)

    def _loop(self, run):
        stop, fd = run["stop"], run["fd"]
        roots = [p for p in self.settings.get("antivirus.shield_paths", []) if os.path.isdir(p)]
        for r in roots:
            self._add_tree(run, r)
        if stop.is_set():
            return
        run["ready"] = True
        self.on_status(True, f"Watching {len(run['wd'])} folders")
        poller = select.poll()
        poller.register(fd, select.POLLIN)
        while not stop.is_set():
            try:
                ev = poller.poll(500)
                if stop.is_set():
                    break
                if not ev:
                    continue
                if any(e & (select.POLLNVAL | select.POLLERR) for _, e in ev):
                    break
                data = os.read(fd, 64 * 1024)
            except OSError:
                break
            off = 0
            while off + _EVENT.size <= len(data):
                wd, mask, _cookie, ln = _EVENT.unpack_from(data, off)
                name = data[off + _EVENT.size: off + _EVENT.size + ln].rstrip(b"\0")
                off += _EVENT.size + ln
                base = run["wd"].get(wd)
                if mask & IN_Q_OVERFLOW:
                    continue
                if mask & IN_IGNORED:
                    run["wd"].pop(wd, None)
                    continue
                if base is None or not name:
                    continue
                full = os.path.join(base, os.fsdecode(name))
                if mask & IN_ISDIR:
                    if mask & (IN_CREATE | IN_MOVED_TO) and os.path.basename(full) not in SKIP_DIRS:
                        self._add_tree(run, full)
                    continue
                if mask & (IN_CLOSE_WRITE | IN_MOVED_TO):
                    with self._plock:
                        self._pending[full] = time.time()

    def _scanner_loop(self, run):
        stop = run["stop"]
        while not stop.is_set():
            time.sleep(0.5)
            now = time.time()
            with self._plock:
                due = [p for p, t in self._pending.items() if now - t > 0.8]
                for p in due:
                    self._pending.pop(p, None)
            for p in due:
                if stop.is_set():
                    break
                self._check(p)

    def _check(self, path):
        if not self.engine.ready or self.settings.is_excepted(path):
            return
        if path.endswith((".part", ".crdownload", ".download", ".tmp")) or "/.Trash" in path:
            return
        try:
            st = os.stat(path)
            if st.st_size == 0 or st.st_size > int(self.settings.get("antivirus.max_file_mb", 100)) << 20:
                return
            r = self.engine.scan(path)
        except OSError:
            return
        self.files_scanned += 1
        if r.infected:
            action = self.settings.get("antivirus.action", "quarantine")
            done = "reported"
            try:
                if action == "quarantine":
                    self.quarantine.add(path, r.threat)
                    done = "quarantined"
                elif action == "delete":
                    os.remove(path)
                    done = "deleted"
                else:
                    os.chmod(path, 0)        # deny access
                    done = "access denied"
            except OSError:
                done = "action failed"
            self.on_threat(path, r.threat, done)
