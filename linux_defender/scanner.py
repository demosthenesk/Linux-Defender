"""On-demand scan jobs.

Scan types:
  * Quick Scan  – running programs, autostart entries, Downloads, Desktop, temp dirs
  * System Scan – the whole system (root filesystem + /home), skipping virtual FS
  * Custom Scan – user-chosen files and folders
"""
import os
import queue
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from linux_defender.quarantine import delete_file

HOME = str(Path.home())
VIRTUAL_FS = {"/proc", "/sys", "/dev", "/run", "/var/run", "/var/lock", "/snap",
              "/var/lib/docker", "/var/lib/containers", "/var/lib/snapd/snaps", "/lost+found"}


def quick_scan_targets() -> list[str]:
    t = [f"{HOME}/Downloads", f"{HOME}/Desktop", "/tmp", "/var/tmp", "/dev/shm",
         f"{HOME}/.config/autostart", f"{HOME}/.local/bin", f"{HOME}/.local/share/applications",
         "/etc/xdg/autostart", "/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly",
         f"{HOME}/.bashrc", f"{HOME}/.profile", f"{HOME}/.bash_profile", f"{HOME}/.xprofile"]
    # executables of running processes (only those we may read)
    seen = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        if exe.endswith(" (deleted)") or exe in seen:
            continue
        seen.add(exe)
        t.append(exe)
    return [p for p in t if os.path.exists(p)]


def system_scan_targets(other_mounts=False) -> list[str]:
    targets = ["/"]
    if other_mounts:
        try:
            with open("/proc/self/mounts") as f:
                for line in f:
                    dev, mnt, fstype = line.split()[:3]
                    mnt = mnt.replace("\\040", " ")
                    if dev.startswith("/dev/") and fstype not in ("squashfs", "iso9660") and mnt != "/":
                        targets.append(mnt)
        except OSError:
            pass
    return targets


