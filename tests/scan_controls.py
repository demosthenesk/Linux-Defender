"""Start / Pause / Resume / Stop for every scan type, from every place that offers the controls."""
import os, sys, time
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 50):
        if pred(): return True
        wait(50)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:70]}")
    if not cond: fails.append(name)

ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 820); win.show(); ctl.start()
until(lambda: ctl.engine.ready, 30000)
check("engine ready", ctl.engine.ready)
_scan = ctl.engine.scan
ctl.engine.scan = lambda p: (time.sleep(0.004), _scan(p))[1]        # slow down so there is time to pause
big = Path.home() / "scanme"; big.mkdir(exist_ok=True)
for i in range(3000):
    (big / f"f{i}.txt").write_text(f"file {i}")
pp = win.pages["protection"]; av = pp.av; dash = win.pages["dashboard"]

def exercise(label_, start, controls, kind, show=lambda: None):
    """start → pause → resume → stop with the given controls; checks every other place agrees."""
    start()
    ok = until(lambda: ctl.job is not None and ctl.job.running and ctl.job.stats.scanned > 20, 15000)
    check(f"[{label_}] started", ok, ctl.job.title if ctl.job else None)
    if not ok:
        return
    j = ctl.job
    show(); wait(150)
    check(f"[{label_}] controls show Pause + Stop", controls.b_pause.isVisible() and controls.b_stop.isVisible()
          and not controls.b_resume.isVisible())
    controls.b_pause.click(); wait(400)
    n1, t1 = j.stats.scanned, j.stats.elapsed
    wait(1000)
    show(); wait(100)
    check(f"[{label_}] paused: no more files scanned", j.stats.scanned - n1 <= 4, f"{n1}->{j.stats.scanned}")
    check(f"[{label_}] paused: timer stopped", abs(j.stats.elapsed - t1) < 0.05, f"{t1:.2f}->{j.stats.elapsed:.2f}")
    check(f"[{label_}] Resume visible, Pause hidden", controls.b_resume.isVisible() and not controls.b_pause.isVisible())
    win.go("dashboard"); wait(150)
    check(f"[{label_}] dashboard card shows paused", dash.scan_card.isVisible() and "paused" in dash.scan_title.text(),
          dash.scan_title.text())
    if kind:
        win.go("protection"); pp.open(1); wait(150)
        check(f"[{label_}] its scan row says Paused", av.scan_state_lbls[kind].text().startswith("Paused"),
              av.scan_state_lbls[kind].text())
        others = [k for k in ("quick", "system", "custom") if k != kind]
        check(f"[{label_}] other rows unavailable", all(not av.scan_ctrls[k].b_start.isEnabled() for k in others))
    if hasattr(win, "act_scan_resume"):
        win.refresh()
        check(f"[{label_}] tray: Resume + Stop", win.act_scan_resume.isVisible() and win.act_scan_stop.isVisible()
              and not win.act_scan_pause.isVisible())
    check(f"[{label_}] scan screen headline", win.pages["scan"].headline.text() == "Scan paused",
          win.pages["scan"].headline.text())
    show(); wait(100)
    controls.b_resume.click(); wait(700)
    check(f"[{label_}] resumed: scanning continues", j.stats.scanned > n1 + 5, f"{n1}->{j.stats.scanned}")
    controls.b_stop.click()
    check(f"[{label_}] stopped", until(lambda: not j.running, 15000) and j.cancelled)
    wait(400)
    check(f"[{label_}] scan screen says stopped", win.pages["scan"].headline.text() == "Scan stopped",
          win.pages["scan"].headline.text())
    check(f"[{label_}] log + notification", ctl.events.all()[0]["title"].endswith("stopped"), ctl.events.all()[0]["title"])
    win.go("dashboard"); wait(200)
    check(f"[{label_}] dashboard card gone, tiles available", not dash.scan_card.isVisible()
          and dash.qa["quick"].action.isEnabled())

# 1) Quick Scan from its row, controlled from the same row
win.go("protection"); pp.open(1); wait(200)
exercise("Quick / row", lambda: av.scan_ctrls["quick"].b_start.click(), av.scan_ctrls["quick"], "quick", show=lambda: (win.go("protection"), pp.open(1)))
# 2) System Scan started from the row, controlled from the Dashboard card
win.go("protection"); pp.open(1); wait(200)
exercise("System / dashboard", lambda: (av.scan_ctrls["system"].b_start.click(), wait(300), win.go("dashboard")),
         dash.scan_controls, "system", show=lambda: win.go("dashboard"))
# 3) saved custom scan, controlled from the scan screen
ctl.settings.set("custom_scans", [{"name": "Big folder", "paths": [str(big)]}])
win.go("protection"); pp.open(1); av.refresh(); av.saved.setCurrentRow(0); wait(100)
exercise("Custom (saved) / scan screen", lambda: av.b_run_saved.click(), win.pages["scan"].controls, "custom", show=lambda: win.go("scan"))
# 4) custom scan from the file manager (--scan), controlled from its row
win.go("protection"); pp.open(1); wait(100)
exercise("Custom (file manager) / row", lambda: win.start_scan("custom", [str(big)]), av.scan_ctrls["custom"], "custom", show=lambda: (win.go("protection"), pp.open(1)))
# 5) scheduled scan (a quick scan), controlled from the Quick row
sched = {"enabled": True, "type": "quick", "frequency": "daily", "weekday": 0, "time": "00:00", "last_run": 0}
ctl.settings.set("schedule", sched)
win.go("protection"); pp.open(1); wait(100)
exercise("Scheduled / Quick row", ctl._check_schedule, av.scan_ctrls["quick"], "quick", show=lambda: (win.go("protection"), pp.open(1)))
ctl.settings.set("schedule.enabled", False)
# 6) tray actions
if hasattr(win, "act_scan_pause"):
    win.start_scan("custom", [str(big)]); until(lambda: ctl.job.stats.scanned > 20)
    win.refresh(); win.act_scan_pause.trigger(); wait(300)
    check("tray Pause pauses", ctl.scan_state() == "paused")
    win.refresh(); win.act_scan_resume.trigger(); wait(300)
    check("tray Resume resumes", ctl.scan_state() == "running")
    win.act_scan_stop.trigger(); until(lambda: not ctl.job.running)
    check("tray Stop stops", ctl.job.cancelled)
else:
    print("SKIP tray (no system tray in this session)")
# 7) a full run still finishes normally
j = ctl.start_scan("custom", [str(big)]); until(lambda: not j.running, 60000); wait(300)
check("uninterrupted scan finishes", not j.cancelled and j.stats.scanned >= 3000, j.stats.scanned)
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
