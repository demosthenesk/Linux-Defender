"""Application pages (Dashboard, Protection, Scan, Notifications, Settings, Support)."""
import os
import time
from datetime import datetime

from PySide6.QtCore import QDateTime, QSize, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QTabWidget, QTimeEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from linux_defender import APP_NAME, VERSION, integration, paths
from linux_defender import engine as eng
from linux_defender.ui.icons import app_pixmap, svg_icon, svg_pixmap
from linux_defender.ui.style import color
from linux_defender.ui.widgets import IconLabel, SettingRow, Tile, Toggle, button, card, fit_field, label, sep

LEVEL_ICON = {"risk": "critical", "warn": "warning", "info": "info",
              "critical": "critical", "warning": "warning"}


def fmt_time(ts):
    if not ts:
        return "never"
    d = datetime.fromtimestamp(ts)
    if d.date() == datetime.now().date():
        return "today, " + d.strftime("%H:%M")
    return d.strftime("%d %b %Y, %H:%M")


def fmt_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(widget)
    return sa


class Page(QWidget):
    def __init__(self, ctl, title, theme_getter):
        super().__init__()
        self.ctl = ctl
        self.theme = theme_getter
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(32, 26, 32, 26)
        self.lay.setSpacing(16)
        if title:
            self.title_label = label(title, "PageTitle")
            self.lay.addWidget(self.title_label)
        self.outer.addWidget(scroll(body))

    def c(self, key):
        return color(self.theme(), key)

    def refresh(self):
        pass


# ---------------------------------------------------------------- Update controls
class UpdatePanel(QWidget):
    """Signature download with Download / Pause / Resume / Stop.
    Used in Settings › Update, on the Dashboard and in the first-run setup."""

    def __init__(self, ctl, show_last=True):
        super().__init__()
        self.ctl = ctl
        self.show_last = show_last
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.status = label("", wrap=True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setFixedHeight(10)
        self.bar.hide()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        self.b_start = button("Update now", "Primary", icon="update", color="#062016", on_click=self._start)
        self.b_pause = button("Pause", icon="pause", on_click=ctl.pause_update)
        self.b_resume = button("Resume", "Primary", icon="play", color="#062016", on_click=ctl.resume_update)
        self.b_stop = button("Stop", "Danger", icon="stop", color="#ff6a6a", on_click=self._stop)
        for b in (self.b_start, self.b_pause, self.b_resume, self.b_stop):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.last = label("", wrap=True, muted=True)
        lay.addWidget(self.last)
        self.last.setVisible(show_last)
        self._result = ("", "")                  # (text, css) of the last finished run
        ctl.updateProgress.connect(self._progress)
        ctl.updateState.connect(lambda *_: self.sync())
        ctl.updateDone.connect(self._done)
        ctl.engineState.connect(lambda *_: self.sync())
        self.sync()

    def _start(self):
        self._result = ("", "")
        self.ctl.update_now()

    def _stop(self):
        if self.ctl.updater.state == "paused" or QMessageBox.question(
                self, "Stop download", "Stop downloading the threat signatures?\n\n"
                "Database files that have already finished are kept; the file in progress is discarded.") \
                == QMessageBox.Yes:
            self.ctl.stop_update()

    def sync(self):
        u = self.ctl.updater
        st = u.state
        no_sigs = not eng.signatures_present()
        self.b_start.setText("Download signatures" if no_sigs else "Update now")
        self.b_start.setVisible(st == "idle")
        self.b_pause.setVisible(st == "running")
        self.b_resume.setVisible(st == "paused")
        self.b_stop.setVisible(st in ("running", "paused", "stopping"))
        self.b_stop.setEnabled(st != "stopping")
        self.bar.setVisible(st != "idle")
        if st == "idle":
            text, css = self._result
            if not text and no_sigs:
                text, css = ("Threat signatures have not been downloaded yet (about 230 MB).", "color:#ffc24b;")
            self.status.setText(text)
            self.status.setStyleSheet(css)
            self.status.setVisible(bool(text))
        elif st == "paused":
            self.status.setVisible(True)
            self.status.setText(u.progress_text if u.progress_text.startswith("Paused") else "Paused")
            self.status.setStyleSheet("color:#ffc24b;")
            self._bar_value(u.progress_frac, paused=True)
        elif st == "stopping":
            self.status.setVisible(True)
            self.status.setText("Stopping the download…")
            self.status.setStyleSheet("")
            self._bar_value(-1)
        else:
            self.status.setVisible(True)
            self.status.setText(u.progress_text or "Starting…")
            self.status.setStyleSheet("")
            self._bar_value(u.progress_frac)
        last = self.ctl.settings.get("update.last_success")
        self.last.setText(f"Last successful update: {fmt_time(last)}")

    def _bar_value(self, frac, paused=False):
        if frac is None or frac < 0:
            if paused:
                self.bar.setRange(0, 1000)
                self.bar.setValue(0)
            else:
                self.bar.setRange(0, 0)          # busy indicator
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(frac * 1000))

    def _progress(self, text, frac):
        st = self.ctl.updater.state
        if st == "idle":
            return
        if st == "paused" and not text.startswith("Paused"):
            text = "Paused — " + text
        self.status.setVisible(True)
        self.status.setText(text)
        self.status.setStyleSheet("color:#ffc24b;" if st == "paused" else "")
        self._bar_value(frac, paused=(st == "paused"))

    def _done(self, ok, changed, message):
        if self.ctl.updater.last_cancelled:
            self._result = (message, "")
        elif ok:
            self._result = (message, "color:#2fd38a;")
        else:
            self._result = (f"Update failed: {message}", "color:#ff6a6a;")
        self.sync()


# ---------------------------------------------------------------- Scan controls
class ScanControls(QWidget):
    """Start / Pause / Resume / Stop for one scan type (kind=None: whatever scan is running).
    Used on each scan's row, on the Dashboard, on the scan screen and mirrored in the tray menu."""

    def __init__(self, ctl, kind=None, start_text="Run scan", on_start=None):
        super().__init__()
        self.ctl, self.kind, self.on_start = ctl, kind, on_start
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.b_start = button(start_text, "Primary", icon="play", color="#062016", on_click=self._start)
        self.b_pause = button("Pause", icon="pause", on_click=ctl.pause_scan)
        self.b_resume = button("Resume", "Primary", icon="play", color="#062016", on_click=ctl.resume_scan)
        self.b_stop = button("Stop", "Danger", icon="stop", color="#ff6a6a", on_click=self._stop)
        for b in (self.b_start, self.b_pause, self.b_resume, self.b_stop):
            lay.addWidget(b)
        self.b_start.setVisible(on_start is not None)
        ctl.scanState.connect(lambda *_: self.sync())
        ctl.statusChanged.connect(self.sync)
        self.sync()

    def _start(self):
        if self.on_start:
            self.on_start()

    def _stop(self):
        if QMessageBox.question(self, "Stop scan", "Are you sure you want to stop the scan?") == QMessageBox.Yes:
            self.ctl.stop_scan()

    def mine(self) -> bool:
        j = self.ctl.job
        if not (j and j.running):
            return False
        if self.kind == "scheduled":                   # only the scheduled scan itself
            return j.kind == "scheduled"
        return self.kind is None or getattr(j, "base_kind", j.kind) == self.kind

    def sync(self):
        st = self.ctl.scan_state()
        mine = self.mine()
        if self.on_start is not None:
            self.b_start.setVisible(not mine)
            why = self.ctl.scan_unavailable_reason()
            self.b_start.setEnabled(not why)
            self.b_start.setToolTip(why)
        self.b_pause.setVisible(mine and st == "running")
        self.b_resume.setVisible(mine and st == "paused")
        self.b_stop.setVisible(mine)


