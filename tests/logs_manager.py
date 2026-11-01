"""Logs manager: list/filter/view, multi-select, Select all/none, move selected, delete selected, retention."""
import os, sys, time, json
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
CHOSEN = {"dir": ""}
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: CHOSEN["dir"])
from linux_defender import paths
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 100):
        if pred(): return True
        wait(100)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:78]}")
    if not cond: fails.append(name)
ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 820); win.show(); ctl.start(); until(lambda: ctl.engine.ready, 30000)
home = Path.home(); dl = home / "Downloads"; dl.mkdir(exist_ok=True)
for i in range(3):
    (dl / f"t{i}.com").write_text(EICAR)
    j = ctl.start_scan("custom", [str(dl)]); until(lambda: not j.running); wait(1100)   # distinct file names
(paths.LOG_DIR / "freshclam.log").write_text("update line 1\nupdate line 2\n")
(paths.LOG_DIR / "freshclam.log.1").write_text("old update log\n")
pp = win.pages["protection"]; win.go("protection"); pp.open(5); wait(300)
lp = pp.logs
rows = lambda: [lp.tree.topLevelItem(i) for i in range(lp.tree.topLevelItemCount())]
visible = lambda: [it for it in rows() if not it.isHidden()]
kinds = sorted({it.data(0, Qt.UserRole).kind for it in rows()})
check("logs listed: scan reports + engine + update", kinds == ["engine", "scan", "update"], kinds)
check("3 scan reports", sum(1 for it in rows() if it.data(0, Qt.UserRole).kind == "scan") == 3)
lp.type_cb.setCurrentIndex(1); wait(100)
check("filter 'Scan reports' shows 3", len(visible()) == 3, lp.count_lbl.text())
lp.type_cb.setCurrentIndex(3); wait(100)
check("filter 'Update logs' shows 2", len(visible()) == 2, [it.text(5) for it in visible()])
lp.type_cb.setCurrentIndex(0); lp.search.setText("archived"); wait(100)
check("search 'archived' finds the rotated log", [it.text(5) for it in visible()] == ["freshclam.log.1"],
      [it.text(5) for it in visible()])
lp.search.setText(""); wait(100)
scan_row = next(it for it in rows() if it.data(0, Qt.UserRole).kind == "scan")
lp.tree.setCurrentItem(scan_row); wait(100)
check("viewing a scan report", "Scanned:" in lp.detail.toPlainText() and "FOUND" not in lp.detail.toPlainText(),
      lp.detail.toPlainText().splitlines()[0])
eng = next(it for it in rows() if it.text(5) == "clamd.log")
lp.tree.setCurrentItem(eng); wait(100)
check("viewing the engine log", len(lp.detail.toPlainText()) > 20, lp.detail.toPlainText()[:60])
lp.b_none.click(); wait(50)
check("nothing selected → move/delete disabled", not lp.b_move.isEnabled() and not lp.b_delete.isEnabled())
lp.b_all.click(); wait(50)
check("Select all", len(lp._selected()) == len(rows()) and lp.sel_lbl.text().startswith(f"{len(rows())} of {len(rows())}"),
      lp.sel_lbl.text())
lp.b_none.click(); wait(50)
check("Select none", not lp._selected())
lp.type_cb.setCurrentIndex(1); wait(50); lp.b_all.click(); wait(50)
check("Select all with a filter selects only visible", len(lp._selected()) == 3, lp.sel_lbl.text())
lp.type_cb.setCurrentIndex(0); wait(50)
check("widening the filter keeps the selection", len(lp._selected()) == 3)
lp.b_all.click(); lp.type_cb.setCurrentIndex(2); wait(50)
check("narrowing the filter unselects hidden rows", len(lp._selected()) == len(visible()), lp.sel_lbl.text())
lp.type_cb.setCurrentIndex(0); lp.b_none.click(); wait(50)
# move: two scan reports + the in-use update log
r = [it for it in rows() if it.data(0, Qt.UserRole).kind == "scan"]
r[0].setCheckState(0, Qt.Checked); r[1].setCheckState(0, Qt.Checked)
next(it for it in rows() if it.text(5) == "freshclam.log").setCheckState(0, Qt.Checked); wait(50)
check("3 ticked", len(lp._selected()) == 3, lp.sel_lbl.text())
lp.tree.setCurrentItem(next(it for it in rows() if it.text(5) == "clamd.log")); wait(100)
check("viewing another log keeps the 3 ticks", len(lp._selected()) == 3, lp.sel_lbl.text())
lp.tree.clearSelection(); r[0].setSelected(True); r[2].setSelected(True); wait(50)
check("Ctrl/Shift-selecting rows ticks exactly those", len(lp._selected()) == 2, lp.sel_lbl.text())
lp.b_none.click(); r[0].setCheckState(0, Qt.Checked); r[1].setCheckState(0, Qt.Checked)
next(it for it in rows() if it.text(5) == "freshclam.log").setCheckState(0, Qt.Checked); wait(50)
names = sorted(e.path.name for e in lp._selected())
dest = home / "old-logs"; CHOSEN["dir"] = str(dest)
lp.b_move.click(); wait(300)
check("moved files arrive in the folder", sorted(p.name for p in dest.iterdir()) == names, sorted(p.name for p in dest.iterdir()))
check("moved scan reports left the logs folder", len(list(paths.SCAN_LOG_DIR.glob("*.json"))) == 1)
fl = paths.LOG_DIR / "freshclam.log"
check("in-use update log copied, then emptied (not deleted)", fl.exists() and fl.stat().st_size == 0
      and (dest / "freshclam.log").read_text().startswith("update line 1"))
