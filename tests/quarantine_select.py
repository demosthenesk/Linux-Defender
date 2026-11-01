"""Quarantine multi-select: checkboxes, Select all / none, filter + select all, restore/delete selected, conflicts."""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
CHOICE = {"conflict": "Keep both", "dir": ""}
def _exec(self):
    for b in self.buttons():
        if b.text() == CHOICE["conflict"]:
            b.click()
    return 0
QMessageBox.exec = _exec
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: CHOICE["dir"])
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:56} {str(detail)[:80]}")
    if not cond: fails.append(name)
ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 820); win.show()
home = Path.home(); dl = home / "Downloads"; dl.mkdir(exist_ok=True)
names = ["alpha.exe", "beta.js", "gamma.doc", "delta.exe", "eps.sh"]
for n in names:
    (dl / n).write_text("content of " + n)
    ctl.quarantine.add(str(dl / n), "Test." + n.split(".")[1].upper())
pp = win.pages["protection"]; win.go("protection"); pp.open(2); wait(300)
qp = pp.quar
def rows():
    return [qp.tree.topLevelItem(i) for i in range(qp.tree.topLevelItemCount())]
def checked():
    return [it for it in rows() if it.checkState(0) == Qt.Checked]
check("5 items listed with checkboxes", len(rows()) == 5 and all(it.flags() & Qt.ItemIsUserCheckable for it in rows()))
check("nothing selected: actions disabled", not qp.b_restore.isEnabled() and not qp.b_delete.isEnabled()
      and not qp.b_restore_to.isEnabled() and qp.b_all.isEnabled() and not qp.b_none.isEnabled())
qp.b_all.click(); wait(100)
check("Select all → 5 ticked", len(checked()) == 5 and len(qp._selected()) == 5, qp.sel_lbl.text())
check("label '5 of 5 selected'", qp.sel_lbl.text() == "5 of 5 selected", qp.sel_lbl.text())
check("button shows count", qp.b_restore.text() == "Restore selected (5)", qp.b_restore.text())
check("Select all disabled when all selected", not qp.b_all.isEnabled())
qp.b_none.click(); wait(100)
check("Select none → 0", len(checked()) == 0 and not qp._selected() and not qp.b_restore.isEnabled())
r = rows(); r[0].setCheckState(0, Qt.Checked); r[2].setCheckState(0, Qt.Checked); wait(100)
check("ticking 2 checkboxes selects 2 items", len(qp._selected()) == 2 and qp.sel_lbl.text() == "2 of 5 selected",
      qp.sel_lbl.text())
qp.tree.setCurrentItem(r[4]); wait(100)
check("clicking another row keeps the ticks", len(qp._selected()) == 2 and r[4].checkState(0) == Qt.Unchecked,
      qp.sel_lbl.text())
qp.b_none.click(); qp.tree.clearSelection(); wait(50); r[1].setSelected(True); r[3].setSelected(True); wait(100)
check("row selection (Ctrl+click) ticks checkboxes", {it.text(2) for it in checked()} == {r[1].text(2), r[3].text(2)},
      [it.text(2) for it in checked()])
qp.b_none.click(); qp.search.setText(".exe"); wait(100)
qp.b_all.click(); wait(100)
check("filter + Select all selects only visible rows", len(qp._selected()) == 2 and qp.sel_lbl.text() == "2 of 2 selected",
      qp.sel_lbl.text())
# restore selected (.exe files) to original location
qp.b_restore.click(); wait(300)
check("Restore selected → 2 restored to original place", (dl / "alpha.exe").exists() and (dl / "delta.exe").exists()
      and len(ctl.quarantine.items()) == 3, qp.action_lbl.text())
check("result message", qp.action_lbl.text().startswith("Restored 2 item(s)"), qp.action_lbl.text())
check("restored files added to exceptions", {e["path"] for e in ctl.settings.get("exceptions")} >=
      {str(dl / "alpha.exe"), str(dl / "delta.exe")})
qp.search.setText(""); wait(100)
# restore selected to a folder, with a name conflict → Keep both
dest = home / "restored"; dest.mkdir(exist_ok=True); (dest / "beta.js").write_text("already here")
CHOICE["dir"] = str(dest); CHOICE["conflict"] = "Keep both"
qp.b_all.click(); wait(100)
qp.b_restore_to.click(); wait(300)
files = sorted(p.name for p in dest.iterdir())
check("Restore selected to… folder (3 items)", len(ctl.quarantine.items()) == 0 and len(files) == 4, files)
check("conflict 'Keep both' kept original + renamed copy", (dest / "beta.js").read_text() == "already here"
      and (dest / "beta (1).js").read_text() == "content of beta.js", files)
# delete selected + skip conflicts
for n in ("x1.sh", "x2.sh", "x3.sh"):
    (dl / n).write_text(n); ctl.quarantine.add(str(dl / n), "Test.SH")
qp.refresh(); wait(100)
r = rows(); r[0].setCheckState(0, Qt.Checked); wait(50)
qp.b_delete.click(); wait(200)
check("Delete selected removes only the checked item", len(ctl.quarantine.items()) == 2, qp.action_lbl.text())
left = [Path(m["path"]) for m in ctl.quarantine.items()]
for p_ in left:
    p_.write_text("new")
CHOICE["conflict"] = "Skip those"
qp.b_all.click(); qp.b_restore.click(); wait(200)
check("conflict 'Skip those' leaves items in quarantine", len(ctl.quarantine.items()) == 2
      and "Skipped 2" in qp.action_lbl.text(), qp.action_lbl.text())
CHOICE["conflict"] = "Replace"
qp.b_all.click(); qp.b_restore.click(); wait(200)
check("conflict 'Replace' overwrites", len(ctl.quarantine.items()) == 0 and all(p_.read_text() == p_.name for p_ in left),
      qp.action_lbl.text())
win.grab().save(sys.argv[1] if len(sys.argv) > 1 else "/tmp/qs.png")
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