# ---------------------------------------------------------------- Dashboard
class DashboardPage(Page):
    navigate = Signal(str)

    def __init__(self, ctl, theme):
        super().__init__(ctl, "Dashboard", theme)
        hero, hl = card(margins=24, layout="h")
        self.hero_icon = QLabel()
        self.hero_icon.setFixedSize(104, 104)
        hl.addWidget(self.hero_icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.hero_title = label("", "Hero")
        self.hero_sub = label("", wrap=True, muted=True)
        col.addStretch(1)
        col.addWidget(self.hero_title)
        col.addWidget(self.hero_sub)
        col.addStretch(1)
        hl.addSpacing(10)
        hl.addLayout(col, 1)
        self.lay.addWidget(hero)

        self.issues_box = QVBoxLayout()
        self.issues_box.setSpacing(8)
        self.lay.addLayout(self.issues_box)

        self.scan_card, scl = card(obj="Card2", margins=16, spacing=6)
        self.scan_title = label("", "H2")
        scl.addWidget(self.scan_title)
        self.scan_line = label("", muted=True)
        self.scan_line.setTextInteractionFlags(Qt.NoTextInteraction)
        scl.addWidget(self.scan_line)
        srow = QHBoxLayout()
        self.scan_controls = ScanControls(ctl, None)
        srow.addWidget(self.scan_controls)
        srow.addStretch(1)
        srow.addWidget(button("View details", icon="log", on_click=lambda: self.navigate.emit("action:view_scan")))
        scl.addLayout(srow)
        self.lay.addWidget(self.scan_card)
        self.scan_card.hide()
        ctl.scanProgress.connect(self._scan_progress)

        self.dl_card, dcl = card(obj="Card2", margins=16, spacing=6)
        dcl.addWidget(label("Threat signature download", "H2"))
        self.update_panel = UpdatePanel(ctl, show_last=False)
        dcl.addWidget(self.update_panel)
        self.lay.addWidget(self.dl_card)
        self.dl_card.hide()

        self.lay.addWidget(label("Quick actions", "H2"))
        grid = QGridLayout()
        grid.setSpacing(14)
        self.qa = {}
        specs = [("quick", "quick", "Quick Scan", "Running programs, startup items, Downloads and temp folders.", "Run scan"),
                 ("system", "system", "System Scan", "A deep scan of every file on your system.", "Run scan"),
                 ("custom", "custom", "Custom Scan", "Choose the files and folders to scan.", "Choose…"),
                 ("update", "update", "Update", "Download the latest threat signatures.", "Update now")]
        for i, (key, icon, title, desc, act) in enumerate(specs):
            t = Tile(icon, title, desc, act, "#4c9dff" if key == "update" else "#2fd38a")
            t.clicked.connect(lambda k=key: self.navigate.emit("action:" + k))
            grid.addWidget(t, 0, i)
            grid.setColumnStretch(i, 1)
            self.qa[key] = t
        self.lay.addLayout(grid)

        self.lay.addWidget(label("Protection overview", "H2"))
        ov, ol = card(layout="h", spacing=24)
        self.ov_engine = self._stat(ol, "Scan engine")
        self.ov_sigs = self._stat(ol, "Threat signatures")
        self.ov_update = self._stat(ol, "Last update")
        self.ov_shield = self._stat(ol, "Shield")
        self.ov_quar = self._stat(ol, "Quarantine")
        self.lay.addWidget(ov)

        self.lay.addStretch(1)

    def _scan_progress(self, _stats):
        j = self.ctl.job
        running = bool(j and j.running)
        self.scan_card.setVisible(running)
        if not running:
            return
        self.scan_controls.sync()
        paused = j.paused
        self.scan_title.setText(f"{j.title} — " + ("paused" if paused else "in progress"))
        self.scan_title.setStyleSheet("color:#ffc24b;" if paused else "")
        s = j.stats
        m, sec = divmod(int(s.elapsed), 60)
        cur = self.scan_line.fontMetrics().elidedText(s.current or "Preparing…", Qt.ElideMiddle, 520)
        self.scan_line.setText(f"{s.scanned:,} items scanned · {s.infected} threat(s) · {m}m {sec:02d}s"
                               + ("" if paused else f" · {cur}"))

    def _stat(self, lay, title):
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(label(title, muted=True))
        v = label("—")
        v.setStyleSheet("font-weight:700;")
        v.setWordWrap(True)
        col.addWidget(v)
        lay.addLayout(col, 1)
        return v

    def refresh(self):
        ctl = self.ctl
        state = ctl.overall()
        titles = {"safe": "You are safe", "warn": "Your attention is needed",
                  "risk": "Your device is at risk", "idle": "Starting protection…"}
        subs = {"safe": "All protection modules are working. We'll keep watching for threats.",
                "warn": "Some settings reduce your protection. Review the items below.",
                "risk": "Fix the issues below to protect your device.",
                "idle": "Loading threat signatures into the scan engine. This takes up to a minute."}
        self.hero_icon.setPixmap(app_pixmap(state, 104))
        self.hero_title.setText(titles[state])
        col = {"safe": self.c("accent"), "warn": self.c("warn"), "risk": self.c("risk"), "idle": self.c("muted")}[state]
        self.hero_title.setStyleSheet(f"color:{col};")
        self.hero_sub.setText(subs[state])

        while self.issues_box.count():
            w = self.issues_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for iss in ctl.issues():
            f, fl = card(obj="Card2", margins=14, layout="h")
            ic = "#ff6a6a" if iss["level"] == "risk" else "#ffc24b"
            fl.addWidget(IconLabel(LEVEL_ICON[iss["level"]], ic, 22))
            t = QVBoxLayout()
            t.setSpacing(2)
            t.addWidget(label(iss["title"], "H2"))
            t.addWidget(label(iss["desc"], wrap=True, muted=True))
            fl.addLayout(t, 1)
            if iss["action"] == "update" and ctl.updater.running:
                fl.addWidget(label({"paused": "Download paused", "stopping": "Stopping…"}.get(
                    ctl.updater.state, "Downloading…"), muted=True))
            elif iss["action"]:
                fl.addWidget(button(iss["fix"], "Primary",
                                    on_click=lambda a=iss["action"]: self.navigate.emit("action:" + a)))
            self.issues_box.addWidget(f)

        why = ctl.scan_unavailable_reason()
        for k in ("quick", "system", "custom"):
            self.qa[k].set_available(not why, why)
        self.dl_card.setVisible(ctl.updater.running)
        self._scan_progress(None)
        self.update_panel.sync()
        self.qa["update"].set_available(not ctl.updater.running,
                                        "Downloading — use Pause, Resume or Stop above." if ctl.updater.running else "")
        self.qa["update"].action.setText("Download signatures" if not eng.signatures_present() else "Update now")

        vi = ctl.engine.version_info()
        estate = {eng.STATE_READY: "Running", eng.STATE_LOADING: "Loading…", eng.STATE_ERROR: "Error",
                  eng.STATE_NO_SIGNATURES: "Waiting for signatures", eng.STATE_NO_ENGINE: "Not found",
                  eng.STATE_STOPPED: "Stopped"}.get(ctl.engine.state, ctl.engine.state)
        self.ov_engine.setText(f"{vi['engine'] or 'ClamAV'} — {estate}")
        self.ov_sigs.setText(f"Version {vi['db_version']}\n{vi['db_date']}" if vi["db_version"] else "—")
        self.ov_update.setText(fmt_time(ctl.settings.get("update.last_success")))
        self.ov_shield.setText(ctl.shield_state()[1])
        items = ctl.quarantine.items()
        self.ov_quar.setText(f"{len(items)} item(s)")


# ---------------------------------------------------------------- Protection
class ProtectionPage(Page):
    navigate = Signal(str)

    def __init__(self, ctl, theme):
        super().__init__(ctl, None, theme)
        self.stack = QStackedWidget()
        self.lay.addWidget(self.stack)
        # home
        home = QWidget()
        hl = QVBoxLayout(home)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(16)
        hl.addWidget(label("Protection", "PageTitle"))
        grid = QGridLayout()
        grid.setSpacing(14)
        tiles = [("protection", "Antivirus", "Scans, real-time Shield and scan settings.", 1),
                 ("quarantine", "Quarantine", "Isolated threats. Restore or delete them.", 2),
                 ("exceptions", "Exceptions", "Files and folders excluded from scanning.", 3),
                 ("schedule", "Scheduled scans", "Run scans automatically on a schedule.", 4),
                 ("log", "Logs", "Scan reports, scan engine and update logs.", 5)]
        for i, (ic, t, d, idx) in enumerate(tiles):
            tile = Tile(ic, t, d, "Open")
            tile.clicked.connect(lambda x=idx: self.open(x))
            grid.addWidget(tile, i // 3, i % 3)
            grid.setColumnStretch(i % 3, 1)
        hl.addLayout(grid)
        hl.addStretch(1)
        self.stack.addWidget(home)
        self.av = AntivirusPanel(ctl, theme, self)
        self.quar = QuarantinePanel(ctl, theme, self)
        self.exc = ExceptionsPanel(ctl, theme, self)
        self.sched = SchedulePanel(ctl, theme, self)
        self.logs = LogsPanel(ctl, theme, self)
        for w in (self.av, self.quar, self.exc, self.sched, self.logs):
            self.stack.addWidget(w)

    def open(self, idx):
        self.stack.setCurrentIndex(idx)
        w = self.stack.currentWidget()
        if hasattr(w, "refresh"):
            w.refresh()

    def back(self):
        self.stack.setCurrentIndex(0)

    def refresh(self):
        w = self.stack.currentWidget()
        if hasattr(w, "refresh"):
            w.refresh()


class SubPanel(QWidget):
    def __init__(self, ctl, theme, owner, title):
        super().__init__()
        self.ctl, self.theme, self.owner = ctl, theme, owner
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(14)
        back = button("‹  Protection", "Link", on_click=owner.back)
        self.lay.addWidget(back, 0, Qt.AlignLeft)
        self.lay.addWidget(label(title, "PageTitle"))


class AntivirusPanel(SubPanel):
    def __init__(self, ctl, theme, owner):
        super().__init__(ctl, theme, owner, "Antivirus")
        tabs = QTabWidget()
        self.lay.addWidget(tabs)
        # --- Scans
        scans = QWidget()
        sl = QVBoxLayout(scans)
        sl.setContentsMargins(0, 12, 0, 0)
        sl.setSpacing(10)
        self.scan_btns = []
        self.scan_ctrls = {}
        self.scan_state_lbls = {}
        self.scan_reason = label("", wrap=True)
        self.scan_reason.setStyleSheet("color:#ffc24b;")
        sl.addWidget(self.scan_reason)
        for kind, icon, title, desc in [
                ("quick", "quick", "Quick Scan", "Checks running programs, autostart entries, cron jobs, "
                 "Downloads, Desktop and temporary folders."),
                ("system", "system", "System Scan", "Scans all files on the root filesystem and /home. "
                 "Virtual filesystems (/proc, /sys, /dev) are skipped."),
                ("custom", "custom", "Custom Scan", "Pick files or folders to scan. You can also right-click "
                 "files in your file manager (Settings › Integration).")]:
            f, fl = card(obj="Card", layout="h", margins=16)
            fl.addWidget(IconLabel(icon, "#2fd38a", 26))
            t = QVBoxLayout()
            t.addWidget(label(title, "H2"))
            t.addWidget(label(desc, wrap=True, muted=True))
            fl.addLayout(t, 1)
            sc = ScanControls(ctl, kind, "Run scan" if kind != "custom" else "Choose…",
                              on_start=lambda k=kind: owner.navigate.emit("action:" + k))
            self.scan_ctrls[kind] = sc
            fl.addWidget(sc)
            self.scan_state_lbls[kind] = label("", muted=True)
            t.addWidget(self.scan_state_lbls[kind])
            sl.addWidget(f)
        sl.addWidget(label("Saved custom scans", "H2"))
        self.saved = QListWidget()
        self.saved.setMaximumHeight(160)
        self.saved.itemDoubleClicked.connect(self._run_saved)
        sl.addWidget(self.saved)
        row = QHBoxLayout()
        row.addWidget(button("New saved scan…", icon="plus", on_click=self._new_saved))
        self.b_run_saved = button("Run", on_click=lambda: self._run_saved(self.saved.currentItem()))
        self.scan_btns.append(self.b_run_saved)
        row.addWidget(self.b_run_saved)
        row.addWidget(button("Remove", on_click=self._del_saved))
        row.addStretch(1)
        sl.addLayout(row)
        sl.addStretch(1)
        tabs.addTab(scroll(scans), "Scans")

        # --- Shield (real-time)
        sh = QWidget()
        shl = QVBoxLayout(sh)
        shl.setContentsMargins(0, 12, 0, 0)
        f, fl = card()
        self.shield_toggle = Toggle(ctl.settings.get("antivirus.shield_enabled"))
        self.shield_toggle.toggled.connect(self._shield)
        fl.addWidget(SettingRow("Shield", "Real-time protection scans files as soon as they are "
                                "created, downloaded or modified in your protected folders.", self.shield_toggle))
        self.shield_info = label("", muted=True)
        fl.addWidget(self.shield_info)
        shl.addWidget(f)
        f2, fl2 = card()
        fl2.addWidget(label("Protected folders", "H2"))
        self.shield_paths = QListWidget()
        self.shield_paths.setMaximumHeight(170)
        fl2.addWidget(self.shield_paths)
        r = QHBoxLayout()
        r.addWidget(button("Add folder…", icon="plus", on_click=self._add_shield_path))
        r.addWidget(button("Remove", on_click=self._del_shield_path))
        r.addStretch(1)
        fl2.addLayout(r)
        shl.addWidget(f2)
        shl.addStretch(1)
        tabs.addTab(scroll(sh), "Shield")

        # --- Advanced
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 12, 0, 0)
        f3, fl3 = card(spacing=2)
        s = ctl.settings
        self.t_arch = Toggle(s.get("antivirus.scan_archives"))
        self.t_pua = Toggle(s.get("antivirus.detect_pua"))
        self.t_heur = Toggle(s.get("antivirus.heuristic_alerts"))
        self.t_mounts = Toggle(s.get("antivirus.system_scan_other_mounts"))
        self.sp_size = QSpinBox()
        self.sp_size.setRange(5, 4000)
        self.sp_size.setSuffix(" MB")
        self.sp_size.setValue(int(s.get("antivirus.max_file_mb")))
        self.cb_action = QComboBox()
        self.cb_action.addItem("Move to quarantine", "quarantine")
        self.cb_action.addItem("Delete", "delete")
        self.cb_action.addItem("Report only (deny access on Shield)", "report")
        self.cb_action.setCurrentIndex(max(0, self.cb_action.findData(s.get("antivirus.action"))))
        rows = [("Scan archives", "Look for threats inside zip, rar, 7z, tar and other archives.", self.t_arch),
                ("Scan potentially unwanted applications", "Detect adware, hacking tools and other PUAs.", self.t_pua),
                ("Heuristic detection", "Alert on suspicious files that match generic patterns.", self.t_heur),
                ("Ignore files larger than", "Large files are skipped to keep scans fast.", self.sp_size),
                ("Threat actions", "What to do when a threat is found.", self.cb_action),
                ("Include other mounted drives in System Scan", "Also scan internal and external data drives.",
                 self.t_mounts)]
        for i, (t, d, w) in enumerate(rows):
            if i:
                fl3.addWidget(sep())
            fl3.addWidget(SettingRow(t, d, w))
        al.addWidget(f3)
        self.adv_status = label("", wrap=True)
        al.addWidget(self.adv_status)
        al.addWidget(button("Reset to defaults", on_click=self._reset_adv), 0, Qt.AlignLeft)
        al.addStretch(1)
        for w in (self.t_arch, self.t_pua, self.t_heur, self.t_mounts):
            w.toggled.connect(self._save_adv)
        self.sp_size.valueChanged.connect(self._save_adv)
        self.cb_action.currentIndexChanged.connect(self._save_adv)
        tabs.addTab(scroll(adv), "Advanced")

    def refresh(self):
        s = self.ctl.settings
        self.shield_toggle.blockSignals(True)
        self.shield_toggle.setChecked(bool(s.get("antivirus.shield_enabled")))
        self.shield_toggle.blockSignals(False)
        self.shield_paths.clear()
        for p in s.get("antivirus.shield_paths", []):
            self.shield_paths.addItem(QListWidgetItem(svg_icon("folder"), p))
        self.saved.clear()
        for cs in s.get("custom_scans", []):
            it = QListWidgetItem(svg_icon("custom"), f"{cs['name']}  —  {', '.join(cs['paths'])}")
            it.setData(Qt.UserRole, cs)
            self.saved.addItem(it)
        s = self.ctl.settings
        for t, key in ((self.t_arch, "antivirus.scan_archives"), (self.t_pua, "antivirus.detect_pua"),
                       (self.t_heur, "antivirus.heuristic_alerts"), (self.t_mounts, "antivirus.system_scan_other_mounts")):
            if t.isChecked() != bool(s.get(key)):
                t.blockSignals(True)
                t.setChecked(bool(s.get(key)))
                t.blockSignals(False)
        self._adv_status()
        why = self.ctl.scan_unavailable_reason()
        for b in self.scan_btns:
            b.setEnabled(not why)
            b.setToolTip(why)
        running = self.ctl.job is not None and self.ctl.job.running
        self.scan_reason.setText("" if running else why)
        self.scan_reason.setVisible(bool(why) and not running)
        for k, sc in self.scan_ctrls.items():
            sc.sync()
            lbl = self.scan_state_lbls[k]
            if sc.mine():
                j = self.ctl.job
                st = "Paused" if j.paused else "Running"
                lbl.setText(f"{st} — {j.stats.scanned:,} items scanned, {j.stats.infected} threat(s)")
                lbl.setStyleSheet("color:#ffc24b;" if j.paused else "color:#2fd38a;")
            elif running:
                lbl.setText(f"Unavailable while the {self.ctl.job.title} is running.")
                lbl.setStyleSheet("color:#8d97a3;")
            else:
                lbl.setText("")
        lvl, _short, text = self.ctl.shield_state()
        col = {"active": "#2fd38a", "off": "", "waiting": "#ffc24b", "error": "#ff6a6a"}[lvl]
        self.shield_info.setText(text)
        self.shield_info.setWordWrap(True)
        self.shield_info.setStyleSheet(f"color:{col};" if col else "")

    def _shield(self, on):
        self.ctl.set_shield(on)
        self.refresh()

    def _add_shield_path(self):
        d = QFileDialog.getExistingDirectory(self, "Protect folder", str(paths.Path.home()))
        if d:
            lst = self.ctl.settings.get("antivirus.shield_paths", [])
            if d not in lst:
                lst.append(d)
                self.ctl.settings.set("antivirus.shield_paths", lst)
                if self.ctl.shield.active:
                    self.ctl.shield.restart()
            self.refresh()

    def _del_shield_path(self):
        it = self.shield_paths.currentItem()
        if not it:
            return
        lst = [p for p in self.ctl.settings.get("antivirus.shield_paths", []) if p != it.text()]
        self.ctl.settings.set("antivirus.shield_paths", lst)
        if self.ctl.shield.active:
            self.ctl.shield.restart()
        self.refresh()

    def _save_adv(self, *_):
        s = self.ctl.settings
        old = (s.get("antivirus.scan_archives"), s.get("antivirus.detect_pua"),
               s.get("antivirus.heuristic_alerts"), s.get("antivirus.max_file_mb"))
        s.set("antivirus.scan_archives", self.t_arch.isChecked(), save=False)
        s.set("antivirus.detect_pua", self.t_pua.isChecked(), save=False)
        s.set("antivirus.heuristic_alerts", self.t_heur.isChecked(), save=False)
        s.set("antivirus.system_scan_other_mounts", self.t_mounts.isChecked(), save=False)
        s.set("antivirus.max_file_mb", self.sp_size.value(), save=False)
        s.set("antivirus.action", self.cb_action.currentData())
        new = (s.get("antivirus.scan_archives"), s.get("antivirus.detect_pua"),
               s.get("antivirus.heuristic_alerts"), s.get("antivirus.max_file_mb"))
        if old != new and self.ctl.engine.state in (eng.STATE_READY, eng.STATE_ERROR, eng.STATE_LOADING):
            self._pending_restart = True
            if not hasattr(self, "_restart_timer"):
                self._restart_timer = QTimer(self)
                self._restart_timer.setSingleShot(True)
                self._restart_timer.timeout.connect(self._maybe_restart)
            self._restart_timer.start(1500)            # several quick changes → one restart
        self._adv_status()

    def _adv_status(self):
        st = self.ctl.engine.state
        s = self.ctl.settings
        parts = [("archives " + ("on" if s.get("antivirus.scan_archives") else "off")),
                 ("unwanted apps " + ("on" if s.get("antivirus.detect_pua") else "off")),
                 ("heuristics " + ("on" if s.get("antivirus.heuristic_alerts") else "off")),
                 ("other drives " + ("included" if s.get("antivirus.system_scan_other_mounts") else "skipped"))]
        if getattr(self, "_pending_restart", False) or st in (eng.STATE_LOADING, eng.STATE_STOPPED):
            self.adv_status.setText("Applying (" + ", ".join(parts) + "): the scan engine is restarting with the new "
                                    "settings…")
            self.adv_status.setStyleSheet("color:#ffc24b;")
        elif st == eng.STATE_READY:
            self.adv_status.setText("Active: " + ", ".join(parts) + ".")
            self.adv_status.setStyleSheet("color:#2fd38a;")
        else:
            self.adv_status.setText("Saved: " + ", ".join(parts) + ". They apply when the scan engine starts.")
            self.adv_status.setStyleSheet("")

    def _maybe_restart(self):
        if self.ctl.job and self.ctl.job.running:      # apply after the running scan
            self._restart_timer.start(10_000)
            return
        self._pending_restart = False
        self.ctl.engine.restart()

    def _reset_adv(self):
        from linux_defender.config import DEFAULTS
        d = DEFAULTS["antivirus"]
        self.t_arch.setChecked(d["scan_archives"])
        self.t_pua.setChecked(d["detect_pua"])
        self.t_heur.setChecked(d["heuristic_alerts"])
        self.t_mounts.setChecked(d["system_scan_other_mounts"])
        self.sp_size.setValue(d["max_file_mb"])
        self.cb_action.setCurrentIndex(self.cb_action.findData(d["action"]))

    def _new_saved(self):
        dlg = CustomScanDialog(self)
        if dlg.exec() and dlg.paths:
            lst = self.ctl.settings.get("custom_scans", [])
            lst.append({"name": dlg.name.text().strip() or f"Custom scan {len(lst) + 1}", "paths": dlg.paths})
            self.ctl.settings.set("custom_scans", lst)
            self.refresh()

    def _run_saved(self, it):
        if it:
            cs = it.data(Qt.UserRole)
            self.owner.navigate.emit("scan:" + "\0".join(cs["paths"]))

    def _del_saved(self):
        it = self.saved.currentItem()
        if it:
            cs = it.data(Qt.UserRole)
            self.ctl.settings.set("custom_scans", [x for x in self.ctl.settings.get("custom_scans", []) if x != cs])
            self.refresh()


class CustomScanDialog:
    """Small modal to pick targets for a custom scan."""

    def __init__(self, parent):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        self._dlg = QDialog(parent)
        self._dlg.setWindowTitle("Custom Scan")
        self._dlg.resize(560, 380)
        lay = QVBoxLayout(self._dlg)
        lay.addWidget(label("Scan name", muted=True))
        self.name = QLineEdit()
        self.name.setPlaceholderText("My custom scan")
        lay.addWidget(self.name)
        lay.addWidget(label("Locations to scan", muted=True))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        r = QHBoxLayout()
        r.addWidget(button("Add folder…", icon="folder", on_click=self._add_dir))
        r.addWidget(button("Add files…", icon="file", on_click=self._add_files))
        r.addWidget(button("Remove", on_click=lambda: self.list.takeItem(self.list.currentRow())))
        r.addStretch(1)
        lay.addLayout(r)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._dlg.accept)
        bb.rejected.connect(self._dlg.reject)
        lay.addWidget(bb)
        self.paths = []

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self._dlg, "Choose folder", str(paths.Path.home()))
        if d:
            self.list.addItem(d)

    def _add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self._dlg, "Choose files", str(paths.Path.home()))
        for f in fs:
            self.list.addItem(f)

    def exec(self):
        r = self._dlg.exec()
        self.paths = [self.list.item(i).text() for i in range(self.list.count())]
        return r


