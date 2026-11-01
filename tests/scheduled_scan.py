"""Scheduled scans: stop / pause / resume a running scheduled scan, skip a waiting or upcoming one, undo skip."""
import os, sys, time
from datetime import datetime, timedelta
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 100):
        if pred(): return True
        wait(100)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:60} {str(detail)[:76]}")
    if not cond: fails.append(name)
ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 860); win.show(); ctl.start(); until(lambda: ctl.engine.ready, 30000)
_scan = ctl.engine.scan
ctl.engine.scan = lambda p: (time.sleep(0.02), _scan(p))[1]
pp = win.pages["protection"]; sp = pp.sched
def schedule(minutes_from_now, last_run=0, skip=0):
    t = datetime.now() + timedelta(minutes=minutes_from_now)
    if t.date() != datetime.now().date():                 # keep "today" near midnight
        t = datetime.now().replace(hour=23, minute=59) if minutes_from_now > 0 else datetime.now().replace(hour=0, minute=0)
    ctl.settings.set("schedule", {"enabled": True, "type": "quick", "frequency": "daily", "weekday": 0,
                                  "time": t.strftime("%H:%M"), "last_run": last_run, "skip_ts": skip, "last_ran": 0})
def show():
    win.go("protection"); pp.open(4); wait(200); sp.refresh(); wait(100)

# 1) running scheduled scan: pause, resume, stop
schedule(-1)
ctl._check_schedule(); wait(500)
j = ctl.job
check("scheduled scan starts when due", j is not None and j.running and j.kind == "scheduled", j.title if j else None)
show()
c = sp.sched_controls
check("status: running", "is running" in sp.run_lbl.text(), sp.run_lbl.text())
check("Pause + Stop shown on the Scheduled scans page", c.b_pause.isVisible() and c.b_stop.isVisible())
check("Skip button hidden while running", not sp.b_skip.isVisible())
c.b_pause.click(); wait(400); show()
check("Pause → status paused", "is paused" in sp.run_lbl.text() and c.b_resume.isVisible(), sp.run_lbl.text())
c.b_resume.click(); wait(400); show()
check("Resume → running again", "is running" in sp.run_lbl.text() and c.b_pause.isVisible())
c.b_stop.click()
check("Stop ends the scheduled scan", until(lambda: not j.running, 15000) and j.cancelled)
wait(400); show()
check("logged as stopped", ctl.events.all()[0]["title"].startswith("Scheduled Quick Scan stopped"), ctl.events.all()[0]["title"])
ctl._check_schedule(); wait(300)
check("a stopped scheduled scan does not restart the same day", ctl.job is j)
check("status shows the next run (tomorrow)", "Next scheduled scan" in sp.run_lbl.text(), sp.run_lbl.text())

# 2) waiting behind another scan → Skip this run
big = Path.home() / "scanme"; big.mkdir(exist_ok=True)
for i in range(1500):
    (big / f"f{i}").write_text(str(i))
other = ctl.start_scan("custom", [str(big)]); wait(300)
schedule(-1)
ctl._check_schedule(); wait(100)
show()
check("due while another scan runs → waiting", ctl.scheduled_state()["state"] == "waiting" and "waiting for the Custom Scan"
      in sp.run_lbl.text(), sp.run_lbl.text())
check("'Skip this run' offered", sp.b_skip.isVisible() and sp.b_skip.text() == "Skip this run")
sp.b_skip.click(); wait(200); show()
check("skipped while waiting", ctl.scheduled_state()["state"] == "skipped_due" and sp.b_unskip.isVisible(), sp.run_lbl.text())
ctl.stop_scan(); until(lambda: not other.running); wait(300)
ctl._check_schedule(); wait(300)
check("skipped scan does not start after the other scan ends", ctl.job is other)
check("skip used up: schedule continues normally", ctl.scheduled_state()["state"] == "scheduled"
      and not ctl.settings.get("schedule.skip_ts"))

# 3) upcoming scan: Skip next scan / Undo skip
schedule(+90, last_run=time.time())
show()
first = ctl.next_scheduled_run()
check("upcoming scan listed", ctl.scheduled_state()["state"] == "scheduled" and sp.b_skip.text() == "Skip next scan",
      first)
sp.b_skip.click(); wait(200); show()
nxt = ctl.next_scheduled_run()
check("Skip next scan → next run moves to the following day", nxt and (nxt - first).days == 1, nxt)
check("status says it will be skipped", "will be skipped" in sp.run_lbl.text() and sp.b_unskip.isVisible(), sp.run_lbl.text())
check("schedule itself stays on", sp.t_en.isChecked() and ctl.settings.get("schedule.enabled"))
sp.b_unskip.click(); wait(200); show()
check("Undo skip restores the original next run", ctl.next_scheduled_run() == first and sp.b_skip.isVisible())
sp.b_skip.click(); wait(100)
sp.cb_type.setCurrentIndex(1); wait(200)                        # change the schedule (System Scan)
check("changing the schedule clears the skip", not ctl.settings.get("schedule.skip_ts"))

# 4) skipped scan whose time arrives → nothing runs, skip used up
schedule(-1)
due = ctl._due_now(); ctl.settings.set("schedule.skip_ts", due.timestamp())
ctl._check_schedule(); wait(300)
check("skipped time arrives → no scan", ctl.job is other and not ctl.settings.get("schedule.skip_ts"))
# 5) scheduled scan stopped from the Dashboard card too
schedule(-1); ctl._check_schedule(); wait(500)
j3 = ctl.job
win.go("dashboard"); wait(200)
win.pages["dashboard"].scan_controls.b_stop.click()
check("Dashboard Stop also stops a scheduled scan", until(lambda: not j3.running, 15000) and j3.kind == "scheduled" and j3.cancelled)
# 6) turning the schedule off
show(); sp.t_en.setChecked(False); wait(200)
check("schedule off → status off, no buttons", "turned off" in sp.run_lbl.text() and not sp.b_skip.isVisible())
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
