"""Running scan's report is locked (running and paused), unlocked when finished/stopped; one scan at a time."""
import os, sys, time, json, stat, threading
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
BOXES = []
def _exec(self):
    BOXES.append(self.text()); return 0
QMessageBox.exec = _exec
from linux_defender import paths, logs as L
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
win = MainWindow(ctl); win.resize(1180, 820); win.show(); ctl.start(); until(lambda: ctl.engine.ready, 30000)
_scan = ctl.engine.scan
ctl.engine.scan = lambda p: (time.sleep(0.03), _scan(p))[1]
big = Path.home() / "scanme"; big.mkdir(exist_ok=True)
for i in range(2500):
    (big / f"f{i}").write_text(str(i))
# an older finished report, for the retention check
old = paths.SCAN_LOG_DIR / "20260101-000000-custom.json"
old.write_text(json.dumps({"kind": "custom", "status": "finished", "started": time.time() - 5 * 86400,
                           "finished": time.time() - 5 * 86400 + 3, "scanned": 1, "infected": 0, "resolved": 0}))
job = ctl.start_scan("custom", [str(big)])
rep = Path(job.log_file)
wait(300)
d = json.loads(rep.read_text())
check("report exists as soon as the scan starts", rep.exists() and d["status"] == "running", d.get("status"))
check("report is locked while running", L.is_locked(rep))
check("report is read-only while running", stat.S_IMODE(rep.stat().st_mode) == 0o444, oct(stat.S_IMODE(rep.stat().st_mode)))
until(lambda: json.loads(rep.read_text() or "{}").get("scanned", 0) > 100, 10000)
check("report is updated during the scan", json.loads(rep.read_text())["scanned"] > 100)
# Logs page
pp = win.pages["protection"]; win.go("protection"); pp.open(5); wait(400)
lp = pp.logs
rows = lambda: [lp.tree.topLevelItem(i) for i in range(lp.tree.topLevelItemCount())]
row = next(it for it in rows() if it.text(5) == rep.name)
check("Logs: running report shown as locked", "locked" in row.text(3) and "(running)" in row.text(2), row.text(2))
check("Logs: locked row has no checkbox", not (row.flags() & Qt.ItemIsUserCheckable))
lp.b_all.click(); wait(100)
check("Select all skips the locked report", rep.name not in [e.path.name for e in lp._selected()], lp.sel_lbl.text())
lp.b_delete.click(); wait(300)
check("Delete selected leaves the locked report", rep.exists(), lp.action_lbl.text())
e = next(x for x in L.list_logs() if x.path == rep)
n, failed = L.delete_logs([e])
check("delete refused by the log manager", rep.exists() and n == 0 and "running scan" in failed[0], failed)
moved, failed = L.move_logs([e], Path.home() / "out")
check("move refused by the log manager", rep.exists() and not moved and failed, failed)
old.write_text(json.dumps({"kind": "custom", "status": "finished", "started": time.time() - 5 * 86400,
                           "finished": time.time() - 5 * 86400 + 3, "scanned": 1, "infected": 0, "resolved": 0}))
ctl.settings.set("logs.max_age_days", 1); ctl.settings.set("logs.max_scan_logs", 1)
ctl.apply_log_retention()
check("retention rules skip the locked report", rep.exists() and not old.exists())
lp.tabs.setCurrentIndex(1); lp.b_clear.click(); wait(300)
check("Delete all logs keeps the locked report", rep.exists() and "in use by the running scan" in lp.action_lbl.text(),
      lp.action_lbl.text())
