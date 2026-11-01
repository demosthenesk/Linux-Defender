"""Glue between the backend services and the Qt UI (thread-safe signals)."""
import time
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from linux_defender import engine as eng
from linux_defender import integration, paths
from linux_defender.config import Settings
from linux_defender.events import CRITICAL, INFO, WARNING, EventStore
from linux_defender.quarantine import Quarantine
from linux_defender.scanner import ScanJob, quick_scan_targets, system_scan_targets
from linux_defender.shield import Shield
from linux_defender.updater import Updater

SCAN_TITLES = {"quick": "Quick Scan", "system": "System Scan", "custom": "Custom Scan",
               "scheduled": "Scheduled Scan"}


class Controller(QObject):
    engineState = Signal(str, str)
    updateProgress = Signal(str, float)
    updateDone = Signal(bool, bool, str)
    updateState = Signal(str)                # idle | running | paused | stopping
    scanStarted = Signal(object)
    scanProgress = Signal(object)
    scanThreat = Signal(object)
    scanDone = Signal(object)
    scanState = Signal(str)                 # idle | running | paused
    shieldStatus = Signal(bool, str)
    shieldThreat = Signal(str, str, str)
    eventAdded = Signal(dict)
    statusChanged = Signal()
    notify = Signal(str, str, str)          # title, body, level
    quarantineChanged = Signal()
    quarantineRescan = Signal(int, int)     # done, total (total=0 → finished)

    def __init__(self):
        super().__init__()
        paths.ensure_dirs()
        self.settings = Settings()
        self.events = EventStore()
        self.events.listeners.append(lambda ev: self.eventAdded.emit(ev))
        self.quarantine = Quarantine(self.settings.get("quarantine.location") or None,
                                     int(self.settings.get("quarantine.max_size_mb", 0)))
        self._rescan_pending = False
        self._rescanning = False
        import threading as _th
        self._scan_lock = _th.Lock()
        self.engine = eng.Engine(self.settings, on_state=lambda s, i: self.engineState.emit(s, i))
        self.updater = Updater(self.settings,
                               on_progress=lambda t, f: self.updateProgress.emit(t, f),
                               on_done=lambda ok, ch, m: self.updateDone.emit(ok, ch, m),
                               on_state=lambda st: self.updateState.emit(st))
        self.shield = Shield(self.engine, self.settings, self.quarantine,
                             on_threat=lambda p, n, a: self.shieldThreat.emit(p, n, a),
                             on_status=lambda a, i: self.shieldStatus.emit(a, i))
        self.job: ScanJob | None = None
        self.last_job: ScanJob | None = None
        self.update_message = ""
        self.update_ok = None

        self.engineState.connect(self._on_engine_state)
        self.scanState.connect(lambda *_: self.statusChanged.emit())
        self.updateDone.connect(self._on_update_done)
        self.updateState.connect(lambda *_: self.statusChanged.emit())
        self.shieldThreat.connect(self._on_shield_threat)
        self.shieldStatus.connect(lambda *_: self.statusChanged.emit())

        self.timer = QTimer(self)
        self.timer.setInterval(60_000)
        self.timer.timeout.connect(self._tick)

    # -- startup -----------------------------------------------------------
    def start(self):
        try:   # refresh launchers so they follow the AppImage if it was moved/renamed
            if self.settings.get("integration.menu_entry"):
                from linux_defender.ui.icons import app_icon_svg
                integration.set_menu_entry(True, app_icon_svg("safe"))
            if self.settings.get("integration.file_manager"):
                integration.set_file_manager_integration(True)
            if self.settings.get("general.autostart"):
                integration.set_autostart(True)
        except OSError:
            pass
        self._last_limits = time.time()
        self.apply_quarantine_limits()
        self.apply_log_retention()
        self.engine.start()
        self.timer.start()
        QTimer.singleShot(4000, self._tick)

    def shutdown(self):
        self.timer.stop()
        if self.job:
            self.job.stop()
        self.shield.stop()
        self.updater.stop()
        self.engine.stop()

    def _tick(self):
        if time.time() - getattr(self, "_last_limits", 0) > 3600:      # age/size limits, hourly
            self._last_limits = time.time()
            self.apply_quarantine_limits()
            self.apply_log_retention()
        if not self.settings.get("first_run_done"):
            return
        if self.settings.get("update.auto") and not self.updater.running:
            interval = max(1, int(self.settings.get("update.interval_hours", 2))) * 3600
            if self.engine.state == eng.STATE_NO_SIGNATURES or self.update_ok is False:
                interval = min(interval, 15 * 60)
            if time.time() - float(self.settings.get("update.last_check", 0)) >= interval:
                self.update_now(silent=True)
        self._check_schedule()

    # -- engine ------------------------------------------------------------
    # -- quarantine folder -------------------------------------------------------
    def apply_quarantine_limits(self) -> int:
        q = self.quarantine
        q.max_size_mb = int(self.settings.get("quarantine.max_size_mb", 0))
        n = q.purge_older_than(int(self.settings.get("quarantine.auto_delete_days", 30)))
        if n:
            self.events.add(INFO, "Quarantine", f"{n} item(s) older than the age limit removed from quarantine")
        m = q.enforce_size_limit(q.max_size_mb)
        if m:
            self.events.add(INFO, "Quarantine", f"{m} oldest item(s) removed to keep quarantine under "
                                                f"{q.max_size_mb} MB")
        if n or m:
            self.quarantineChanged.emit()
        return n + m

    def apply_log_retention(self) -> int:
        from linux_defender import logs
        n = logs.apply_retention(int(self.settings.get("logs.max_age_days", 90)),
                                 int(self.settings.get("logs.max_scan_logs", 500)))
        if n:
            self.events.add(INFO, "Logs", f"{n} old log file(s) removed by the log retention rules")
        return n

    def move_quarantine(self, chosen: str | None, progress=None):
        """Move the vault to `chosen` (None = default location). Returns the new folder."""
        from pathlib import Path
        from linux_defender.quarantine import resolve_location
        target = paths.QUARANTINE_DIR if not chosen else resolve_location(chosen)
        old = self.quarantine.root
        new = self.quarantine.move_to(target, progress)
        is_default = Path(new).resolve() == paths.QUARANTINE_DIR.resolve()
        self.settings.set("quarantine.location", "" if is_default else str(new))
        if Path(old).resolve() != Path(new).resolve():
            self.events.add(INFO, "Quarantine", "Quarantine folder moved", f"From: {old}\nTo: {new}")
        self.quarantineChanged.emit()
        return new

    def empty_quarantine(self) -> int:
        n = self.quarantine.empty()
        if n:
            self.events.add(INFO, "Quarantine", f"Quarantine emptied ({n} item(s) deleted)")
        self.quarantineChanged.emit()
        return n

    def rescan_quarantine(self, notify_clean=True):
        """Rescan every quarantined item with the current signatures (in the background)."""
        if self._rescanning or not self.engine.ready:
            return False
        self._rescanning = True
        import threading

        def run():
            clean = []
            items = self.quarantine.items()
            total = len(items)
            max_bytes = int(self.settings.get("antivirus.max_file_mb", 100)) << 20
            for i, m in enumerate(items, 1):
                self.quarantineRescan.emit(i - 1, total)
                if m.get("size", 0) > max_bytes:
                    res = {"ts": time.time(), "result": "skipped", "detail": "too large to rescan"}
                else:
                    try:
                        from linux_defender.quarantine import iter_plain
                        r = self.engine.scan_stream(m["path"], iter_plain(self.quarantine.blob(m["id"])))
                        if r.infected:
                            res = {"ts": time.time(), "result": "threat", "detail": r.threat}
                        elif r.status == "OK":
                            res = {"ts": time.time(), "result": "clean", "detail": ""}
                            clean.append(m)
                        else:
                            res = {"ts": time.time(), "result": "error", "detail": r.error}
                    except OSError as e:
                        res = {"ts": time.time(), "result": "error", "detail": str(e)}
                try:
                    self.quarantine.update_meta(m["id"], rescan=res)
                except (OSError, ValueError):
                    pass
            self._rescanning = False
            self.quarantineRescan.emit(total, 0)
            if clean and notify_clean:
                names = "\n".join(f"• {m['threat']} — {m['path']}" for m in clean)
                self.events.add(WARNING, "Quarantine",
                                f"{len(clean)} quarantined item(s) are no longer detected",
                                "With the latest signatures these items are no longer detected as threats. "
                                "They were probably false positives. You can restore them from "
                                "Protection › Quarantine.\n\n" + names)
            self.quarantineChanged.emit()
        threading.Thread(target=run, daemon=True, name="quarantine-rescan").start()
        return True

    def _on_engine_state(self, state, info):
        if state == eng.STATE_READY and self._rescan_pending:
            self._rescan_pending = False
            if self.quarantine.items():
                self.rescan_quarantine()
        if state == eng.STATE_READY and self.settings.get("antivirus.shield_enabled") and not self.shield.active:
            self.shield.start()
        if state == eng.STATE_ERROR:
            self.events.add(CRITICAL, "Antivirus", "Scan engine error", info)
        self.statusChanged.emit()

    # -- updates -----------------------------------------------------------
    def update_now(self, silent=False):
        self._silent_update = silent
        if self.updater.start():
            self.statusChanged.emit()

    def pause_update(self):
        return self.updater.pause()

    def resume_update(self):
        return self.updater.resume()

    def stop_update(self):
        return self.updater.stop()

    def _on_update_done(self, ok, changed, message):
        self.update_message = message
        if self.updater.last_cancelled:
            self.events.add(INFO, "Update", "Signature download stopped", message)
            self.statusChanged.emit()
            return
        self.update_ok = ok
        if ok:
            if changed or self.engine.state in (eng.STATE_NO_SIGNATURES, eng.STATE_ERROR, eng.STATE_STOPPED):
                if self.engine.state == eng.STATE_READY:
                    import threading
                    threading.Thread(target=self.engine.reload_signatures, daemon=True).start()
                else:
                    self.engine.start()
            if changed or not getattr(self, "_silent_update", False):
                self.events.add(INFO, "Update", message)
            if changed and self.settings.get("quarantine.rescan_after_update"):
                self._rescan_pending = True          # runs once the engine has loaded the new signatures
        else:
            self.events.add(WARNING, "Update", "Update failed", message)
            if not getattr(self, "_silent_update", False):
                self.notify.emit("Update failed", message, "warning")
        self.statusChanged.emit()

    # -- shield ------------------------------------------------------------
    def set_shield(self, enabled: bool):
        self.settings.set("antivirus.shield_enabled", enabled)
        if enabled:
            if self.engine.ready:
                self.shield.start()
            self.events.add(INFO, "Shield", "Real-time protection turned on",
                            "The Shield scans files as soon as they are created, downloaded or modified in "
                            "your protected folders:\n" +
                            "\n".join("• " + p for p in self.settings.get("antivirus.shield_paths", [])))
        else:
            self.shield.stop()
            self.events.add(WARNING, "Shield", "Real-time protection turned off",
                            "New and downloaded files are no longer scanned automatically. Turn the Shield back "
                            "on in Protection › Antivirus › Shield.")
        self.statusChanged.emit()

    def _on_shield_threat(self, path, name, action):
        self.events.add(CRITICAL, "Shield", f"Threat blocked: {name}",
                        f"File: {path}\nAction taken: {action}", {"path": path, "threat": name})
        self.notify.emit("Threat blocked", f"{name}\n{path}\nAction: {action}", "critical")
        self.statusChanged.emit()

    # -- scans -------------------------------------------------------------
    def start_scan(self, kind: str, targets=None, title=None):
        # one scan at a time: the check and the start are atomic, so two requests arriving together
        # (button + file manager + schedule) can never start two scans
        with self._scan_lock:
            if self.job and self.job.running:
                return None
            if not self.engine.ready:
                return None
            return self._start_scan_locked(kind, targets, title)

    def _start_scan_locked(self, kind, targets, title):
        if kind == "quick":
            targets = quick_scan_targets()
        elif kind == "system":
            targets = system_scan_targets(self.settings.get("antivirus.system_scan_other_mounts"))
        elif kind == "scheduled":
            st = self.settings.get("schedule.type", "quick")
            targets = quick_scan_targets() if st == "quick" else system_scan_targets()
        job = ScanJob(kind, targets or [], self.engine, self.settings, self.quarantine, self.events,
                      on_progress=lambda s: self.scanProgress.emit(s),
                      on_threat=lambda t: self.scanThreat.emit(t),
                      on_done=lambda j: self.scanDone.emit(j))
        job.title = title or SCAN_TITLES.get(kind, "Scan")
        # which scan type the job belongs to (a scheduled scan is a quick or system scan)
        job.base_kind = self.settings.get("schedule.type", "quick") if kind == "scheduled" else kind
        self.job = job
        job.start()
        self.scanStarted.emit(job)
        self.scanState.emit("running")
        return job

    # -- scan controls (used by every place a scan can be started) -------------
    def scan_state(self) -> str:
        j = self.job
        if not (j and j.running):
            return "idle"
        return "paused" if j.paused else "running"

    def pause_scan(self):
        if self.job and self.job.running and self.job.pause():
            self.scanState.emit("paused")
            return True
        return False

    def resume_scan(self):
        if self.job and self.job.running and self.job.resume():
            self.scanState.emit("running")
            return True
        return False

    def stop_scan(self):
        if self.job and self.job.running:
            self.job.stop()
            return True
        return False

    def finish_scan_bookkeeping(self, job):
        self.last_job = job
        self.scanState.emit("idle")
        s = job.stats
        if job.cancelled:
            lvl, title = INFO, f"{job.title} stopped"
        elif s.infected and s.unresolved:
            lvl, title = CRITICAL, f"{job.title}: {s.unresolved} unresolved threat(s)"
        elif s.infected:
            lvl, title = WARNING, f"{job.title}: {s.infected} threat(s) resolved"
        else:
            lvl, title = INFO, f"{job.title} finished — no threats found"
        mins, secs = divmod(int(s.elapsed), 60)
        self.events.add(lvl, "Antivirus", title,
                        f"Scanned items: {s.scanned}\nSkipped: {s.skipped}\nThreats: {s.infected}\n"
                        f"Resolved: {s.resolved}\nUnresolved: {s.unresolved}\nErrors: {s.errors}\n"
                        f"Duration: {mins}m {secs}s",
                        {"log": getattr(job, "log_file", ""), "threats": [t.to_dict() for t in job.threats]})
        if job.kind == "scheduled" or not self.parent_visible():
            self.notify.emit(title, f"{s.scanned} items scanned", lvl)
        self.statusChanged.emit()

    def parent_visible(self):
        return getattr(self, "window_visible", lambda: True)()

    # -- scheduled scans -----------------------------------------------------------
    def _sched_time(self):
        try:
            hh, mm = (int(x) for x in self.settings.get("schedule.time", "12:00").split(":"))
        except ValueError:
            hh, mm = 12, 0
        return hh, mm

    def _occurrences(self, after: datetime, count=3):
        """The next `count` scheduled times strictly after `after`."""
        from datetime import timedelta
        sc = self.settings.get("schedule")
        hh, mm = self._sched_time()
        cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
        out = []
        for _ in range(30):
            ok_day = sc.get("frequency") != "weekly" or cand.weekday() == int(sc.get("weekday", 6))
            if cand > after and ok_day:
                out.append(cand)
                if len(out) == count:
                    break
            cand += timedelta(days=1)
        return out

    def _due_now(self):
        """Today's scheduled time if it has passed and has not run yet, else None."""
        sc = self.settings.get("schedule")
        if not sc.get("enabled"):
            return None
        now = datetime.now()
        hh, mm = self._sched_time()
        due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if sc.get("frequency") == "weekly" and now.weekday() != int(sc.get("weekday", 6)):
            return None
        if now < due or float(sc.get("last_run", 0)) >= due.timestamp():
            return None
        return due

    def _is_skipped(self, when: datetime) -> bool:
        return abs(float(self.settings.get("schedule.skip_ts", 0) or 0) - when.timestamp()) < 1

    def next_scheduled_run(self):
        """datetime of the next scheduled scan that will really run, or None when scheduling is off."""
        if not self.settings.get("schedule.enabled"):
            return None
        after = datetime.fromtimestamp(max(time.time(), float(self.settings.get("schedule.last_run", 0))))
        for occ in self._occurrences(after):
            if not self._is_skipped(occ):
                return occ
        return None

    def scheduled_state(self) -> dict:
        """What the schedule is doing right now, for the Scheduled scans page."""
        sc = self.settings.get("schedule")
        j = self.job
        if j and j.running and j.kind == "scheduled":
            return {"state": "paused" if j.paused else "running", "job": j}
        if not sc.get("enabled"):
            return {"state": "off"}
        due = self._due_now()
        if due:
            if self._is_skipped(due):
                return {"state": "skipped_due", "when": due}
            why = (f"the {j.title} to finish" if j and j.running else
                   "the scan engine to start" if not self.engine.ready else "the next check (within a minute)")
            return {"state": "waiting", "when": due, "why": why}
        after = datetime.fromtimestamp(max(time.time(), float(sc.get("last_run", 0))))
        occ = self._occurrences(after)
        if occ and self._is_skipped(occ[0]):
            return {"state": "skipped", "when": occ[0], "next": occ[1] if len(occ) > 1 else None}
        return {"state": "scheduled", "when": occ[0] if occ else None}

    def skip_next_scheduled(self) -> bool:
        """Cancel only the upcoming (or waiting) scheduled scan; the schedule stays on."""
        st = self.scheduled_state()
        if st["state"] in ("waiting", "scheduled") and st.get("when"):
            self.settings.set("schedule.skip_ts", st["when"].timestamp())
            self.events.add(INFO, "Antivirus", "Next scheduled scan skipped",
                            f"The scheduled scan of {st['when'].strftime('%A %d %b %Y, %H:%M')} will not run. "
                            "The schedule stays on.")
            self.statusChanged.emit()
            return True
        return False

    def undo_skip_scheduled(self):
        self.settings.set("schedule.skip_ts", 0)
        self.statusChanged.emit()

    def stop_scheduled_scan(self) -> bool:
        j = self.job
        if j and j.running and j.kind == "scheduled":
            return self.stop_scan()
        return False

    def _check_schedule(self):
        sc = self.settings.get("schedule")
        if not sc.get("enabled") or (self.job and self.job.running) or not self.engine.ready:
            return
        due = self._due_now()
        if not due:
            return
        self.settings.set("schedule.last_run", time.time(), save=False)
        if self._is_skipped(due):                       # the user skipped this run
            self.settings.set("schedule.skip_ts", 0)
            self.statusChanged.emit()
            return
        self.settings.set("schedule.last_ran", time.time())
        self.start_scan("scheduled", title="Scheduled " + ("Quick" if sc.get("type") == "quick" else "System") + " Scan")

    # -- status ------------------------------------------------------------
    def issues(self) -> list[dict]:
        """Dashboard issues, worst first: {level, title, desc, fix, action}."""
        out = []
        st = self.engine.state
        if st == eng.STATE_NO_ENGINE:
            out.append(dict(level="risk", title="Scan engine missing",
                            desc="ClamAV could not be found. Reinstall Linux Defender or run: sudo apt install clamav-daemon",
                            fix="", action=None))
        elif st == eng.STATE_NO_SIGNATURES:
            out.append(dict(level="risk", title="Threat signatures not downloaded",
                            desc="Linux Defender needs threat information (about 230 MB) before it can protect you.",
                            fix="Download now", action="update"))
        elif st == eng.STATE_ERROR:
            out.append(dict(level="risk", title="Scan engine stopped", desc=self.engine.info,
                            fix="Restart engine", action="restart_engine"))
        if not self.settings.get("antivirus.shield_enabled"):
            out.append(dict(level="warn", title="Real-time protection is off",
                            desc="Shield does not scan new and downloaded files.",
                            fix="Turn on", action="shield_on"))
        last = float(self.settings.get("update.last_success", 0))
        if st not in (eng.STATE_NO_SIGNATURES, eng.STATE_NO_ENGINE) and last and time.time() - last > 3 * 86400:
            days = int((time.time() - last) // 86400)
            out.append(dict(level="warn", title="Threat signatures are outdated",
                            desc=f"Last successful update was {days} days ago.", fix="Update now", action="update"))
        j = self.last_job
        if j and j.stats.unresolved:
            out.append(dict(level="risk", title=f"{j.stats.unresolved} unresolved threat(s)",
                            desc="The last scan found threats that still need your attention.",
                            fix="Review", action="review_scan"))
        return out

    def shield_state(self) -> tuple[str, str, str]:
        """(level, short text, long text) describing what the Shield is really doing right now."""
        if not self.settings.get("antivirus.shield_enabled"):
            return ("off", "Off", "Shield is turned off. New and downloaded files are not scanned.")
        st = self.engine.state
        if st == eng.STATE_NO_SIGNATURES:
            return ("waiting", "Waiting for signatures",
                    "Shield is on, but protection starts only after the threat signatures are downloaded. "
                    "Run an update.")
        if st == eng.STATE_LOADING:
            return ("waiting", "Starting…", "Shield is on and starting while the scan engine loads the threat signatures…")
        if st == eng.STATE_STOPPED:
            return ("waiting", "Starting…", "Shield is on and waiting for the scan engine to start…")
        if st in (eng.STATE_ERROR, eng.STATE_NO_ENGINE):
            return ("error", "Not protecting",
                    f"Shield is on, but the scan engine is not running: {self.engine.info or st}.")
        if not self.shield.active or not self.shield.watching:
            return ("waiting", "Starting…", "Shield is on and preparing your protected folders…")
        n = len(self.shield.wd_to_path)
        return ("active", "On",
                f"Shield is active. Watching {n} folder{'s' if n != 1 else ''} · "
                f"{self.shield.files_scanned} file(s) checked this session.")

    def scan_unavailable_reason(self) -> str:
        """'' when a scan can start now, otherwise why not (shown on scan buttons and tiles)."""
        if self.job and self.job.running:
            return "A scan is already running."
        st = self.engine.state
        if st == eng.STATE_READY:
            return ""
        return {
            eng.STATE_NO_SIGNATURES: "Available after the threat signatures are downloaded.",
            eng.STATE_LOADING: "Available in a moment, while the scan engine loads.",
            eng.STATE_STOPPED: "Available in a moment, while the scan engine starts.",
            eng.STATE_NO_ENGINE: "The scan engine (ClamAV) was not found.",
        }.get(st, "The scan engine is not running. Restart it from Support.")

    def overall(self) -> str:
        iss = self.issues()
        if any(i["level"] == "risk" for i in iss):
            return "risk"
        if iss:
            return "warn"
        if self.engine.state == eng.STATE_LOADING:
            return "idle"
        return "safe"

    def open_url(self, url):
        integration.open_url(url)