class QuarantinePanel(SubPanel):
    RESCAN_TEXT = {"clean": "No longer detected", "threat": "Still detected", "skipped": "Not rescanned",
                   "error": "Rescan failed"}

    def __init__(self, ctl, theme, owner):
        super().__init__(ctl, theme, owner, "Quarantine")
        self.lay.addWidget(label("Threats that could not be safely left in place are kept here, encrypted, "
                                 "so they can't run. Restored files are automatically added to Exceptions.",
                                 wrap=True, muted=True))
        self.tabs = QTabWidget()
        self.lay.addWidget(self.tabs, 1)

        # ---- Items tab
        items = QWidget()
        il = QVBoxLayout(items)
        il.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by threat name or location…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        self.count_lbl = label("", muted=True)
        top.addWidget(self.count_lbl)
        il.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Threat", "Original location", "Quarantined", "Size", "Last rescan"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(3, Qt.DescendingOrder)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        _checkbox_column(self.tree)
        self.tree.setMinimumHeight(280)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.tree.itemChanged.connect(self._check_changed)
        self._syncing = False
        il.addWidget(self.tree, 1)
        sr = QHBoxLayout()
        self.b_all = button("Select all", icon="check", on_click=self._select_all)
        self.b_none = button("Select none", on_click=self._select_none)
        sr.addWidget(self.b_all)
        sr.addWidget(self.b_none)
        self.sel_lbl = label("", muted=True)
        sr.addWidget(self.sel_lbl)
        sr.addStretch(1)
        il.addLayout(sr)
        r = QHBoxLayout()
        self.b_restore = button("Restore selected", icon="restore", on_click=self._restore)
        self.b_restore_to = button("Restore selected to…", icon="folder", on_click=lambda: self._restore(choose=True))
        self.b_delete = button("Delete selected", "Danger", icon="trash", color="#ff6a6a", on_click=self._delete)
        for b_ in (self.b_restore, self.b_restore_to, self.b_delete):
            r.addWidget(b_)
        r.addStretch(1)
        self.b_rescan = button("Rescan all", icon="update", on_click=self._rescan)
        r.addWidget(self.b_rescan)
        il.addLayout(r)
        self.rescan_lbl = label("", wrap=True)
        il.addWidget(self.rescan_lbl)
        self.action_lbl = label("", wrap=True)
        il.addWidget(self.action_lbl)
        self.tabs.addTab(items, "Items")

        # ---- Quarantine folder tab
        fw = QWidget()
        fl_ = QVBoxLayout(fw)
        fl_.setContentsMargins(0, 12, 0, 0)
        loc, ll = card(spacing=8)
        ll.addWidget(label("Quarantine folder", "H2"))
        self.loc_lbl = label("", wrap=True)
        self.loc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.loc_lbl.setStyleSheet("font-family: monospace;")
        ll.addWidget(self.loc_lbl)
        self.loc_kind = label("", muted=True)
        ll.addWidget(self.loc_kind)
        usage = QGridLayout()
        usage.setHorizontalSpacing(28)
        self.u_items, self.u_used, self.u_free, self.u_oldest = (label("—") for _ in range(4))
        for i, (t, w) in enumerate((("Items", self.u_items), ("Space used", self.u_used),
                                    ("Free space on that drive", self.u_free), ("Oldest item", self.u_oldest))):
            usage.addWidget(label(t, muted=True), 0, i)
            w.setStyleSheet("font-weight:700;")
            usage.addWidget(w, 1, i)
        ll.addLayout(usage)
        br = QHBoxLayout()
        br.addWidget(button("Open folder", icon="folder", on_click=self._open_folder))
        br.addWidget(button("Change location…", icon="external", on_click=self._change_location))
        self.b_default = button("Use default location", on_click=lambda: self._move(None))
        br.addWidget(self.b_default)
        br.addStretch(1)
        ll.addLayout(br)
        self.move_lbl = label("", wrap=True)
        ll.addWidget(self.move_lbl)
        fl_.addWidget(loc)

        lim, ml = card(spacing=2)
        ml.addWidget(label("Limits and maintenance", "H2"))
        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setSuffix(" days")
        self.days.setSpecialValueText("never")
        self.days.setValue(int(ctl.settings.get("quarantine.auto_delete_days", 30)))
        self.days.valueChanged.connect(self._limits_changed)
        self.maxmb = QSpinBox()
        self.maxmb.setRange(0, 1_000_000)
        self.maxmb.setSingleStep(100)
        self.maxmb.setSuffix(" MB")
        self.maxmb.setSpecialValueText("no limit")
        self.maxmb.setValue(int(ctl.settings.get("quarantine.max_size_mb", 0)))
        self.maxmb.valueChanged.connect(self._limits_changed)
        for sb in (self.days, self.maxmb):
            sb.setMinimumWidth(130)
        self.t_rescan = Toggle(ctl.settings.get("quarantine.rescan_after_update"))
        self.t_rescan.toggled.connect(self._rescan_toggled)
        for i, (t, d, w) in enumerate((
                ("Delete items older than", "Old items are removed automatically.", self.days),
                ("Maximum quarantine size", "When the limit is reached, the oldest items are deleted. "
                 "A newly quarantined item is always kept.", self.maxmb),
                ("Rescan quarantine after signature updates", "Finds items that are no longer detected "
                 "(false positives) so you can restore them.", self.t_rescan))):
            if i:
                ml.addWidget(sep())
            ml.addWidget(SettingRow(t, d, w))
        self.limits_lbl = label("", wrap=True)
        ml.addWidget(self.limits_lbl)
        fl_.addWidget(lim)
        er = QHBoxLayout()
        self.b_empty = button("Empty quarantine…", "Danger", icon="trash", color="#ff6a6a", on_click=self._empty)
        er.addWidget(self.b_empty)
        er.addStretch(1)
        fl_.addLayout(er)
        fl_.addStretch(1)
        self.tabs.addTab(scroll(fw), "Quarantine folder")

        ctl.quarantineChanged.connect(self.refresh)
        ctl.quarantineRescan.connect(self._rescan_progress)

    # ---- items
    def refresh(self):
        sel_ids = {m["id"] for m in self._selected()}
        self._syncing = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for m in self.ctl.quarantine.items():
            rs = m.get("rescan") or {}
            status = self.RESCAN_TEXT.get(rs.get("result"), "—")
            if rs.get("result") == "threat" and rs.get("detail") and rs["detail"] != m["threat"]:
                status += f" ({rs['detail']})"
            if rs.get("ts"):
                status += f" · {fmt_time(rs['ts'])}"
            it = SortItem(["", m["threat"], m["path"], fmt_time(m["added"]), fmt_size(m.get("size", 0)), status])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
            it.setData(0, Qt.UserRole, m)
            it.setData(3, Qt.UserRole + 1, m["added"])
            it.setData(4, Qt.UserRole + 1, m.get("size", 0))
            it.setIcon(1, svg_icon("critical", "#ff6a6a"))
            if rs.get("result") == "clean":
                it.setIcon(5, svg_icon("check", "#2fd38a"))
                it.setToolTip(5, "No longer detected with the current signatures, probably a false positive. "
                                 "You can restore it.")
            self.tree.addTopLevelItem(it)
            if m["id"] in sel_ids:
                it.setCheckState(0, Qt.Checked)
        self.tree.setSortingEnabled(True)
        self._syncing = False
        for i in (1, 3, 4, 5):
            self.tree.resizeColumnToContents(i)
        self._filter(self.search.text())
        self._refresh_folder()

    def _filter(self, text):
        t = text.strip().lower()
        shown = 0
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            hide = bool(t) and t not in it.text(1).lower() and t not in it.text(2).lower()
            it.setHidden(hide)
            if hide and (it.isSelected() or it.checkState(0) == Qt.Checked):
                it.setSelected(False)
                it.setCheckState(0, Qt.Unchecked)
            shown += not hide
        total = self.tree.topLevelItemCount()
        self.count_lbl.setText(f"{shown} of {total} item(s)" if t else f"{total} item(s)")
        self._sel_changed()

    # selection: row highlight and checkbox are kept identical; hidden (filtered) rows are never selected
    def _check_changed(self, it, col):
        if self._syncing or col != 0:
            return
        self._sel_changed()

    def _select_all(self):
        self._syncing = True
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setCheckState(0, Qt.Unchecked if it.isHidden() else Qt.Checked)
        self._syncing = False
        self._sel_changed()

    def _select_none(self):
        self._syncing = True
        self.tree.clearSelection()
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
        self._syncing = False
        self._sel_changed()

    def _sel_changed(self):
        # Ctrl/Shift-click on several rows ticks exactly those rows; a plain click only opens a row
        # for viewing and keeps the ticks.
        highlighted = [it for it in self.tree.selectedItems() if not it.isHidden()]
        if not self._syncing and len(highlighted) > 1:
            self._syncing = True
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                want = Qt.Checked if (it.isSelected() and not it.isHidden()) else Qt.Unchecked
                if it.checkState(0) != want:
                    it.setCheckState(0, want)
            self._syncing = False
        n = len(self._selected())
        visible = sum(1 for i in range(self.tree.topLevelItemCount()) if not self.tree.topLevelItem(i).isHidden())
        self.sel_lbl.setText(f"{n} of {visible} selected" if visible else "")
        for b_ in (self.b_restore, self.b_restore_to, self.b_delete, self.b_none):
            b_.setEnabled(n > 0)
        self.b_all.setEnabled(visible > 0 and n < visible)
        self.b_restore.setText(f"Restore selected ({n})" if n else "Restore selected")
        self.b_delete.setText(f"Delete selected ({n})" if n else "Delete selected")
        busy = self.ctl._rescanning
        self.b_rescan.setEnabled(self.tree.topLevelItemCount() > 0 and self.ctl.engine.ready and not busy)
        if not busy:
            if not self.ctl.engine.ready and self.tree.topLevelItemCount():
                self.rescan_lbl.setText("Rescan is available when the scan engine is running.")
                self.rescan_lbl.setStyleSheet("color:#8d97a3;")
            elif not self.rescan_lbl.text().startswith("Rescan finished"):
                self.rescan_lbl.setText("")

    def _selected(self):
        """The ticked rows (hidden rows never count)."""
        return [self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).checkState(0) == Qt.Checked and not self.tree.topLevelItem(i).isHidden()]

    def _restore(self, choose=False):
        import time as _t
        sel = self._selected()
        if not sel:
            return
        dest_dir = None
        if choose:
            if len(sel) == 1:
                dest, _ = QFileDialog.getSaveFileName(self, "Restore to", sel[0]["path"])
                if not dest:
                    return
                targets = {sel[0]["id"]: dest}
            else:
                dest_dir = QFileDialog.getExistingDirectory(self, f"Restore {len(sel)} items to folder",
                                                            str(paths.Path.home()))
                if not dest_dir:
                    return
                targets = {m["id"]: os.path.join(dest_dir, os.path.basename(m["path"])) for m in sel}
        else:
            targets = {m["id"]: m["path"] for m in sel}
        where = "their original locations" if not choose else (dest_dir or targets[sel[0]["id"]])
        if QMessageBox.question(self, "Restore", f"Restore {len(sel)} item(s) to {where}?\n\nThey may be harmful "
                                "and will be excluded from future scans.") != QMessageBox.Yes:
            return
        conflicts = [m for m in sel if os.path.exists(targets[m["id"]])]
        policy = "replace"
        if conflicts:
            box = QMessageBox(QMessageBox.Question, "Files already exist",
                              f"{len(conflicts)} of the files already exist at the destination.", parent=self)
            b_rep = box.addButton("Replace", QMessageBox.AcceptRole)
            b_keep = box.addButton("Keep both", QMessageBox.AcceptRole)
            box.addButton("Skip those", QMessageBox.RejectRole)
            box.setDefaultButton(b_keep)
            box.exec()
            clicked = box.clickedButton()
            policy = "replace" if clicked is b_rep else "keep" if clicked is b_keep else "skip"
        ok, failed, skipped = [], [], 0
        ex = self.ctl.settings.get("exceptions", [])
        for m in sel:
            dest = targets[m["id"]]
            overwrite = False
            if os.path.exists(dest):
                if policy == "skip":
                    skipped += 1
                    continue
                if policy == "keep":
                    dest = _unique_path(dest)
                else:
                    overwrite = True
            try:
                out = self.ctl.quarantine.restore(m["id"], dest, overwrite=overwrite)
            except OSError as e:
                failed.append(f"{os.path.basename(m['path'])}: {e.strerror or e}")
                continue
            ok.append(out)
            ex.append({"path": out, "added": _t.time()})
            self.ctl.events.add("info", "Quarantine", "Item restored", f"{m['threat']}\n{out}")
        self.ctl.settings.set("exceptions", ex)
        msg = f"Restored {len(ok)} item(s)."
        if skipped:
            msg += f" Skipped {skipped}."
        if failed:
            msg += f" {len(failed)} failed: " + "; ".join(failed[:3]) + (" …" if len(failed) > 3 else "")
        self.action_lbl.setText(msg)
        self.action_lbl.setStyleSheet("color:#ff6a6a;" if failed else "color:#2fd38a;")
        self.refresh()
        self.ctl.quarantineChanged.emit()

    def _delete(self):
        sel = self._selected()
        if sel and QMessageBox.question(self, "Delete", f"{len(sel)} item(s) will be removed forever.") == QMessageBox.Yes:
            for m in sel:
                self.ctl.quarantine.delete(m["id"])
            self.action_lbl.setText(f"Deleted {len(sel)} item(s).")
            self.action_lbl.setStyleSheet("color:#2fd38a;")
            self.refresh()
            self.ctl.quarantineChanged.emit()

    def _rescan(self):
        if self.ctl.rescan_quarantine():
            self.rescan_lbl.setText("Rescanning…")
            self.rescan_lbl.setStyleSheet("")
            self.b_rescan.setEnabled(False)

    def _rescan_progress(self, done, total):
        if total:
            self.rescan_lbl.setText(f"Rescanning… {done} of {total}")
            self.rescan_lbl.setStyleSheet("")
            self.b_rescan.setEnabled(False)
            return
        items = self.ctl.quarantine.items()
        clean = sum(1 for m in items if (m.get("rescan") or {}).get("result") == "clean")
        self.rescan_lbl.setText(f"Rescan finished: {done} item(s) checked, {clean} no longer detected."
                                + (" Select them and click Restore if you trust them." if clean else ""))
        self.rescan_lbl.setStyleSheet("color:#ffc24b;" if clean else "color:#2fd38a;")
        self.refresh()

    # ---- folder
    def _refresh_folder(self):
        q = self.ctl.quarantine
        u = q.disk_usage()
        self.loc_lbl.setText(str(q.root))
        default = q.root.resolve() == paths.QUARANTINE_DIR.resolve()
        self.loc_kind.setText("Default location" if default else "Custom location")
        self.b_default.setEnabled(not default)
        self.u_items.setText(str(u["items"]))
        self.u_used.setText(fmt_size(u["used"]))
        self.u_free.setText(fmt_size(u["free"]) if u["disk_total"] else "—")
        self.u_oldest.setText(fmt_time(u["oldest"]) if u["oldest"] else "—")
        self.b_empty.setEnabled(u["items"] > 0)
        days, mb = self.days.value(), self.maxmb.value()
        parts = ["items are kept until you delete them" if not days else f"items older than {days} days are deleted",
                 "no size limit" if not mb else f"the oldest items are deleted above {mb} MB"]
        if mb and u["used"] > (mb << 20):
            parts.append("currently over the limit")
        self.limits_lbl.setText("Now: " + "; ".join(parts) + ".")
        self.limits_lbl.setStyleSheet("color:#ffc24b;" if mb and u["used"] > (mb << 20) else "color:#8d97a3;")

    def _limits_changed(self, *_):
        s = self.ctl.settings
        s.set("quarantine.auto_delete_days", self.days.value(), save=False)
        s.set("quarantine.max_size_mb", self.maxmb.value())
        if not hasattr(self, "_limit_timer"):
            self._limit_timer = QTimer(self)
            self._limit_timer.setSingleShot(True)
            self._limit_timer.timeout.connect(self._apply_limits)
        self._limit_timer.start(1200)            # apply after the user stops typing
        self._refresh_folder()

    def _apply_limits(self):
        n = self.ctl.apply_quarantine_limits()
        if n:
            self.move_lbl.setText(f"{n} item(s) removed to respect the new limits.")
            self.move_lbl.setStyleSheet("color:#ffc24b;")
        self.refresh()

    def _rescan_toggled(self, v):
        self.ctl.settings.set("quarantine.rescan_after_update", v)

    def _open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctl.quarantine.root)))

    def _change_location(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for the quarantine", str(paths.Path.home()))
        if d:
            self._move(d)

    def _move(self, chosen):
        from linux_defender.quarantine import resolve_location
        target = paths.QUARANTINE_DIR if not chosen else resolve_location(chosen)
        n = len(self.ctl.quarantine.items())
        if QMessageBox.question(self, "Move quarantine",
                                f"Move the quarantine to:\n{target}\n\n{n} item(s) will be moved. Items are copied "
                                "and checked before the originals are removed.") != QMessageBox.Yes:
            return
        from PySide6.QtWidgets import QProgressDialog, QApplication
        dlg = QProgressDialog("Moving quarantined items…", None, 0, max(n, 1), self)
        dlg.setWindowTitle("Move quarantine")
        dlg.setMinimumDuration(400)
        dlg.setValue(0)

        def prog(i, total):
            dlg.setValue(i)
            QApplication.processEvents()
        try:
            new = self.ctl.move_quarantine(chosen, prog)
            self.move_lbl.setText(f"Moved {n} item(s) to {new}.")
            self.move_lbl.setStyleSheet("color:#2fd38a;")
        except (OSError, ValueError) as e:
            self.move_lbl.setText(f"The quarantine was not moved: {e}")
            self.move_lbl.setStyleSheet("color:#ff6a6a;")
        finally:
            dlg.close()
        self.refresh()

    def _empty(self):
        n = len(self.ctl.quarantine.items())
        if n and QMessageBox.question(self, "Empty quarantine",
                                      f"Delete all {n} quarantined item(s) permanently? They can't be restored "
                                      "afterwards.") == QMessageBox.Yes:
            self.ctl.empty_quarantine()
            self.move_lbl.setText(f"Quarantine emptied: {n} item(s) deleted.")
            self.move_lbl.setStyleSheet("color:#2fd38a;")
            self.refresh()


def _checkbox_column(tree):
    """Column 0 holds only the selection checkbox, so it never covers any text."""
    h = tree.header()
    h.setSectionResizeMode(0, QHeaderView.Fixed)
    h.setMinimumSectionSize(24)
    tree.setColumnWidth(0, 36)
    tree.setIndentation(0)


def _unique_path(p: str) -> str:
    """'name (1).ext', 'name (2).ext', … for a path that already exists."""
    base, ext = os.path.splitext(p)
    i = 1
    while os.path.exists(f"{base} ({i}){ext}"):
        i += 1
    return f"{base} ({i}){ext}"


class SortItem(QTreeWidgetItem):
    """Sorts dates and sizes by their real values instead of their text."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(col, Qt.UserRole + 1), other.data(col, Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return self.text(col).lower() < other.text(col).lower()


class ExceptionsPanel(SubPanel):
    def __init__(self, ctl, theme, owner):
        super().__init__(ctl, theme, owner, "Exceptions")
        self.lay.addWidget(label("Files and folders listed here are skipped by on-demand scans and by the Shield. "
                                 "Only add items you trust.", wrap=True, muted=True))
        self.list = QListWidget()
        self.list.setMinimumHeight(280)
        self.lay.addWidget(self.list, 1)
        r = QHBoxLayout()
        r.addWidget(button("Add folder…", icon="folder", on_click=self._add_dir))
        r.addWidget(button("Add file…", icon="file", on_click=self._add_file))
        r.addWidget(button("Remove", "Danger", on_click=self._remove))
        r.addStretch(1)
        self.lay.addLayout(r)

    def refresh(self):
        self.list.clear()
        for e in self.ctl.settings.get("exceptions", []):
            it = QListWidgetItem(svg_icon("folder" if os.path.isdir(e["path"]) else "file"),
                                 f"{e['path']}    (added {fmt_time(e.get('added'))})")
            it.setData(Qt.UserRole, e["path"])
            self.list.addItem(it)

    def _add(self, p):
        if p:
            ex = self.ctl.settings.get("exceptions", [])
            if p not in [e["path"] for e in ex]:
                ex.append({"path": p, "added": time.time()})
                self.ctl.settings.set("exceptions", ex)
            self.refresh()

    def _add_dir(self):
        self._add(QFileDialog.getExistingDirectory(self, "Exclude folder", str(paths.Path.home())))

    def _add_file(self):
        self._add(QFileDialog.getOpenFileName(self, "Exclude file", str(paths.Path.home()))[0])

    def _remove(self):
        it = self.list.currentItem()
        if it:
            p = it.data(Qt.UserRole)
            self.ctl.settings.set("exceptions", [e for e in self.ctl.settings.get("exceptions", []) if e["path"] != p])
            self.refresh()


class SchedulePanel(SubPanel):
    def __init__(self, ctl, theme, owner):
        super().__init__(ctl, theme, owner, "Scheduled scans")
        f, fl = card(spacing=2)
        s = ctl.settings
        self.t_en = Toggle(s.get("schedule.enabled"))
        self.cb_type = QComboBox()
        self.cb_type.addItem("Quick Scan", "quick")
        self.cb_type.addItem("System Scan", "system")
        self.cb_freq = QComboBox()
        self.cb_freq.addItem("Every day", "daily")
        self.cb_freq.addItem("Every week", "weekly")
        self.cb_day = QComboBox()
        for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]):
            self.cb_day.addItem(d, i)
        self.te = QTimeEdit()
        self.te.setDisplayFormat("HH:mm")
        rows = [("Run scheduled scan", "Linux Defender must be running (it can stay in the system tray).", self.t_en),
                ("Scan type", "", self.cb_type), ("Frequency", "", self.cb_freq), ("Day", "", self.cb_day),
                ("Time", "If the computer is off at that time, the scan runs at the next start.", self.te)]
        for i, (t, d, w) in enumerate(rows):
            if i:
                fl.addWidget(sep())
            fl.addWidget(SettingRow(t, d, w))
        self.lay.addWidget(f)
        self.status = label("", wrap=True)
        self.lay.addWidget(self.status)
        # live status of the scheduled scan: running / paused / waiting / skipped
        st, stl = card(obj="Card2", margins=16, spacing=8)
        stl.addWidget(label("Scheduled scan status", "H2"))
        self.run_lbl = label("", wrap=True)
        stl.addWidget(self.run_lbl)
        srow = QHBoxLayout()
        self.sched_controls = ScanControls(ctl, "scheduled")
        srow.addWidget(self.sched_controls)
        self.b_skip = button("Skip next scan", icon="exceptions", on_click=self._skip)
        self.b_unskip = button("Undo skip", icon="restore", on_click=ctl.undo_skip_scheduled)
        srow.addWidget(self.b_skip)
        srow.addWidget(self.b_unskip)
        srow.addStretch(1)
        stl.addLayout(srow)
        self.lay.addWidget(st)
        self.last = label("", muted=True)
        self.lay.addWidget(self.last)
        self.lay.addStretch(1)
        ctl.statusChanged.connect(self._update_run_state)
        ctl.scanState.connect(lambda *_: self._update_run_state())
        ctl.scanProgress.connect(lambda *_: self._update_run_state() if self.isVisible() else None)
        self._tick = QTimer(self)
        self._tick.setInterval(15000)
        self._tick.timeout.connect(self._update_run_state)
        self._tick.start()
        self.t_en.toggled.connect(self._save)
        for w in (self.cb_type, self.cb_freq, self.cb_day):
            w.currentIndexChanged.connect(self._save)
        self.te.timeChanged.connect(self._save)
        self._loading = False

    def refresh(self):
        self._loading = True
        s = self.ctl.settings
        self.t_en.setChecked(bool(s.get("schedule.enabled")))
        self.cb_type.setCurrentIndex(self.cb_type.findData(s.get("schedule.type")))
        self.cb_freq.setCurrentIndex(self.cb_freq.findData(s.get("schedule.frequency")))
        self.cb_day.setCurrentIndex(int(s.get("schedule.weekday", 6)))
        hh, mm = (int(x) for x in s.get("schedule.time", "12:00").split(":"))
        self.te.setTime(QTime(hh, mm))
        self.last.setText(f"Last scheduled scan: {fmt_time(s.get('schedule.last_ran', 0))}")
        self._loading = False
        self._update_status()
        self._update_run_state()

    def _skip(self):
        st = self.ctl.scheduled_state()
        when = st.get("when")
        what = "this waiting scheduled scan" if st["state"] == "waiting" else \
            f"the scheduled scan of {when.strftime('%A %d %b, %H:%M')}" if when else "the next scheduled scan"
        if QMessageBox.question(self, "Skip scheduled scan", f"Skip {what}? The schedule stays on.") == QMessageBox.Yes:
            self.ctl.skip_next_scheduled()

    def _update_run_state(self):
        st = self.ctl.scheduled_state()
        s_ = st["state"]
        self.sched_controls.sync()
        self.b_skip.setVisible(s_ in ("scheduled", "waiting"))
        self.b_skip.setText("Skip this run" if s_ == "waiting" else "Skip next scan")
        self.b_unskip.setVisible(s_ in ("skipped", "skipped_due"))
        fmt = lambda d: d.strftime("%A %d %b %Y, %H:%M") if d else "—"
        css = ""
        if s_ in ("running", "paused"):
            j = st["job"]
            txt = (f"{j.title} is {'paused' if s_ == 'paused' else 'running'}: {j.stats.scanned:,} items scanned, "
                   f"{j.stats.infected} threat(s). Use Stop to end it; it will not run again until the next "
                   "scheduled time.")
            css = "color:#ffc24b;" if s_ == "paused" else "color:#2fd38a;"
        elif s_ == "off":
            txt = "Scheduled scans are turned off."
        elif s_ == "waiting":
            txt = f"The scan scheduled for {fmt(st['when'])} is waiting for {st['why']}."
            css = "color:#ffc24b;"
        elif s_ == "skipped":
            txt = f"The scan of {fmt(st['when'])} will be skipped. Following scan: {fmt(st.get('next'))}."
            css = "color:#ffc24b;"
        elif s_ == "skipped_due":
            txt = f"The scan of {fmt(st['when'])} was skipped."
        else:
            txt = f"Nothing running. Next scheduled scan: {fmt(st.get('when'))}."
        self.run_lbl.setText(txt)
        self.run_lbl.setStyleSheet(css)
        self.last.setText(f"Last scheduled scan: {fmt_time(self.ctl.settings.get('schedule.last_ran', 0))}")

    def _update_status(self):
        on = self.t_en.isChecked()
        for w in (self.cb_type, self.cb_freq, self.te):
            w.setEnabled(on)
        self.cb_day.setEnabled(on and self.cb_freq.currentData() == "weekly")
        nxt = self.ctl.next_scheduled_run()
        if not on:
            self.status.setText("Scheduled scans are turned off.")
            self.status.setStyleSheet("")
        elif nxt:
            kind = self.cb_type.currentText()
            self.status.setText(f"Next {kind}: {nxt.strftime('%A %d %b %Y, %H:%M')}")
            self.status.setStyleSheet("color:#2fd38a;")
        else:
            self.status.setText("")

    def _save(self, *_):
        if self._loading:
            return
        s = self.ctl.settings
        s.set("schedule.enabled", self.t_en.isChecked(), save=False)
        s.set("schedule.type", self.cb_type.currentData(), save=False)
        s.set("schedule.frequency", self.cb_freq.currentData(), save=False)
        s.set("schedule.weekday", self.cb_day.currentData(), save=False)
        s.set("schedule.time", self.te.time().toString("HH:mm"), save=False)
        s.set("schedule.skip_ts", 0, save=False)          # a changed schedule forgets an old skip
        # count from now, so turning the schedule on (or changing it) never starts a scan immediately
        s.set("schedule.last_run", time.time())
        self._update_status()
        self._update_run_state()


class LogsPanel(SubPanel):
    """Scan reports + scan-engine and update logs: view, filter, multi-select, move, delete, retention."""
    TYPES = (("all", "All logs"), ("scan", "Scan reports"), ("engine", "Scan engine logs"), ("update", "Update logs"))

    def __init__(self, ctl, theme, owner):
        super().__init__(ctl, theme, owner, "Logs")
        self.tabs = QTabWidget()
        self.lay.addWidget(self.tabs, 1)
        # ---- Logs tab
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        self.type_cb = QComboBox()
        for k, t in self.TYPES:
            self.type_cb.addItem(t, k)
        self.type_cb.currentIndexChanged.connect(lambda _: self._filter())
        top.addWidget(self.type_cb)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search in type, details or file name…")
        self.search.textChanged.connect(lambda _: self._filter())
        top.addWidget(self.search, 1)
        self.count_lbl = label("", muted=True)
        top.addWidget(self.count_lbl)
        l.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["", "Date", "Type", "Details", "Size", "File"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.DescendingOrder)
        self.tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        _checkbox_column(self.tree)
        self.tree.setMinimumHeight(220)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.tree.itemChanged.connect(self._check_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._show())
        self._syncing = False
        l.addWidget(self.tree, 1)
        sr = QHBoxLayout()
        self.b_all = button("Select all", icon="check", on_click=self._select_all)
        self.b_none = button("Select none", on_click=self._select_none)
        sr.addWidget(self.b_all)
        sr.addWidget(self.b_none)
        self.sel_lbl = label("", muted=True)
        sr.addWidget(self.sel_lbl)
        sr.addStretch(1)
        self.b_move = button("Move selected to folder…", icon="folder", on_click=self._move)
        self.b_delete = button("Delete selected", "Danger", icon="trash", color="#ff6a6a", on_click=self._delete)
        sr.addWidget(self.b_move)
        sr.addWidget(self.b_delete)
        l.addLayout(sr)
        self.action_lbl = label("", wrap=True)
        l.addWidget(self.action_lbl)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(170)
        self.detail.setStyleSheet("font-family: monospace; font-size: 9pt;")
        l.addWidget(self.detail, 1)
        self.tabs.addTab(w, "Logs")

        # ---- Settings tab
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(0, 12, 0, 0)
        f, fl = card(spacing=8)
        fl.addWidget(label("Logs folder", "H2"))
        self.loc_lbl = label(str(paths.LOG_DIR), wrap=True)
        self.loc_lbl.setStyleSheet("font-family: monospace;")
        self.loc_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fl.addWidget(self.loc_lbl)
        self.usage_lbl = label("", muted=True)
        fl.addWidget(self.usage_lbl)
        br = QHBoxLayout()
        br.addWidget(button("Open logs folder", icon="folder",
                            on_click=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.LOG_DIR)))))
        br.addStretch(1)
        fl.addLayout(br)
        sl.addWidget(f)
        r, rl = card(spacing=2)
        rl.addWidget(label("Log retention", "H2"))
        s = ctl.settings
        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setSuffix(" days")
        self.days.setSpecialValueText("never")
        self.days.setMinimumWidth(130)
        self.days.setValue(int(s.get("logs.max_age_days", 90)))
        self.maxn = QSpinBox()
        self.maxn.setRange(0, 100000)
        self.maxn.setSingleStep(50)
        self.maxn.setSpecialValueText("no limit")
        self.maxn.setSuffix(" reports")
        self.maxn.setMinimumWidth(130)
        self.maxn.setValue(int(s.get("logs.max_scan_logs", 500)))
        for i, (t, d, w_) in enumerate((
                ("Delete logs older than", "Scan reports and archived engine/update logs.", self.days),
                ("Keep at most", "The oldest scan reports are deleted first.", self.maxn))):
            if i:
                rl.addWidget(sep())
            rl.addWidget(SettingRow(t, d, w_))
        self.ret_lbl = label("", wrap=True)
        rl.addWidget(self.ret_lbl)
        sl.addWidget(r)
        er = QHBoxLayout()
        self.b_clear = button("Delete all logs…", "Danger", icon="trash", color="#ff6a6a", on_click=self._delete_all)
        er.addWidget(self.b_clear)
        er.addStretch(1)
        sl.addLayout(er)
        sl.addWidget(label("Scan engine and update logs that are in use are emptied instead of deleted, so logging "
                           "continues in the same file.", wrap=True, muted=True))
        sl.addStretch(1)
        self.days.valueChanged.connect(self._retention_changed)
        self.maxn.valueChanged.connect(self._retention_changed)
        self.tabs.addTab(scroll(sw), "Settings")
        # keep the running scan's report (locked) up to date on screen, and unlock it when the scan ends
        self._live = QTimer(self)
        self._live.setInterval(2000)
        self._live.timeout.connect(self._live_refresh)
        self._live.start()
        ctl.scanState.connect(lambda *_: QTimer.singleShot(300, self._live_refresh_force))

    def _live_refresh(self):
        if self.isVisible() and self.ctl.job is not None and self.ctl.job.running:
            self.refresh()

    def _live_refresh_force(self):
        if self.isVisible():
            self.refresh()

    # ---- list
    def refresh(self):
        from linux_defender import logs as L
        cur = self.tree.currentItem()
        cur_path = str(cur.data(0, Qt.UserRole).path) if cur else None
        sel = {str(e.path) for e in self._selected()}
        self._syncing = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        icons = {"scan": ("log", "#2fd38a"), "engine": ("system", "#4c9dff"), "update": ("update", "#4c9dff")}
        self._entries = L.list_logs()
        for e in self._entries:
            it = SortItem(["", fmt_time(e.ts), e.title, e.summary, fmt_size(e.size), e.path.name])
            it.setCheckState(0, Qt.Unchecked)
            if e.locked:                                   # a running/paused scan's report: not selectable
                it.setFlags(it.flags() & ~Qt.ItemIsUserCheckable)
                it.setData(0, Qt.CheckStateRole, None)
                it.setIcon(0, svg_icon("quarantine", "#ffc24b"))
                for c in range(6):
                    it.setToolTip(c, "In use by the running scan. It is unlocked when the scan finishes.")
            else:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setData(0, Qt.UserRole, e)
            it.setData(1, Qt.UserRole + 1, e.ts)
            it.setData(4, Qt.UserRole + 1, e.size)
            ic, col = icons[e.kind]
            it.setIcon(2, svg_icon(ic, col))
            if e.kind == "scan" and e.data.get("infected"):
                it.setIcon(2, svg_icon("critical", "#ff6a6a"))
            self.tree.addTopLevelItem(it)
            if str(e.path) in sel and not e.locked:
                it.setCheckState(0, Qt.Checked)
            if str(e.path) == cur_path:
                self.tree.setCurrentItem(it)
        self.tree.setSortingEnabled(True)
        self._syncing = False
        for i in (1, 2, 4, 5):
            self.tree.resizeColumnToContents(i)
        self._filter()
        self._settings_status()

    def _filter(self):
        kind = self.type_cb.currentData()
        t = self.search.text().strip().lower()
        shown = 0
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            e = it.data(0, Qt.UserRole)
            hide = (kind != "all" and e.kind != kind) or (bool(t) and not any(
                t in it.text(c).lower() for c in (2, 3, 5)))
            it.setHidden(hide)
            if hide and (it.isSelected() or it.checkState(0) == Qt.Checked):
                it.setSelected(False)
                it.setCheckState(0, Qt.Unchecked)
            shown += not hide
        total = self.tree.topLevelItemCount()
        self.count_lbl.setText(f"{shown} of {total} log(s)" if shown != total else f"{total} log(s)")
        self._sel_changed()

    def _show(self):
        from linux_defender import logs as L
        it = self.tree.currentItem()
        if not it or it.isHidden():
            self.detail.setPlainText("")
            return
        self.detail.setPlainText(L.read_text(it.data(0, Qt.UserRole)))
        if it.data(0, Qt.UserRole).kind != "scan":
            from PySide6.QtGui import QTextCursor
            self.detail.moveCursor(QTextCursor.End)

    # ---- selection (checkbox == highlighted row; hidden rows are never selected)
    def _selected(self):
        """The ticked rows (hidden and locked rows never count)."""
        return [self.tree.topLevelItem(i).data(0, Qt.UserRole) for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).checkState(0) == Qt.Checked and not self.tree.topLevelItem(i).isHidden()
                and not self.tree.topLevelItem(i).data(0, Qt.UserRole).locked]

    def _check_changed(self, it, col):
        if self._syncing or col != 0:
            return
        self._sel_changed()

    def _select_all(self):
        self._syncing = True
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole).locked:
                continue
            it.setCheckState(0, Qt.Unchecked if it.isHidden() else Qt.Checked)
        self._syncing = False
        self._sel_changed()

    def _select_none(self):
        self._syncing = True
        self.tree.clearSelection()
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
        self._syncing = False
        self._sel_changed()

    def _sel_changed(self):
        # Ctrl/Shift-click on several rows ticks exactly those rows; a plain click only opens a row
        # for viewing and keeps the ticks.
        highlighted = [it for it in self.tree.selectedItems() if not it.isHidden()]
        if not self._syncing and len(highlighted) > 1:
            self._syncing = True
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, Qt.UserRole).locked:
                    continue
                want = Qt.Checked if (it.isSelected() and not it.isHidden()) else Qt.Unchecked
                if it.checkState(0) != want:
                    it.setCheckState(0, want)
            self._syncing = False
        sel = self._selected()
        n = len(sel)
        visible = sum(1 for i in range(self.tree.topLevelItemCount()) if not self.tree.topLevelItem(i).isHidden()
                      and not self.tree.topLevelItem(i).data(0, Qt.UserRole).locked)
        size = sum(e.size for e in sel)
        self.sel_lbl.setText(f"{n} of {visible} selected" + (f" · {fmt_size(size)}" if n else "") if visible else "")
        for b_ in (self.b_move, self.b_delete, self.b_none):
            b_.setEnabled(n > 0)
        self.b_all.setEnabled(visible > 0 and n < visible)
        self.b_delete.setText(f"Delete selected ({n})" if n else "Delete selected")
        self.b_move.setText(f"Move selected ({n}) to folder…" if n else "Move selected to folder…")

    # ---- actions
    def _report(self, text, ok=True):
        self.action_lbl.setText(text)
        self.action_lbl.setStyleSheet("color:#2fd38a;" if ok else "color:#ff6a6a;")

    def _move(self):
        from linux_defender import logs as L
        sel = self._selected()
        if not sel:
            return
        d = QFileDialog.getExistingDirectory(self, f"Move {len(sel)} log file(s) to folder", str(paths.Path.home()))
        if not d:
            return
        if os.path.realpath(d) in (os.path.realpath(paths.LOG_DIR), os.path.realpath(paths.SCAN_LOG_DIR)):
            self._report("Choose a folder outside the logs folder.", ok=False)
            return
        try:
            moved, failed = L.move_logs(sel, d)
        except OSError as e:
            self._report(f"Nothing was moved: {e}", ok=False)
            return
        active = sum(1 for e in sel if e.active)
        msg = f"Moved {len(moved)} log file(s) to {d}."
        if active:
            msg += f" {active} in-use log(s) were copied and then emptied."
        if failed:
            msg += f" {len(failed)} failed: " + "; ".join(failed[:3])
        self._report(msg, ok=not failed)
        self.refresh()

    def _delete(self):
        from linux_defender import logs as L
        sel = self._selected()
        if not sel or QMessageBox.question(self, "Delete logs", f"Delete {len(sel)} log file(s)? This can't be "
                                           "undone.") != QMessageBox.Yes:
            return
        n, failed = L.delete_logs(sel)
        active = sum(1 for e in sel if e.active)
        msg = f"Deleted {n} log file(s)." + (f" {active} in-use log(s) were emptied instead." if active else "")
        if failed:
            msg += f" {len(failed)} failed: " + "; ".join(failed[:3])
        self._report(msg, ok=not failed)
        self.refresh()

    def _delete_all(self):
        from linux_defender import logs as L
        allv = L.list_logs()
        if allv and QMessageBox.question(self, "Delete all logs", f"Delete all {len(allv)} log file(s)? This "
                                         "can't be undone.") == QMessageBox.Yes:
            n, failed = L.delete_logs(allv)
            busy = [f for f in failed if "running scan" in f]
            other = [f for f in failed if f not in busy]
            self.tabs.setCurrentIndex(0)
            msg = f"Deleted {n} log file(s)."
            if busy:
                msg += f" {len(busy)} kept: in use by the running scan."
            if other:
                msg += f" {len(other)} failed."
            self._report(msg, ok=not other)
            self.refresh()

    # ---- retention
    def _retention_changed(self, *_):
        self.ctl.settings.set("logs.max_age_days", self.days.value(), save=False)
        self.ctl.settings.set("logs.max_scan_logs", self.maxn.value())
        if not hasattr(self, "_ret_timer"):
            self._ret_timer = QTimer(self)
            self._ret_timer.setSingleShot(True)
            self._ret_timer.timeout.connect(self._apply_retention)
        self._ret_timer.start(1200)
        self._settings_status()

    def _apply_retention(self):
        n = self.ctl.apply_log_retention()
        if n:
            self.ret_lbl.setText(f"{n} log file(s) removed by the new rules.")
            self.ret_lbl.setStyleSheet("color:#ffc24b;")
        self.refresh()

    def _settings_status(self):
        entries = getattr(self, "_entries", [])
        scans = sum(1 for e in entries if e.kind == "scan")
        self.usage_lbl.setText(f"{len(entries)} log file(s) · {scans} scan report(s) · "
                               f"{fmt_size(sum(e.size for e in entries))}")
        self.b_clear.setEnabled(bool(entries))
        if not self.ret_lbl.text().endswith("new rules."):
            d, m = self.days.value(), self.maxn.value()
            self.ret_lbl.setText("Now: " + ("logs are kept until you delete them" if not d else
                                            f"logs older than {d} days are deleted") + "; " +
                                 ("no limit on scan reports" if not m else f"at most {m} scan reports are kept") + ".")
            self.ret_lbl.setStyleSheet("color:#8d97a3;")


# ---------------------------------------------------------------- Scan view
class ScanPage(Page):
    closed = Signal()

    def __init__(self, ctl, theme):
        super().__init__(ctl, "Scan", theme)
        self.job = None
        f, fl = card(margins=22)
        top = QHBoxLayout()
        self.icon = IconLabel("protection", "#2fd38a", 40)
        top.addWidget(self.icon)
        col = QVBoxLayout()
        self.headline = label("", "Hero")
        self.sub = label("", muted=True)
        self.sub.setTextInteractionFlags(Qt.NoTextInteraction)
        col.addWidget(self.headline)
        col.addWidget(self.sub)
        top.addLayout(col, 1)
        fl.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(10)
        fl.addWidget(self.bar)
        stats = QHBoxLayout()
        self.s_scanned = self._stat(stats, "Scanned items")
        self.s_threats = self._stat(stats, "Threats found")
        self.s_resolved = self._stat(stats, "Resolved")
        self.s_unres = self._stat(stats, "Unresolved")
        self.s_time = self._stat(stats, "Elapsed time")
        fl.addLayout(stats)
        btns = QHBoxLayout()
        self.controls = ScanControls(ctl, None)
        self.b_pause, self.b_resume, self.b_stop = self.controls.b_pause, self.controls.b_resume, self.controls.b_stop
        self.b_log = button("View log", icon="log", on_click=self._log)
        self.b_finish = button("Finish", "Primary", on_click=self._finish)
        btns.addWidget(self.controls)
        btns.addStretch(1)
        btns.addWidget(self.b_log)
        btns.addWidget(self.b_finish)
        fl.addLayout(btns)
        self.lay.addWidget(f)

        self.res_title = label("Threats", "H2")
        self.lay.addWidget(self.res_title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Threat", "File", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.setMinimumHeight(220)
        self.lay.addWidget(self.tree, 1)
        act = QHBoxLayout()
        self.act_label = label("Choose action for the selected threats:", muted=True)
        act.addWidget(self.act_label)
        self.b_q = button("Quarantine", on_click=lambda: self._resolve("quarantine"))
        self.b_d = button("Delete", "Danger", on_click=lambda: self._resolve("delete"))
        self.b_e = button("Add exception", on_click=lambda: self._resolve("except"))
        self.b_i = button("Ignore", on_click=lambda: self._resolve("ignore"))
        for b in (self.b_q, self.b_d, self.b_e, self.b_i):
            act.addWidget(b)
        act.addStretch(1)
        self.lay.addLayout(act)
        self.lay.addStretch(0)
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(lambda: self.job and self._progress(self.job.stats))
        ctl.scanStarted.connect(self.attach)
        ctl.scanState.connect(self._scan_state)
        ctl.scanProgress.connect(self._progress)
        ctl.scanThreat.connect(self._threat)
        ctl.scanDone.connect(self._done)

    def _stat(self, lay, title):
        col = QVBoxLayout()
        col.addWidget(label(title, muted=True))
        v = label("0")
        v.setStyleSheet("font-size:15pt;font-weight:700;")
        col.addWidget(v)
        lay.addLayout(col, 1)
        return v

    def attach(self, job):
        self.job = job
        self.title_label.setText(job.title)
        self.headline.setText("Scanning in progress…")
        self.headline.setStyleSheet("")
        self.icon.set_icon("protection", "#2fd38a", 40)
        self.sub.setText("Preparing…")
        self.bar.setRange(0, 0)
        self.bar.show()
        self.tree.clear()
        self.controls.show()
        self.controls.sync()
        self.b_finish.setEnabled(False)
        self.b_log.setEnabled(False)
        self._set_actions_visible(False)
        self._progress(job.stats)
        self.tick.start()

    def _progress(self, s):
        if not self.job or s is not self.job.stats:
            return
        self.s_scanned.setText(f"{s.scanned:,}")
        self.s_threats.setText(str(s.infected))
        self.s_resolved.setText(str(s.resolved))
        self.s_unres.setText(str(s.unresolved))
        m, sec = divmod(int(s.elapsed), 60)
        h, m = divmod(m, 60)
        self.s_time.setText(f"{h:02d}:{m:02d}:{sec:02d}")
        if self.job.running:
            cur = s.current
            fm = self.sub.fontMetrics()
            self.sub.setText(fm.elidedText(cur or "Preparing…", Qt.ElideMiddle, max(200, self.sub.width())))
        col = "#ff6a6a" if s.infected else None
        self.s_threats.setStyleSheet("font-size:15pt;font-weight:700;" + (f"color:{col};" if col else ""))

    def _threat(self, t):
        if not self.job or t not in self.job.threats:
            return
        self._add_row(t)

    def _add_row(self, t):
        it = QTreeWidgetItem([t.name, t.path, self._status_text(t)])
        it.setData(0, Qt.UserRole, t)
        it.setIcon(0, svg_icon("critical", "#ff6a6a"))
        self.tree.addTopLevelItem(it)
        self.tree.resizeColumnToContents(0)

    @staticmethod
    def _status_text(t):
        return {"quarantined": "Moved to quarantine", "deleted": "Deleted", "ignored": "Ignored (no action)",
                "excepted": "Added to exceptions", "failed": f"Action failed: {t.error}",
                "none": "Unresolved — choose an action"}.get(t.action, t.action)

    def _done(self, job):
        if job is not self.job:
            return
        self.tick.stop()
        self._progress(job.stats)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        s = job.stats
        if job.cancelled:
            self.headline.setText("Scan stopped")
            self.icon.set_icon("info", "#8d97a3", 40)
        elif s.unresolved:
            self.headline.setText("Your system requires your attention!")
            self.headline.setStyleSheet("color:#ff6a6a;")
            self.icon.set_icon("shield_alert", "#ff6a6a", 40)
        elif s.infected:
            self.headline.setText("Detected threats were resolved!")
            self.headline.setStyleSheet("color:#ffc24b;")
            self.icon.set_icon("shield_check", "#ffc24b", 40)
        else:
            self.headline.setText("Your system is clean!")
            self.headline.setStyleSheet("color:#2fd38a;")
            self.icon.set_icon("shield_check", "#2fd38a", 40)
        self.sub.setText(f"Scan finished · {s.skipped:,} items skipped (empty, too large or unreadable) · "
                         f"{s.errors} errors")
        self.controls.hide()
        self.b_finish.setEnabled(True)
        self.b_log.setEnabled(bool(getattr(job, "log_file", "")))
        self._set_actions_visible(bool(s.unresolved))
        self.ctl.finish_scan_bookkeeping(job)

    def show_job(self, job):
        """Show a finished job again (from the dashboard 'Review' action)."""
        self.attach(job)
        for t in job.threats:
            self._add_row(t)
        self.tick.stop()
        self._done_display(job)

    def _done_display(self, job):
        self.tick.stop()
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.headline.setText("Your system requires your attention!" if job.stats.unresolved else "Scan finished")
        self.controls.hide()
        self.b_finish.setEnabled(True)
        self.b_log.setEnabled(bool(getattr(job, "log_file", "")))
        self._set_actions_visible(bool(job.stats.unresolved))

    def _set_actions_visible(self, v):
        for w in (self.act_label, self.b_q, self.b_d, self.b_e, self.b_i):
            w.setVisible(v)

    def _resolve(self, action):
        if not self.job:
            return
        items = self.tree.selectedItems() or [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        for it in items:
            t = it.data(0, Qt.UserRole)
            if t.action in ("none", "failed"):
                self.job.resolve(t, action)
                it.setText(2, self._status_text(t))
        self._progress(self.job.stats)
        self._set_actions_visible(bool(self.job.stats.unresolved))
        self.ctl.statusChanged.emit()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        t = it.data(0, Qt.UserRole)
        m = QMenu(self)
        m.addAction("Open containing folder",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(t.path))))
        if t.action in ("none", "failed"):
            m.addSeparator()
            m.addAction("Quarantine", lambda: self._resolve("quarantine"))
            m.addAction("Delete", lambda: self._resolve("delete"))
            m.addAction("Add exception", lambda: self._resolve("except"))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _scan_state(self, st):
        if not self.job or not self.job.running:
            return
        if st == "paused":
            self.headline.setText("Scan paused")
            self.headline.setStyleSheet("color:#ffc24b;")
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
        elif st == "running":
            self.headline.setText("Scanning in progress…")
            self.headline.setStyleSheet("")
            self.bar.setRange(0, 0)

    def _log(self):
        lf = getattr(self.job, "log_file", "")
        if lf:
            QDesktopServices.openUrl(QUrl.fromLocalFile(lf))

    def _finish(self):
        self.closed.emit()


# ---------------------------------------------------------------- Notifications
class NotificationRow(QWidget):
    """One notification in the list: level icon, title, meta line and an explicit unread marker."""

    def __init__(self, ev):
        super().__init__()
        self.ev = ev
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 7, 10, 7)
        lay.setSpacing(10)
        col = {"critical": "#ff6a6a", "warning": "#ffc24b"}.get(ev["level"], "#4c9dff")
        lay.addWidget(IconLabel(LEVEL_ICON.get(ev["level"], "info"), col, 20), 0, Qt.AlignTop)
        txt = QVBoxLayout()
        txt.setSpacing(1)
        self.title = QLabel(ev["title"])
        self.title.setToolTip(ev["title"])
        self.meta = QLabel(f"{ev['module']} · {fmt_time(ev['ts'])}")
        txt.addWidget(self.title)
        txt.addWidget(self.meta)
        lay.addLayout(txt, 1)
        self.tag = QLabel("NEW")
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        lay.addWidget(self.tag, 0, Qt.AlignVCenter)
        lay.addWidget(self.dot, 0, Qt.AlignVCenter)
        self.set_read(bool(ev.get("read")))

    def set_read(self, read: bool):
        self.ev["read"] = read
        self.title.setStyleSheet("font-weight:500;" if read else "font-weight:800;")
        self.meta.setStyleSheet("color:#8d97a3; font-size:9pt;")
        self.tag.setVisible(not read)
        self.tag.setStyleSheet("color:#4c9dff; font-size:8pt; font-weight:800;")
        self.dot.setStyleSheet("background:transparent;" if read else "background:#4c9dff; border-radius:5px;")


class NotificationsPage(Page):
    unreadChanged = Signal()

    def __init__(self, ctl, theme):
        super().__init__(ctl, "Notifications", theme)
        tabs = QHBoxLayout()
        self.filter = "all"
        self.fbtn = {}
        for key, txt in (("all", "All"), ("critical", "Critical"), ("warning", "Warnings"), ("info", "Information")):
            b = QPushButton(txt)
            b.setCheckable(True)
            b.setObjectName("Nav")
            b.setChecked(key == "all")
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            tabs.addWidget(b)
            self.fbtn[key] = b
        tabs.addStretch(1)
        self.unread_lbl = label("", muted=True)
        tabs.addWidget(self.unread_lbl)
        self.b_read = button("Mark all as read", on_click=self._read_all)
        tabs.addWidget(self.b_read)
        self.b_clear = button("Clear", on_click=self._clear)
        tabs.addWidget(self.b_clear)
        self.lay.addLayout(tabs)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(360)
        self.list.setObjectName("NotifList")
        self.list.setStyleSheet("QListWidget#NotifList::item { padding: 0px; }")
        self.list.currentItemChanged.connect(self._show)
        row.addWidget(self.list, 5)
        dv, dl = card()
        self.d_title = label("", "H2")
        self.d_title.setWordWrap(True)
        self.d_meta = label("", muted=True)
        self.d_body = QPlainTextEdit()
        self.d_body.setReadOnly(True)
        self.d_body.setFrameShape(QFrame.NoFrame)
        self.d_open = button("Open scan log", icon="log", on_click=self._open_log)
        self.d_open.hide()
        dl.addWidget(self.d_title)
        dl.addWidget(self.d_meta)
        dl.addWidget(self.d_body, 1)
        dl.addWidget(self.d_open, 0, Qt.AlignLeft)
        row.addWidget(dv, 6)
        self.lay.addLayout(row, 1)
        self.list.setMinimumHeight(440)
        self._read_timer = QTimer(self)
        self._read_timer.setSingleShot(True)
        self._read_timer.timeout.connect(self._mark_current_read)

    def _set_filter(self, k):
        self.filter = k
        for key, b in self.fbtn.items():
            b.setChecked(key == k)
        self.refresh()

    def _rows(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            yield it, self.list.itemWidget(it)

    def refresh(self):
        cur = self.list.currentItem()
        cur_key = self.ctl.events.key(cur.data(Qt.UserRole)) if cur else None
        self.list.blockSignals(True)
        self.list.clear()
        select = 0
        for ev in self.ctl.events.all():
            if self.filter != "all" and ev["level"] != self.filter:
                continue
            it = QListWidgetItem()
            it.setData(Qt.UserRole, ev)
            w = NotificationRow(ev)
            it.setSizeHint(QSize(w.sizeHint().width(), max(w.sizeHint().height(), 56)))
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            if cur_key and self.ctl.events.key(ev) == cur_key:
                select = self.list.count() - 1
        if self.list.count():
            self.list.setCurrentRow(select)          # signals still blocked: not a user selection
        self.list.blockSignals(False)
        if self.list.count():
            self._show(self.list.currentItem(), mark=False)
        else:
            self.d_title.setText("No notifications")
            self.d_meta.setText("")
            self.d_body.setPlainText("")
            self.d_open.hide()
        self._update_counts()

    def _update_counts(self):
        n = self.ctl.events.unread_count()
        self.unread_lbl.setText(f"{n} unread" if n else "All read")
        self.b_read.setEnabled(n > 0)
        self.b_clear.setEnabled(self.list.count() > 0 or n > 0)

    def _show(self, it, _prev=None, mark=True):
        if not it:
            return
        ev = it.data(Qt.UserRole)
        self.d_title.setText(ev["title"])
        self.d_meta.setText(f"{ev['module']} · {fmt_time(ev['ts'])} · {ev['level'].title()}"
                            + ("" if ev.get("read") else " · Unread"))
        body = ev.get("details", "") or "No additional details."
        th = ev.get("data", {}).get("threats")
        if th:
            body += "\n\nThreats:\n" + "\n".join(f"• {t['name']} — {t['path']} [{t['action']}]" for t in th)
        self.d_body.setPlainText(body)
        self._log = ev.get("data", {}).get("log", "")
        self.d_open.setVisible(bool(self._log) and os.path.exists(self._log))
        if mark and not ev.get("read"):
            self._read_timer.start(800)          # opening a notification marks it as read

    def _mark_current_read(self):
        it = self.list.currentItem()
        if not it:
            return
        ev = it.data(Qt.UserRole)
        if ev.get("read"):
            return
        self.ctl.events.mark_read([self.ctl.events.key(ev)])
        self.list.itemWidget(it).set_read(True)
        it.setData(Qt.UserRole, ev)
        self.d_meta.setText(f"{ev['module']} · {fmt_time(ev['ts'])} · {ev['level'].title()}")
        self._update_counts()
        self.unreadChanged.emit()

    def _open_log(self):
        if getattr(self, "_log", ""):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._log))

    def _read_all(self):
        self._read_timer.stop()
        self.ctl.events.mark_all_read()
        for it, w in self._rows():
            ev = it.data(Qt.UserRole)
            ev["read"] = True
            it.setData(Qt.UserRole, ev)
            w.set_read(True)
        cur = self.list.currentItem()
        if cur:
            self._show(cur, mark=False)
        self._update_counts()
        self.unreadChanged.emit()

    def _clear(self):
        if QMessageBox.question(self, "Clear", "Delete all notifications?") == QMessageBox.Yes:
            self.ctl.events.clear()
            self.refresh()
            self.unreadChanged.emit()


# ---------------------------------------------------------------- Settings
class SettingsPage(Page):
    themeChanged = Signal(str)

    def __init__(self, ctl, theme):
        super().__init__(ctl, "Settings", theme)
        s = ctl.settings
        tabs = QTabWidget()
        self.lay.addWidget(tabs)

        # General
        g = QWidget()
        gl = QVBoxLayout(g)
        gl.setContentsMargins(0, 12, 0, 0)
        f, fl = card(spacing=2)
        self.cb_theme = QComboBox()
        self.cb_theme.addItem("Dark", "dark")
        self.cb_theme.addItem("Light", "light")
        self.cb_theme.setCurrentIndex(self.cb_theme.findData(s.get("general.theme")))
        self.cb_theme.currentIndexChanged.connect(self._theme)
        self.t_notif = Toggle(s.get("general.notifications"))
        self.t_notif.toggled.connect(lambda v: (s.set("general.notifications", v), self._update_states()))
        self.t_tray = Toggle(s.get("general.close_to_tray"))
        self.t_tray.toggled.connect(lambda v: s.set("general.close_to_tray", v))
        self.t_auto = Toggle(s.get("general.autostart"))
        self.t_auto.toggled.connect(self._autostart)
        self.t_min = Toggle(s.get("general.start_minimized"))
        self.t_min.toggled.connect(lambda v: (s.set("general.start_minimized", v), self._update_states()))
        self.t_tray.toggled.connect(lambda v: self._update_states())
        rows = [("Appearance", "", self.cb_theme),
                ("Notifications", "Show desktop notifications for threats, scans and update problems.", self.t_notif),
                ("Start on login", "Start Linux Defender in the system tray when you log in, so the Shield and "
                 "scheduled scans keep working.", self.t_auto),
                ("Start minimized", "Open in the system tray instead of showing the window.", self.t_min),
                ("Keep running in the tray when closed", "Closing the window keeps protection active.", self.t_tray)]
        for i, (t, d, w) in enumerate(rows):
            if i:
                fl.addWidget(sep())
            fl.addWidget(SettingRow(t, d, w))
            if w is self.t_auto:
                self.auto_start_status = label("", wrap=True)
                fl.addWidget(self.auto_start_status)
            if w is self.t_min:
                self.min_status = label("", wrap=True)
                fl.addWidget(self.min_status)
            if w is self.t_notif:
                self.notif_status = label("", wrap=True)
                fl.addWidget(self.notif_status)
            if w is self.t_tray:
                self.tray_status = label("", wrap=True)
                fl.addWidget(self.tray_status)
        gl.addWidget(f)
        gl.addStretch(1)
        tabs.addTab(scroll(g), "General")

        # Update
        u = QWidget()
        ul = QVBoxLayout(u)
        ul.setContentsMargins(0, 12, 0, 0)
        f, fl = card(spacing=2)
        self.t_upd = Toggle(s.get("update.auto"))
        self.t_upd.toggled.connect(self._auto_update)
        self.cb_int = QComboBox()
        for h in (1, 2, 4, 8, 12, 24):
            self.cb_int.addItem(f"Every {h} hour{'s' if h > 1 else ''}", h)
        self.cb_int.setCurrentIndex(max(0, self.cb_int.findData(int(s.get("update.interval_hours", 2)))))
        self.cb_int.currentIndexChanged.connect(self._interval)
        rows = [("Automatic update", "Download new threat signatures in the background.", self.t_upd),
                ("Check for updates", "ClamAV asks clients not to check more than once per hour.", self.cb_int)]
        for i, (t, d, w) in enumerate(rows):
            if i:
                fl.addWidget(sep())
            fl.addWidget(SettingRow(t, d, w))
        self.auto_status = label("", wrap=True)
        fl.addWidget(self.auto_status)
        ul.addWidget(f)
        dl, dll = card(spacing=8)
        dll.addWidget(label("Threat signatures", "H2"))
        self.update_panel = UpdatePanel(ctl)
        dll.addWidget(self.update_panel)
        ul.addWidget(dl)
        # proxy
        p, pl = card(spacing=6)
        pl.addWidget(label("Proxy", "H2"))
        px = s.get("update.proxy")
        self.t_px = Toggle(px.get("enabled"))
        pl.addWidget(SettingRow("Use a proxy for updates", "", self.t_px))
        grid = QGridLayout()
        self.px_host = QLineEdit(px.get("host", ""))
        self.px_port = QSpinBox()
        self.px_port.setRange(1, 65535)
        self.px_port.setValue(int(px.get("port", 8080)))
        fit_field(self.px_port)
        self.px_user = QLineEdit(px.get("user", ""))
        self.px_pass = QLineEdit(px.get("password", ""))
        self.px_pass.setEchoMode(QLineEdit.Password)
        for i, (t, w) in enumerate((("Address", self.px_host), ("Port", self.px_port),
                                    ("User name", self.px_user), ("Password", self.px_pass))):
            grid.addWidget(label(t, muted=True), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        pl.addLayout(grid)
        self.b_px = button("Save proxy settings", on_click=self._save_proxy)
        pl.addWidget(self.b_px, 0, Qt.AlignLeft)
        self.px_status = label("", wrap=True)
        pl.addWidget(self.px_status)
        self.t_px.toggled.connect(self._proxy_toggled)
        ul.addWidget(p)
        ul.addStretch(1)
        tabs.addTab(scroll(u), "Update")

        # Integration
        it = QWidget()
        il = QVBoxLayout(it)
        il.setContentsMargins(0, 12, 0, 0)
        f, fl = card(spacing=2)
        self.t_fm = Toggle(s.get("integration.file_manager"))
        self.t_fm.toggled.connect(self._fm)
        fl.addWidget(SettingRow("Scan with Linux Defender in the file manager",
                                "Right-click files or folders to scan them, in Caja (MATE), Files (Nautilus › Scripts), "
                                "Nemo and Dolphin.",
                                self.t_fm))
        self.fm_status = label("", wrap=True)
        fl.addWidget(self.fm_status)
        fl.addWidget(sep())
        self.t_menu = Toggle(s.get("integration.menu_entry"))
        self.t_menu.toggled.connect(self._menu_entry)
        fl.addWidget(SettingRow("Add Linux Defender to the applications menu",
                                "Creates a launcher (with Quick Scan and Update actions) for this AppImage.",
                                self.t_menu))
        self.menu_status = label("", wrap=True)
        fl.addWidget(self.menu_status)
        il.addWidget(f)
        il.addStretch(1)
        tabs.addTab(scroll(it), "Integration")

        ctl.updateDone.connect(lambda *_: self._update_states())

    def refresh(self):
        s = self.ctl.settings
        # keep switches in sync with the stored settings (they can change from elsewhere)
        for t, key in ((self.t_notif, "general.notifications"), (self.t_tray, "general.close_to_tray"),
                       (self.t_auto, "general.autostart"), (self.t_min, "general.start_minimized"),
                       (self.t_upd, "update.auto"), (self.t_px, "update.proxy.enabled"),
                       (self.t_fm, "integration.file_manager"), (self.t_menu, "integration.menu_entry")):
            if t.isChecked() != bool(s.get(key)):
                t.blockSignals(True)
                t.setChecked(bool(s.get(key)))
                t.blockSignals(False)
        self.update_panel.sync()
        self._update_states()

    @staticmethod
    def _fm_status_text() -> str:
        fms = integration.file_managers()
        names = {"caja": "Caja", "nautilus": "Files", "nemo": "Nemo", "dolphin": "Dolphin"}
        found = [n for k, n in names.items() if fms[k]]
        lines = ["Installed for Caja, Files, Nemo and Dolphin."
                 + (f" Found on this computer: {', '.join(found)}." if found else "")]
        if fms["caja"]:
            if fms["caja_actions"]:
                lines.append("Caja: right-click a file or folder › Scan with Linux Defender (right-click an empty "
                             "area to scan the open folder).")
            else:
                lines.append("Caja: right-click › Scripts › Scan with Linux Defender. For the entry directly in the "
                             "right-click menu, install caja-actions (sudo apt install caja-actions) and restart Caja "
                             "(caja -q).")
        return "\n".join(lines)

    def _update_states(self):
        """Every switch's dependent controls and status line, derived from the current state."""
        s = self.ctl.settings
        ok, warn, off = "color:#2fd38a;", "color:#ffc24b;", ""
        # automatic update
        auto = self.t_upd.isChecked()
        self.cb_int.setEnabled(auto)
        if auto:
            last = float(s.get("update.last_check", 0))
            nxt = max(time.time(), last + int(s.get("update.interval_hours", 2)) * 3600)
            self.auto_status.setText("Automatic updates are on. Next check: " +
                                     ("in a few minutes" if nxt - time.time() < 600 else fmt_time(nxt)))
            self.auto_status.setStyleSheet(ok)
        else:
            self.auto_status.setText("Automatic updates are off. Signatures update only when you click Update now.")
            self.auto_status.setStyleSheet(warn)
        # proxy
        on = self.t_px.isChecked()
        for w in (self.px_host, self.px_port, self.px_user, self.px_pass, self.b_px):
            w.setEnabled(on)
        host = s.get("update.proxy.host") or ""
        if not on:
            self.px_status.setText("Updates connect directly to the ClamAV mirrors.")
            self.px_status.setStyleSheet(off)
        elif host:
            self.px_status.setText(f"Updates go through {host}:{s.get('update.proxy.port')}.")
            self.px_status.setStyleSheet(ok)
        else:
            self.px_status.setText("Enter the proxy address and click Save proxy settings.")
            self.px_status.setStyleSheet(warn)
        # integration
        if self.t_fm.isChecked() and integration.NAUTILUS_SCRIPT.exists():
            self.fm_status.setText(self._fm_status_text())
            self.fm_status.setStyleSheet(ok)
        else:
            self.fm_status.setText("Not installed.")
            self.fm_status.setStyleSheet(off)
        if self.t_menu.isChecked() and integration.MENU_ENTRY.exists():
            self.menu_status.setText(f"Installed: {integration.MENU_ENTRY}")
            self.menu_status.setStyleSheet(ok)
        else:
            self.menu_status.setText("Not installed.")
            self.menu_status.setStyleSheet(off)
        # general
        if self.t_auto.isChecked() and integration.AUTOSTART.exists():
            self.auto_start_status.setText("Linux Defender will start in the tray when you log in.")
            self.auto_start_status.setStyleSheet(ok)
        else:
            self.auto_start_status.setText("Linux Defender does not start automatically. The Shield and scheduled "
                                           "scans work only while the app is open.")
            self.auto_start_status.setStyleSheet(warn if not self.t_auto.isChecked() else off)
        if self.t_min.isChecked():
            self.min_status.setText("The window stays hidden at start; open it from the tray icon.")
        else:
            self.min_status.setText("The window opens at start.")
        self.min_status.setStyleSheet(off)
        if self.t_notif.isChecked():
            self.notif_status.setText("Desktop notifications are on.")
            self.notif_status.setStyleSheet(ok)
        else:
            self.notif_status.setText("Desktop notifications are off. Threats and scan results appear only in "
                                      "Notifications.")
            self.notif_status.setStyleSheet(warn)
        if self.t_tray.isChecked():
            self.tray_status.setText("Closing the window keeps Linux Defender running in the tray.")
            self.tray_status.setStyleSheet(ok)
        else:
            self.tray_status.setText("Closing the window quits Linux Defender and stops the Shield.")
            self.tray_status.setStyleSheet(warn)

    def _auto_update(self, v):
        self.ctl.settings.set("update.auto", v)
        self._update_states()

    def _interval(self, _):
        self.ctl.settings.set("update.interval_hours", self.cb_int.currentData())
        self._update_states()

    def _proxy_toggled(self, v):
        self.ctl.settings.set("update.proxy.enabled", v)
        self._update_states()

    def _apply(self, toggle, key, fn):
        """Run an integration action; on failure revert the switch and explain."""
        v = toggle.isChecked()
        try:
            fn(v)
            self.ctl.settings.set(key, v)
        except OSError as e:
            toggle.blockSignals(True)
            toggle.setChecked(not v)
            toggle.blockSignals(False)
            QMessageBox.warning(self, APP_NAME, f"Could not change this setting:\n{e}")
        self._update_states()

    def _theme(self, _):
        v = self.cb_theme.currentData()
        self.ctl.settings.set("general.theme", v)
        self.themeChanged.emit(v)

    def _autostart(self, v):
        self._apply(self.t_auto, "general.autostart", integration.set_autostart)

    def _fm(self, v):
        self._apply(self.t_fm, "integration.file_manager", integration.set_file_manager_integration)

    def _menu_entry(self, v):
        from linux_defender.ui.icons import app_icon_svg
        self._apply(self.t_menu, "integration.menu_entry", lambda on: integration.set_menu_entry(on, app_icon_svg("safe")))

    def _save_proxy(self):
        self.ctl.settings.set("update.proxy", {"enabled": self.t_px.isChecked(), "host": self.px_host.text().strip(),
                                               "port": self.px_port.value(), "user": self.px_user.text().strip(),
                                               "password": self.px_pass.text()})
        self._update_states()
        QMessageBox.information(self, "Proxy", "Proxy settings saved. They apply to the next update.")



# ---------------------------------------------------------------- Support / About
class SupportPage(Page):
    def __init__(self, ctl, theme):
        super().__init__(ctl, "Support", theme)
        f, fl = card(margins=22, layout="h")
        ic = QLabel()
        ic.setPixmap(app_pixmap("safe", 72))
        fl.addWidget(ic)
        col = QVBoxLayout()
        col.addWidget(label(f"{APP_NAME} {VERSION}", "Hero"))
        col.addWidget(label("Free antivirus for Ubuntu 24.04", muted=True))
        self.engine_lbl = label("", muted=True)
        col.addWidget(self.engine_lbl)
        fl.addLayout(col, 1)
        self.lay.addWidget(f)

        h, hl = card(spacing=8)
        hl.addWidget(label("Help", "H2"))
        for t, cb in (("Open logs folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.LOG_DIR)))),
                      ("Open configuration folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.CONFIG_DIR)))),
                      ("Report a false positive to ClamAV", lambda: ctl.open_url("https://www.clamav.net/reports/fp")),
                      ("Submit a missed threat to ClamAV", lambda: ctl.open_url("https://www.clamav.net/reports/malware")),
                      ("ClamAV documentation", lambda: ctl.open_url(integration.CLAMAV_DOCS)),
                      ("Restart scan engine", lambda: ctl.engine.restart())):
            hl.addWidget(button(t, "Link", on_click=cb), 0, Qt.AlignLeft)
        self.lay.addWidget(h)

        a, al = card(obj="Card2", spacing=6)
        al.addWidget(label("About", "H2"))
        self.about_grid = QGridLayout()
        self.about_grid.setHorizontalSpacing(24)
        self.about_grid.setVerticalSpacing(6)
        al.addLayout(self.about_grid)
        al.addWidget(sep())
        al.addWidget(label(f"{APP_NAME} is free software released under the GPL-2.0-or-later licence. "
                           "ClamAV® is GPL-2.0, © Cisco Systems. Qt 6 and PySide6 are LGPL-3.0. "
                           "Python is under the PSF licence.", wrap=True, muted=True))
        self.lay.addWidget(a)
        self.lay.addStretch(1)

    def refresh(self):
        vi = self.ctl.engine.version_info()
        self.engine_lbl.setText(f"Engine: {vi['engine'] or 'ClamAV'} · Signatures: {vi['db_version'] or '—'} "
                                f"{('(' + vi['db_date'] + ')') if vi['db_date'] else ''}")
        while self.about_grid.count():
            w = self.about_grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        for r, (k, v) in enumerate(self._components(vi)):
            self.about_grid.addWidget(label(k, muted=True), r, 0, Qt.AlignTop)
            val = label(v)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setWordWrap(True)
            self.about_grid.addWidget(val, r, 1)
        self.about_grid.setColumnStretch(1, 1)

    def _components(self, vi):
        import platform
        import sys as _sys
        import PySide6
        from PySide6.QtCore import qVersion
        os_name = platform.system()
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        clamd = paths.find_tool("clamd") or "not found"
        freshclam = paths.find_tool("freshclam") or "not found"
        bundled = "bundled" if paths.appdir() and clamd.startswith(str(paths.appdir())) else "system"
        return [
            (APP_NAME, VERSION),
            ("Scan engine", f"{vi['engine'] or 'ClamAV'} ({bundled}) — {self.ctl.engine.state}"),
            ("Threat signatures", f"{vi['db_version']} · {vi['db_date']}" if vi["db_version"] else "not loaded"),
            ("Last update", fmt_time(self.ctl.settings.get("update.last_success"))),
            ("clamd", clamd),
            ("freshclam", freshclam),
            ("Signature folder", str(paths.DB_DIR)),
            ("Qt", qVersion()),
            ("PySide6", PySide6.__version__),
            ("Python", f"{platform.python_version()} ({_sys.executable})"),
            ("Operating system", f"{os_name} · kernel {platform.release()} · {platform.machine()}"),
        ]