class LockedReport:
    """The scan report file of a running scan.

    Created when the scan starts and kept open with an exclusive lock (flock) and read-only
    permissions until the scan ends. The Logs manager treats a locked report as "in use" and never
    moves or deletes it. If the file is removed behind our back, it is written again.
    """

    def __init__(self, path):
        import fcntl
        self._fcntl = fcntl
        self.path = str(path)
        self._mx = threading.Lock()
        self.fd = self._open()

    def _open(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            self._fcntl.flock(fd, self._fcntl.LOCK_EX | self._fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise
        os.fchmod(fd, 0o444)               # read-only while the scan runs
        return fd

    def write(self, data: bytes):
        with self._mx:
            self._write(data)

    def _write(self, data: bytes):
        if self.fd is None:
            return
        try:
            if os.fstat(self.fd).st_nlink == 0:        # deleted from outside: put it back
                os.close(self.fd)
                self.fd = self._open()
            os.ftruncate(self.fd, 0)
            os.pwrite(self.fd, data, 0)
        except OSError:
            pass

    def close(self, data: bytes):
        """Write the final report and unlock it."""
        with self._mx:
            self._write(data)
            if self.fd is not None:
                try:
                    os.fchmod(self.fd, 0o644)
                    self._fcntl.flock(self.fd, self._fcntl.LOCK_UN)
                finally:
                    os.close(self.fd)
                    self.fd = None


class ScanStats:
    def __init__(self):
        self.scanned = 0
        self.infected = 0
        self.resolved = 0
        self.unresolved = 0
        self.errors = 0
        self.skipped = 0
        self.started = time.time()
        self.finished = 0.0
        self.current = ""

    paused_total = 0.0
    paused_at = 0.0

    @property
    def elapsed(self):
        """Scan time, not counting time spent paused."""
        end = self.finished or time.time()
        paused = self.paused_total + ((end - self.paused_at) if self.paused_at else 0.0)
        return max(0.0, end - self.started - paused)


class Threat:
    def __init__(self, path, name):
        self.path, self.name = path, name
        self.action = "none"     # quarantined | deleted | ignored | excepted | failed | none
        self.error = ""

    def to_dict(self):
        return {"path": self.path, "name": self.name, "action": self.action, "error": self.error}


class ScanJob:
    """Walks targets in a producer thread and scans files with a worker pool."""

    def __init__(self, kind, targets, engine, settings, quarantine, events,
                 on_progress=None, on_threat=None, on_done=None, one_file_system=True):
        self.kind = kind
        self.targets = list(targets)
        self.engine = engine
        self.settings = settings
        self.quarantine = quarantine
        self.events = events
        self.on_progress = on_progress or (lambda stats: None)
        self.on_threat = on_threat or (lambda threat: None)
        self.on_done = on_done or (lambda job: None)
        self.one_file_system = one_file_system
        self.stats = ScanStats()
        self.threats: list[Threat] = []
        self.errors: list[tuple[str, str]] = []
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()
        self._lock = threading.Lock()
        self.cancelled = False
        self.thread = None
        self.max_bytes = int(settings.get("antivirus.max_file_mb", 100)) << 20

    # -- control -----------------------------------------------------------
    def start(self):
        self._open_report()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"scan-{self.kind}")
        self.thread.start()
        threading.Thread(target=self._report_loop, daemon=True, name=f"scan-report-{self.kind}").start()

    def stop(self):
        self.cancelled = True
        self._stop.set()
        self.resume()                       # let paused workers see the stop

    def pause(self):
        if self._pause.is_set() and self.running:
            self._pause.clear()
            self.stats.paused_at = time.time()
            return True
        return False

    def resume(self):
        if not self._pause.is_set():
            if self.stats.paused_at:
                self.stats.paused_total += time.time() - self.stats.paused_at
                self.stats.paused_at = 0.0
            self._pause.set()
            return True
        return False

    @property
    def paused(self):
        return not self._pause.is_set()

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    # -- walking -----------------------------------------------------------
    def _iter_files(self):
        seen_dirs = set()
        for target in self.targets:
            if self._stop.is_set():
                return
            try:
                st = os.lstat(target)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                if not self.settings.is_excepted(target):
                    yield target, st
                continue
            if not stat.S_ISDIR(st.st_mode):
                continue
            root_dev = st.st_dev
            stack = [target]
            while stack:
                if self._stop.is_set():
                    return
                d = stack.pop()
                if d in VIRTUAL_FS or self.settings.is_excepted(d):
                    continue
                try:
                    dst = os.stat(d)
                except OSError:
                    continue
                key = (dst.st_dev, dst.st_ino)
                if key in seen_dirs:
                    continue
                seen_dirs.add(key)
                try:
                    with os.scandir(d) as it:
                        entries = list(it)
                except OSError:
                    continue
                for e in entries:
                    try:
                        if e.is_symlink():
                            continue
                        est = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(est.st_mode):
                        if self.one_file_system and est.st_dev != root_dev and self.kind != "custom":
                            continue
                        stack.append(e.path)
                    elif stat.S_ISREG(est.st_mode):
                        if not self.settings.is_excepted(e.path):
                            yield e.path, est

    # -- scanning ----------------------------------------------------------
    def _scan_one(self, path, st):
        try:
            self._scan_one_inner(path, st)
        except Exception as e:
            with self._lock:
                self.stats.errors += 1
                self.errors.append((path, repr(e)))

    def _scan_one_inner(self, path, st):
        self._pause.wait()
        if self._stop.is_set():
            return
        if st.st_size == 0 or st.st_size > self.max_bytes or not os.access(path, os.R_OK):
            with self._lock:
                self.stats.skipped += 1
            return
        try:
            r = self.engine.scan(path)
        except OSError as e:
            r = None
            err = str(e)
        with self._lock:
            self.stats.scanned += 1
            self.stats.current = path
        if r is None:
            with self._lock:
                self.stats.errors += 1
                self.errors.append((path, err))
            return
        if r.status == "ERROR":
            with self._lock:
                self.stats.errors += 1
                self.errors.append((path, r.error))
            return
        if r.infected:
            self._handle_threat(Threat(path, r.threat))

    def _handle_threat(self, t: Threat):
        action = self.settings.get("antivirus.action", "quarantine")
        try:
            if action == "quarantine":
                self.quarantine.add(t.path, t.name)
                t.action = "quarantined"
            elif action == "delete":
                delete_file(t.path)
                t.action = "deleted"
        except OSError as e:
            t.action, t.error = "failed", e.strerror or str(e)
        with self._lock:
            self.threats.append(t)
            self.stats.infected += 1
            if t.action in ("quarantined", "deleted"):
                self.stats.resolved += 1
            else:
                self.stats.unresolved += 1
        self.on_threat(t)

    def resolve(self, t: Threat, action: str):
        """Apply a user decision to an unresolved threat after the scan."""
        try:
            if action == "quarantine":
                self.quarantine.add(t.path, t.name)
                t.action = "quarantined"
            elif action == "delete":
                delete_file(t.path)
                t.action = "deleted"
            elif action == "except":
                ex = self.settings.get("exceptions", [])
                ex.append({"path": t.path, "added": time.time()})
                self.settings.set("exceptions", ex)
                t.action = "excepted"
            else:
                t.action = "ignored"
            t.error = ""
        except OSError as e:
            t.action, t.error = "failed", e.strerror or str(e)
        with self._lock:
            unresolved = [x for x in self.threats if x.action in ("none", "failed")]
            self.stats.unresolved = len(unresolved)
            self.stats.resolved = self.stats.infected - self.stats.unresolved
        return t

    def _run(self):
        try:
            self._run_inner()
        except Exception as e:  # never leave the UI waiting for a scan that died
            self.errors.append(("<scanner>", repr(e)))
            self.stats.errors += 1
        finally:
            self.stats.finished = self.stats.finished or time.time()
            self.on_progress(self.stats)
            try:
                self._log()
            except Exception:
                pass
            self.on_done(self)

    def _run_inner(self):
        q: queue.Queue = queue.Queue(maxsize=512)
        producer_done = threading.Event()

        def producer():
            try:
                for item in self._iter_files():
                    self._pause.wait()
                    while not self._stop.is_set():
                        try:
                            q.put(item, timeout=0.2)
                            break
                        except queue.Full:
                            continue
                    if self._stop.is_set():
                        break
            finally:
                producer_done.set()

        threading.Thread(target=producer, daemon=True).start()
        last_report = 0.0
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = set()
            while not (producer_done.is_set() and q.empty()) and not self._stop.is_set():
                try:
                    path, st = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                pending.add(pool.submit(self._scan_one, path, st))
                if len(pending) > 32:
                    pending = {f for f in pending if not f.done()}
                    if len(pending) > 32:
                        next(iter(pending)).result()
                now = time.time()
                if now - last_report > 0.25:
                    last_report = now
                    self.on_progress(self.stats)
            for f in pending:
                f.result()
        self.stats.finished = time.time()

    # -- report file ---------------------------------------------------------
    def status(self) -> str:
        if self.stats.finished:
            return "stopped" if self.cancelled else "finished"
        return "paused" if self.paused else "running"

    def _record(self) -> dict:
        return {
            "kind": self.kind, "title": getattr(self, "title", ""), "status": self.status(),
            "targets": self.targets[:50], "started": self.stats.started,
            "finished": self.stats.finished, "cancelled": self.cancelled,
            "scanned": self.stats.scanned, "skipped": self.stats.skipped,
            "infected": self.stats.infected, "resolved": self.stats.resolved,
            "unresolved": self.stats.unresolved, "errors": self.stats.errors,
            "elapsed": self.stats.elapsed,
            "threats": [t.to_dict() for t in self.threats],
            "error_samples": self.errors[:200],
        }

    def _open_report(self):
        from linux_defender import paths
        paths.SCAN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        base = time.strftime(f"%Y%m%d-%H%M%S-{self.kind}", time.localtime(self.stats.started))
        fn = paths.SCAN_LOG_DIR / f"{base}.json"
        i = 1
        while fn.exists():
            fn = paths.SCAN_LOG_DIR / f"{base}-{i}.json"
            i += 1
        try:
            self.report = LockedReport(fn)
            self.log_file = str(fn)
            self._write_report()
        except OSError:
            self.report = None
            self.log_file = ""

    def _write_report(self):
        import json
        rep = getattr(self, "report", None)
        if rep:
            rep.write(json.dumps(self._record(), indent=1).encode())

    def _report_loop(self):
        """Keep the locked report up to date (every 2 s, and immediately on pause/resume)."""
        while self.thread and self.thread.is_alive():
            st = self.status()
            self._write_report()
            for _ in range(20):
                time.sleep(0.1)
                if self.status() != st or not self.thread.is_alive():
                    break

    def _log(self):
        """Final report: written, then unlocked."""
        import json
        if getattr(self, "report", None):
            self.report.close(json.dumps(self._record(), indent=1).encode())
            self.report = None