ctl.settings.set("logs.max_age_days", 90); ctl.settings.set("logs.max_scan_logs", 500)
check("scan still running before the outside-delete check", job.running)
os.unlink(rep)
check("report written again if deleted from outside", until(lambda: rep.exists(), 4000) and L.is_locked(rep))
# paused
ctl.pause_scan(); wait(2600)
d = json.loads(rep.read_text())
check("paused: report says paused", d["status"] == "paused", d["status"])
check("paused: report still locked", L.is_locked(rep))
lp.tabs.setCurrentIndex(0); lp.refresh(); wait(200)
row = next(it for it in rows() if it.text(5) == rep.name)
check("Logs: paused report locked", "(paused)" in row.text(2) and not (row.flags() & Qt.ItemIsUserCheckable), row.text(2))
e = next(x for x in L.list_logs() if x.path == rep)
check("paused: delete refused", L.delete_logs([e])[0] == 0 and rep.exists())
# one scan at a time
BOXES.clear()
check("controller refuses a second scan", ctl.start_scan("quick") is None and ctl.job is job)
win.start_scan("quick"); wait(100)
check("window: second Quick Scan refused with a message", BOXES and "Only one scan can run at a time" in BOXES[-1], BOXES[-1][:60] if BOXES else "")
win.start_scan("system"); win.handle("action:custom"); wait(100)
check("System scan and Custom scan refused too", len(BOXES) == 3 and ctl.job is job, len(BOXES))
win.handle("scan:" + str(big)); wait(100)
check("file-manager scan refused", len(BOXES) == 4 and ctl.job is job)
ctl.settings.set("schedule", {"enabled": True, "type": "quick", "frequency": "daily", "weekday": 0, "time": "00:00", "last_run": 0})
ctl._check_schedule()
check("scheduled scan waits (does not start a second scan)", ctl.job is job)
ctl.settings.set("schedule.enabled", False)
check("refusals logged in Notifications", sum(1 for x in ctl.events.all() if "not started" in x["title"]) >= 4)
win.go("dashboard"); wait(100)
check("dashboard start tiles disabled", not win.pages["dashboard"].qa["quick"].action.isEnabled())
# stop → unlocked
ctl.resume_scan(); wait(300); ctl.stop_scan(); until(lambda: not job.running); wait(500)
d = json.loads(rep.read_text())
check("stopped: final report written", d["status"] == "stopped" and d["finished"], d["status"])
check("stopped: report unlocked", not L.is_locked(rep))
check("stopped: report writable again", stat.S_IMODE(rep.stat().st_mode) == 0o644, oct(stat.S_IMODE(rep.stat().st_mode)))
win.go("protection"); pp.open(5); lp.refresh(); wait(200)
row = next(it for it in rows() if it.text(5) == rep.name)
check("Logs: stopped report selectable", bool(row.flags() & Qt.ItemIsUserCheckable) and "locked" not in row.text(3))
row.setCheckState(0, Qt.Checked); wait(50); lp.b_delete.click(); wait(200)
check("stopped report can be deleted", not rep.exists(), lp.action_lbl.text())
# simultaneous start requests
results = []
barrier = threading.Barrier(5)
def go():
    barrier.wait(); results.append(ctl.start_scan("custom", [str(big)]))
ts = [threading.Thread(target=go) for _ in range(5)]
[t.start() for t in ts]; [t.join() for t in ts]
started = [r for r in results if r is not None]
check("5 simultaneous start requests → exactly 1 scan", len(started) == 1, len(started))
j2 = started[0]
wait(500)
# natural finish → unlocked
ctl.engine.scan = _scan
until(lambda: not j2.running, 120000); wait(500)
r2 = Path(j2.log_file); d = json.loads(r2.read_text())
check("finished: status finished + unlocked", d["status"] == "finished" and not L.is_locked(r2), d["status"])
# a crashed session leaves an unlocked 'running' report → interrupted, deletable
crash = paths.SCAN_LOG_DIR / "20260102-000000-quick.json"
crash.write_text(json.dumps({"kind": "quick", "status": "running", "started": time.time() - 60, "scanned": 5}))
ce = next(x for x in L.list_logs() if x.path == crash)
check("crashed scan's report: 'interrupted', not locked", "(interrupted)" in ce.title and not ce.locked, ce.title)
check("crashed scan's report can be deleted", L.delete_logs([ce])[0] == 1 and not crash.exists())
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
