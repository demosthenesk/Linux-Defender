"""Signature download controls (Download / Pause / Resume / Stop) on Dashboard, Settings, tray and first-run setup.

Needs a stand-in for freshclam: set FAKE_FRESHCLAM=/path/to/script (it should print freshclam-style progress).
"""
import os, sys, subprocess
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from linux_defender import paths
_real = paths.find_tool
paths.find_tool = lambda n: os.environ["FAKE_FRESHCLAM"] if n == "freshclam" else _real(n)
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow, Onboarding
ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 800); win.show()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 100):
        if pred(): return True
        wait(100)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:52} {str(detail)[:90]}")
    if not cond: fails.append(name)
def proc_state():
    p = ctl.updater.proc
    return subprocess.run(["ps", "-o", "stat=", "-p", str(p.pid)], capture_output=True, text=True).stdout.strip() if p else "-"
def vis(panel):
    return {k: getattr(panel, "b_" + k).isVisible() for k in ("start", "pause", "resume", "stop")}

ctl.start(); until(lambda: ctl.engine.state not in ("stopped", "loading"), 5000)
dash = win.pages["dashboard"]; dp = dash.update_panel
win.go("dashboard"); wait(300)
check("no signatures at start", ctl.engine.state == "no_signatures", ctl.engine.state)
check("Update tile says 'Download signatures'", dash.qa["update"].action.text() == "Download signatures", dash.qa["update"].action.text())
check("download panel hidden while idle", not dash.dl_card.isVisible())
fix = [b for b in dash.findChildren(QPushButton) if b.text() == "Download now" and b.isVisible()]
check("'Download now' fix button present", bool(fix))
fix[0].click()
until(lambda: ctl.updater.progress_frac > 0.1)
check("download running", ctl.updater.state == "running", ctl.updater.progress_text)
check("dashboard panel visible", dash.dl_card.isVisible())
check("buttons: Pause + Stop", vis(dp) == {"start": False, "pause": True, "resume": False, "stop": True}, vis(dp))
check("progress bar shows a value", dp.bar.isVisible() and dp.bar.value() > 0, dp.bar.value())
check("sidebar shows download %", "Downloading signatures" in win.side_status.text(), win.side_status.text())
# pause
dp.b_pause.click(); wait(400)
frac_paused = ctl.updater.progress_frac
check("paused", ctl.updater.state == "paused")
check("freshclam process frozen (T)", proc_state().startswith("T"), proc_state())
check("buttons: Resume + Stop", vis(dp) == {"start": False, "pause": False, "resume": True, "stop": True}, vis(dp))
check("status says Paused", dp.status.text().startswith("Paused"), dp.status.text())
check("sidebar says Download paused", win.side_status.text() == "Download paused", win.side_status.text())
if hasattr(win, "act_dl_resume"):
    check("tray menu: Resume + Stop", win.act_dl_resume.isVisible() and win.act_dl_stop.isVisible() and not win.act_dl_pause.isVisible())
wait(1000)
check("no progress while paused", abs(ctl.updater.progress_frac - frac_paused) < 1e-9, f"{frac_paused:.2f}")
# resume
dp.b_resume.click(); wait(300)
check("resumed", ctl.updater.state == "running" and not proc_state().startswith("T"), proc_state())
until(lambda: ctl.updater.progress_frac > frac_paused + 0.05, 5000)
check("progress continues after resume", ctl.updater.progress_frac > frac_paused, f"{ctl.updater.progress_frac:.2f}")
# stop
dp.b_stop.click()
until(lambda: ctl.updater.state == "idle", 10000); wait(300)
check("stopped → idle", ctl.updater.state == "idle")
check("dashboard panel hidden again", not dash.dl_card.isVisible())
check("no temp files left", not any(p.name.startswith("tmp.") for p in paths.DB_DIR.iterdir()),
      [p.name for p in paths.DB_DIR.iterdir()])
evs = ctl.events.all()
check("event: 'Signature download stopped'", evs and evs[0]["title"] == "Signature download stopped", evs[0]["title"] if evs else "")
check("no 'Update failed' after a stop", not any(e["title"] == "Update failed" for e in evs))
check("still no signatures", ctl.engine.state == "no_signatures")
# full run from Settings, with a pause in between
win.go("settings"); wait(200)
from PySide6.QtWidgets import QTabWidget
win.pages["settings"].findChild(QTabWidget).setCurrentIndex(1); wait(200)      # Update tab
sp = win.pages["settings"].update_panel
check("Settings button says 'Download signatures'", sp.b_start.text() == "Download signatures", sp.b_start.text())
sp.b_start.click(); until(lambda: ctl.updater.progress_frac > 0.1)
sp.b_pause.click(); wait(500)
check("Settings: paused", ctl.updater.state == "paused" and sp.b_resume.isVisible())
sp.b_resume.click()
until(lambda: ctl.updater.state == "idle", 30000); wait(300)
check("download completed", ctl.update_ok is True, sp.status.text())
check("Settings shows success in green", "updated" in sp.status.text() and "2fd38a" in sp.status.styleSheet(), sp.status.text())
check("scan engine started with new signatures", until(lambda: ctl.engine.state == "ready", 30000), ctl.engine.state)
win.go("dashboard"); wait(300)
check("dashboard scans available now", dash.qa["quick"].action.isEnabled())
check("Update tile says 'Update now'", dash.qa["update"].action.text() == "Update now", dash.qa["update"].action.text())
# first-run setup dialog
ob = Onboarding(ctl, win); ob.show(); wait(200)
op = ob.panel
check("setup: Update button visible", op.b_start.isVisible() and op.b_start.text() == "Update now", op.b_start.text())
op.b_start.click(); until(lambda: ctl.updater.progress_frac > 0.05)
check("setup: Pause + Stop visible", vis(op)["pause"] and vis(op)["stop"], vis(op))
check("setup: 'Continue in background'", ob.b_skip1.text() == "Continue in background", ob.b_skip1.text())
op.b_pause.click(); wait(300)
check("setup: Resume visible after pause", vis(op)["resume"] and not vis(op)["pause"], vis(op))
op.b_stop.click(); until(lambda: ctl.updater.state == "idle", 10000); wait(200)
check("setup: stopped, dialog stays open", ob.isVisible() and op.b_start.isVisible())
ob.close()
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
