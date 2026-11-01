"""Main window: sidebar navigation + page stack, tray icon, onboarding."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from linux_defender import APP_NAME, VERSION, integration
from linux_defender import engine as eng
from linux_defender.ui.icons import app_icon, app_pixmap, svg_icon
from linux_defender.ui.pages import (UpdatePanel, DashboardPage, NotificationsPage, ProtectionPage, ScanPage,
                              SettingsPage, SupportPage, CustomScanDialog)
from linux_defender.ui.style import color, stylesheet
from linux_defender.ui.widgets import button, fit_field, label

NAV = [("dashboard", "Dashboard", "dashboard"), ("protection", "Protection", "protection"),
       ("notifications", "Notifications", "bell"),
       ("settings", "Settings", "settings"), ("support", "Support", "support")]


class MainWindow(QMainWindow):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon("safe"))
        self.resize(1180, 780)
        self.setMinimumSize(960, 640)
        self._quitting = False
        theme = lambda: ctl.settings.get("general.theme", "dark")
        self.theme = theme

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(app_pixmap("safe", 34))
        brand.addWidget(self.brand_icon)
        bcol = QVBoxLayout()
        bcol.setSpacing(0)
        bcol.addWidget(label(APP_NAME, "Brand"))
        bcol.addWidget(label("Antivirus Free", "BrandSub"))
        brand.addLayout(bcol, 1)
        sl.addLayout(brand)
        sl.addSpacing(20)
        self.nav = {}
        for key, text, icon in NAV:
            b = QPushButton("   " + text)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(b, 1)
            if key == "notifications":
                self.badge = label("", "Badge")
                self.badge.setAlignment(Qt.AlignCenter)
                self.badge.setFixedHeight(18)
                self.badge.setMinimumWidth(18)
                self.badge.hide()
                row.addWidget(self.badge)
            sl.addLayout(row)
            self.nav[key] = (b, icon)
        sl.addStretch(1)
        self.side_status = label("", "BrandSub")
        self.side_status.setWordWrap(True)
        sl.addWidget(self.side_status)
        sl.addWidget(label(f"Version {VERSION}", "BrandSub"))
        h.addWidget(side)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages = {
            "dashboard": DashboardPage(ctl, theme),
            "protection": ProtectionPage(ctl, theme),
            "notifications": NotificationsPage(ctl, theme),
            "settings": SettingsPage(ctl, theme),
            "support": SupportPage(ctl, theme),
            "scan": ScanPage(ctl, theme),
        }
        for p in self.pages.values():
            self.stack.addWidget(p)
        self.pages["dashboard"].navigate.connect(self.handle)
        self.pages["protection"].navigate.connect(self.handle)
        self.pages["scan"].closed.connect(lambda: self.go("dashboard"))
        self.pages["settings"].themeChanged.connect(self.apply_theme)
        self.pages["notifications"].unreadChanged.connect(self._badge)

        ctl.statusChanged.connect(self.refresh)
        ctl.engineState.connect(lambda *_: self.refresh())
        ctl.updateDone.connect(lambda *_: self.refresh())
        ctl.updateProgress.connect(self._update_progress_side)
        ctl.eventAdded.connect(lambda _: QTimer.singleShot(0, self._on_event))
        ctl.scanStarted.connect(lambda _: self.go("scan"))
        ctl.notify.connect(self.notify)
        ctl.window_visible = self.isVisible

        self._make_tray()
        self.apply_theme(theme())
        self.go("dashboard")
        self.refresh()
        self.poll = QTimer(self)
        self.poll.setInterval(30_000)
        self.poll.timeout.connect(self.refresh)
        self.poll.start()

    # -- navigation ----------------------------------------------------------
    def go(self, key):
        if key == "scan" and not self.ctl.job:
            key = "dashboard"
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        for k, (b, icon) in self.nav.items():
            sel = (k == key) or (key == "scan" and k == "protection")
            b.setChecked(sel)
            b.setIcon(svg_icon(icon, color(self.theme(), "accent") if sel else color(self.theme(), "muted")))
        page.refresh()

    def handle(self, cmd: str):
        if cmd.startswith("scan:"):
            self.start_scan("custom", cmd[5:].split("\0"))
            return
        action = cmd.split(":", 1)[1]
        if action in ("quick", "system"):
            self.start_scan(action)
        elif action == "custom" and self.ctl.job and self.ctl.job.running:
            self._scan_busy("custom")
        elif action == "custom":
            dlg = CustomScanDialog(self)
            dlg.name.setPlaceholderText("(optional) save this scan under a name")
            if dlg.exec() and dlg.paths:
                name = dlg.name.text().strip()
                if name:
                    lst = self.ctl.settings.get("custom_scans", [])
                    lst.append({"name": name, "paths": dlg.paths})
                    self.ctl.settings.set("custom_scans", lst)
                self.start_scan("custom", dlg.paths)
        elif action == "update":
            self.ctl.update_now()                 # progress + Pause/Resume/Stop appear on the Dashboard
        elif action == "view_scan" and self.ctl.job:
            self.go("scan")
        elif action == "restart_engine":
            self.ctl.engine.restart()
        elif action == "shield_on":
            self.ctl.set_shield(True)
        elif action == "review_scan" and self.ctl.last_job:
            self.pages["scan"].show_job(self.ctl.last_job)
            self.ctl.job = self.ctl.last_job
            self.go("scan")
        self.refresh()

    def start_scan(self, kind, targets=None):
        if self.ctl.job and self.ctl.job.running:
            self._scan_busy(kind)
            return
        if not self.ctl.engine.ready:
            QMessageBox.information(self, APP_NAME, {
                eng.STATE_LOADING: "The scan engine is still loading threat signatures. Try again in a moment.",
                eng.STATE_NO_SIGNATURES: "Threat signatures have not been downloaded yet. Run an update first.",
                eng.STATE_STOPPED: "The scan engine is starting. Try again in a moment.",
            }.get(self.ctl.engine.state, f"The scan engine is not running: {self.ctl.engine.info}"))
            return
        self.ctl.start_scan(kind, targets)

    def _scan_busy(self, kind):
        """Only one scan at a time: explain and offer to show the running one."""
        from linux_defender.controller import SCAN_TITLES
        j = self.ctl.job
        state = "paused" if j.paused else "running"
        want = SCAN_TITLES.get(kind, "scan")
        text = (f"The {j.title} is still {state} ({j.stats.scanned:,} items scanned).\n\n"
                f"Only one scan can run at a time. Stop the {j.title} or wait for it to finish, then start the "
                f"{want}.")
        self.ctl.events.add("info", "Antivirus", f"{want} not started: another scan is {state}", text)
        if not self.isVisible():
            self.notify(f"{want} not started", f"The {j.title} is still {state}.", "info")
        box = QMessageBox(QMessageBox.Information, APP_NAME, text, parent=self)
        show = box.addButton("Show running scan", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() is show:
            self.show_normal()
            self.go("scan")

    # -- status ----------------------------------------------------------------
    def refresh(self):
        st = self.ctl.overall()
        self.setWindowIcon(app_icon(st))
        self.brand_icon.setPixmap(app_pixmap(st, 34))
        if hasattr(self, "tray"):
            self.tray.setIcon(app_icon(st))
            self.tray.setToolTip(f"{APP_NAME} — " + {"safe": "You are safe", "warn": "Attention needed",
                                                     "risk": "Your device is at risk", "idle": "Starting…"}[st])
            self.act_shield.setText("Turn Shield off" if self.ctl.settings.get("antivirus.shield_enabled")
                                    else "Turn Shield on")
            sst = self.ctl.scan_state()
            self.act_quick.setVisible(sst == "idle")
            self.act_system.setVisible(sst == "idle")
            self.act_scan_pause.setVisible(sst == "running")
            self.act_scan_resume.setVisible(sst == "paused")
            self.act_scan_stop.setVisible(sst != "idle")
            ust = self.ctl.updater.state
            self.act_update.setVisible(ust == "idle")
            self.act_dl_pause.setVisible(ust == "running")
            self.act_dl_resume.setVisible(ust == "paused")
            self.act_dl_stop.setVisible(ust in ("running", "paused"))
        ust = self.ctl.updater.state
        sst = self.ctl.scan_state()
        if sst != "idle":
            self.side_status.setText(f"{self.ctl.job.title} " + ("paused" if sst == "paused" else "running…"))
        elif ust == "paused":
            self.side_status.setText("Download paused")
        elif ust == "stopping":
            self.side_status.setText("Stopping download…")
        elif not self.ctl.updater.running:
            self.side_status.setText({eng.STATE_LOADING: "Loading signatures…",
                                      eng.STATE_READY: "Protection active"}.get(self.ctl.engine.state, ""))
        cur = self.stack.currentWidget()
        if cur is not self.pages["scan"] and hasattr(cur, "refresh"):
            cur.refresh()
        self._badge()

    def _update_progress_side(self, text, frac):
        if self.ctl.updater.state != "running":
            return
        pct = f" {int(frac * 100)}%" if frac >= 0 else ""
        self.side_status.setText(f"Downloading signatures…{pct}")

    def _on_event(self):
        self._badge()
        if self.stack.currentWidget() is self.pages["notifications"]:
            self.pages["notifications"].refresh()

    def _badge(self):
        n = self.ctl.events.unread_count()
        self.badge.setText(str(n) if n < 100 else "99+")
        self.badge.setVisible(n > 0)

    def apply_theme(self, name):
        QApplication.instance().setStyleSheet(stylesheet(name))
        # number/time fields: re-measure with the theme's padding and arrow buttons so no digit is hidden
        for sb in self.findChildren(QAbstractSpinBox):
            fit_field(sb)
        cur = [k for k, (b, _) in self.nav.items() if b.isChecked()]
        if cur:
            self.go(cur[0])

    # -- tray ------------------------------------------------------------------
    def _make_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon("safe"), self)
        m = QMenu()
        m.addAction("Open Linux Defender", self.show_normal)
        m.addSeparator()
        self.act_quick = m.addAction("Quick Scan", lambda: (self.show_normal(), self.start_scan("quick")))
        self.act_system = m.addAction("System Scan", lambda: (self.show_normal(), self.start_scan("system")))
        self.act_scan_pause = m.addAction("Pause scan", self.ctl.pause_scan)
        self.act_scan_resume = m.addAction("Resume scan", self.ctl.resume_scan)
        self.act_scan_stop = m.addAction("Stop scan", self.ctl.stop_scan)
        self.act_update = m.addAction("Update now", self.ctl.update_now)
        self.act_dl_pause = m.addAction("Pause download", self.ctl.pause_update)
        self.act_dl_resume = m.addAction("Resume download", self.ctl.resume_update)
        self.act_dl_stop = m.addAction("Stop download", self.ctl.stop_update)
        self.act_shield = QAction("Turn Shield off", self)
        self.act_shield.triggered.connect(
            lambda: self.ctl.set_shield(not self.ctl.settings.get("antivirus.shield_enabled")))
        m.addAction(self.act_shield)
        m.addSeparator()
        m.addAction("Quit", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (QSystemTrayIcon.Trigger,
                                                                         QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def notify(self, title, body, level):
        if not self.ctl.settings.get("general.notifications"):
            return
        if hasattr(self, "tray") and self.tray.supportsMessages():
            icon = {"critical": QSystemTrayIcon.Critical, "warning": QSystemTrayIcon.Warning}.get(
                level, QSystemTrayIcon.Information)
            self.tray.showMessage(title, body, icon, 8000)
        else:
            integration.desktop_notify(title, body, "critical" if level == "critical" else "normal")

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if not self._quitting and self.ctl.settings.get("general.close_to_tray") and hasattr(self, "tray"):
            e.ignore()
            self.hide()
            if not self.ctl.settings.get("tray_hint_shown"):
                self.ctl.settings.set("tray_hint_shown", True)
                self.notify(APP_NAME, "Linux Defender keeps protecting you from the system tray.", "info")
            return
        self.quit()
        e.accept()

    def quit(self):
        self._quitting = True
        if self.ctl.job and self.ctl.job.running:
            if QMessageBox.question(self, APP_NAME, "A scan is running. Stop it and quit?") != QMessageBox.Yes:
                self._quitting = False
                return
        self.ctl.shutdown()
        QApplication.instance().quit()


class Onboarding(QDialog):
    """First run: download the threat signatures."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setWindowIcon(app_icon("safe"))
        self.resize(640, 340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 26)
        lay.setSpacing(12)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(app_pixmap("safe", 64))
        top.addWidget(ic)
        col = QVBoxLayout()
        col.addWidget(label(f"Welcome to {APP_NAME}", "Hero"))
        col.addWidget(label("Free antivirus protection for Ubuntu", muted=True))
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        # step 1: signatures
        s1 = QWidget()
        l1 = QVBoxLayout(s1)
        l1.addWidget(label("Threat signatures", "H2"))
        l1.addWidget(label("Linux Defender needs the latest threat information before it can protect you. The first "
                           "download is about 230 MB. Later updates are small and happen automatically.",
                           wrap=True, muted=True))
        self.panel = UpdatePanel(ctl, show_last=False)
        l1.addWidget(self.panel)
        l1.addStretch(1)
        r = QHBoxLayout()
        self.b_skip1 = button("Later", on_click=self.accept)
        r.addStretch(1)
        r.addWidget(self.b_skip1)
        l1.addLayout(r)
        self.stack.addWidget(s1)


        ctl.updateState.connect(self._state)
        ctl.updateDone.connect(self._done)
        self._state(ctl.updater.state)

    def _state(self, st):
        self.b_skip1.setText("Continue in background" if st != "idle" else "Later")

    def _done(self, ok, changed, message):
        if ok and not self.ctl.updater.last_cancelled:
            self.b_skip1.hide()
            QTimer.singleShot(1500, self.accept)