check("move message", lp.action_lbl.text().startswith("Moved 3 log file(s)"), lp.action_lbl.text())
CHOSEN["dir"] = str(paths.SCAN_LOG_DIR); lp.b_all.click(); lp.b_move.click(); wait(100)
check("moving into the logs folder itself is refused", "outside the logs folder" in lp.action_lbl.text(), lp.action_lbl.text())
lp.b_none.click()
# delete: the remaining scan report + the in-use engine log
next(it for it in rows() if it.data(0, Qt.UserRole).kind == "scan").setCheckState(0, Qt.Checked)
next(it for it in rows() if it.text(5) == "clamd.log").setCheckState(0, Qt.Checked); wait(50)
lp.b_delete.click(); wait(300)
cl = paths.LOG_DIR / "clamd.log"
check("Delete selected: scan report gone", not list(paths.SCAN_LOG_DIR.glob("*.json")))
check("in-use engine log emptied, not deleted", cl.exists() and cl.stat().st_size == 0)
(dl / "t9.com").write_text(EICAR); ctl.engine.scan(str(dl / "t9.com")); wait(500)
check("scan engine keeps logging into the same file", cl.stat().st_size > 0, cl.stat().st_size)
check("delete message", lp.action_lbl.text().startswith("Deleted 2 log file(s)"), lp.action_lbl.text())
# retention: age and count
for i, age in enumerate((40, 20, 10, 1)):
    f = paths.SCAN_LOG_DIR / f"2026010{i}-000000-custom.json"
    f.write_text(json.dumps({"kind": "custom", "targets": [], "started": time.time() - age * 86400,
                             "finished": time.time() - age * 86400 + 5, "scanned": 1, "infected": 0, "resolved": 0}))
lp.refresh(); lp.tabs.setCurrentIndex(1); wait(100)
lp.days.setValue(31); wait(100); lp.days.setValue(30); wait(1600)
check("age rule removes the 40-day-old report", len(list(paths.SCAN_LOG_DIR.glob("*.json"))) == 3)
check("archived update log older? kept (new)", (paths.LOG_DIR / "freshclam.log.1").exists())
lp.maxn.setValue(2); wait(1600)
left = sorted(json.loads(p.read_text())["started"] for p in paths.SCAN_LOG_DIR.glob("*.json"))
check("count rule keeps the 2 newest reports", len(left) == 2 and left[0] > time.time() - 15 * 86400, len(left))
check("retention event in Notifications", any(e["module"] == "Logs" for e in ctl.events.all()))
# delete all
lp.b_clear.click(); wait(300)
check("Delete all logs", not list(paths.SCAN_LOG_DIR.glob("*.json")) and not (paths.LOG_DIR / "freshclam.log.1").exists()
      and cl.exists())
# notifications: 'Open scan log' hidden for a deleted report
win.go("notifications"); wait(200); np_ = win.pages["notifications"]
idx = next((i for i in range(np_.list.count()) if np_.list.item(i).data(0x0100).get("data", {}).get("log")), None)
if idx is not None:
    np_.list.setCurrentRow(idx); wait(100)
    check("notification hides 'Open scan log' for a deleted report", not np_.d_open.isVisible())
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
