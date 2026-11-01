"""Quarantine management: items tab (filter, sort, restore), folder tab (move/default/open/limits/empty), rescan.

Needs a ClamAV test signature for the EICAR test file in the signature folder (test.hdb).
"""
import os, sys, time, hashlib
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QTabWidget
app = QApplication([])
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
CHOSEN = {"dir": ""}
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: CHOSEN["dir"])
from linux_defender import paths
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow

HOME = Path.home()
EICAR = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*").encode()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 100):
        if pred(): return True
        wait(100)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:56} {str(detail)[:80]}")
    if not cond: fails.append(name)

def boot():
    ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
    win = MainWindow(ctl); win.resize(1180, 820); win.show(); ctl.start()
    until(lambda: ctl.engine.state == "ready", 30000)
    return ctl, win

ctl, win = boot()
check("engine ready with test signature", ctl.engine.state == "ready", ctl.engine.state)
dl = HOME / "Downloads"; dl.mkdir(exist_ok=True)
for i in range(3):
    (dl / f"eicar{i}.com").write_bytes(EICAR)
job = ctl.start_scan("custom", [str(dl)]); until(lambda: not job.running)
check("3 threats quarantined by a scan", len(ctl.quarantine.items()) == 3, len(ctl.quarantine.items()))
pp = win.pages["protection"]; win.go("protection"); pp.open(2); wait(300)
qp = pp.quar
check("Items tab lists 3", qp.tree.topLevelItemCount() == 3, qp.count_lbl.text())
qp.search.setText("eicar1"); wait(100)
check("filter shows 1 of 3", qp.count_lbl.text() == "1 of 3 item(s)", qp.count_lbl.text())
qp.search.setText(""); wait(100)
check("restore buttons disabled with no selection", not qp.b_restore.isEnabled() and not qp.b_delete.isEnabled())
qp.tabs.setCurrentIndex(1); wait(200)
check("folder tab: default location", qp.loc_lbl.text() == str(paths.QUARANTINE_DIR) and qp.loc_kind.text() == "Default location",
      qp.loc_lbl.text())
check("folder tab: 3 items, size shown", qp.u_items.text() == "3" and qp.u_used.text() != "—", qp.u_used.text())
check("'Use default location' disabled at default", not qp.b_default.isEnabled())

# --- move into a folder that already contains files → subfolder
docs = HOME / "Documents"; docs.mkdir(exist_ok=True); (docs / "notes.txt").write_text("mine")
CHOSEN["dir"] = str(docs)
qp._change_location(); wait(300)
newq = docs / "Linux Defender Quarantine"
check("moved into a subfolder of a non-empty folder", Path(qp.loc_lbl.text()) == newq, qp.loc_lbl.text())
check("3 items now in the new folder", len(list(newq.glob("*.bin"))) == 3 and len(ctl.quarantine.items()) == 3)
check("old folder has no items left", not list(paths.QUARANTINE_DIR.glob("*.bin")))
check("user's own file untouched", (docs / "notes.txt").read_text() == "mine")
check("location saved in settings", ctl.settings.get("quarantine.location") == str(newq), ctl.settings.get("quarantine.location"))
check("custom location label", qp.loc_kind.text() == "Custom location" and qp.b_default.isEnabled())

# --- new detections go to the new folder
(dl / "eicar9.com").write_bytes(EICAR)
job = ctl.start_scan("custom", [str(dl)]); until(lambda: not job.running)
check("new detection stored in the new folder", len(list(newq.glob("*.bin"))) == 4)

# --- restart keeps the location
ctl.shutdown(); win.close(); wait(500)
ctl, win = boot()
check("location kept after restart", ctl.quarantine.root == newq and len(ctl.quarantine.items()) == 4, ctl.quarantine.root)
pp = win.pages["protection"]; win.go("protection"); pp.open(2); wait(300); qp = pp.quar

# --- restore from the custom folder
first = qp.tree.topLevelItem(0); first.setCheckState(0, Qt.Checked); wait(100)
m = first.data(0, 0x0100)
qp._restore(); wait(200)
check("restore from custom folder", Path(m["path"]).read_bytes() == EICAR and len(ctl.quarantine.items()) == 3)
Path(m["path"]).unlink()
ctl.settings.set("exceptions", [])

# --- move to a read-only folder fails safely
ro = HOME / "readonly"; ro.mkdir(exist_ok=True); os.chmod(ro, 0o500)
CHOSEN["dir"] = str(ro); qp.tabs.setCurrentIndex(1); qp._change_location(); wait(200)
if os.geteuid() == 0:
    print("SKIP read-only check (running as root)")
else:
    check("read-only target refused", "not moved" in qp.move_lbl.text(), qp.move_lbl.text())
    check("items intact after refused move", ctl.quarantine.root == newq and len(ctl.quarantine.items()) == 3)
os.chmod(ro, 0o700)
if ctl.quarantine.root != newq:          # root can write anywhere: move back for the next checks
    ctl.move_quarantine(str(newq.parent))

# --- back to default
qp._move(None); wait(300)
check("moved back to default location", ctl.quarantine.root.resolve() == paths.QUARANTINE_DIR.resolve()
      and len(list(paths.QUARANTINE_DIR.glob("*.bin"))) == 3)
check("settings location cleared", ctl.settings.get("quarantine.location") == "")
check("empty custom vault folder removed", not newq.exists())

# --- age limit
old = ctl.quarantine.items()[-1]
ctl.quarantine.update_meta(old["id"], added=time.time() - 45 * 86400)
qp.days.setValue(60); wait(200); qp.days.setValue(30); wait(1600)
check("age limit removes the 45-day-old item", len(ctl.quarantine.items()) == 2, len(ctl.quarantine.items()))

# --- size limit (2 MB items, limit 3 MB → keep newest)
big = []
for i in range(3):
    f = HOME / f"big{i}.bin"; f.write_bytes(os.urandom(2 << 20)); big.append(ctl.quarantine.add(str(f), f"Test.Big{i}"))
    time.sleep(0.05)
check("5 items before size limit", len(ctl.quarantine.items()) == 5, len(ctl.quarantine.items()))
ctl._last_limits = 0; ctl._tick()
check("hourly maintenance keeps items within limits", len(ctl.quarantine.items()) == 5)
qp.maxmb.setValue(3); wait(1600)
ids = {m["id"] for m in ctl.quarantine.items()}
check("size limit keeps vault under 3 MB", ctl.quarantine.disk_usage()["used"] <= 3 << 20, fmt := ctl.quarantine.disk_usage()["used"])
check("newest big item kept", big[-1]["id"] in ids)
qp.maxmb.setValue(0); wait(1300)
f = HOME / "big9.bin"; f.write_bytes(os.urandom(5 << 20))
ctl.settings.set("quarantine.max_size_mb", 1); ctl.quarantine.max_size_mb = 1
nm = ctl.quarantine.add(str(f), "Test.Big9")
check("an item bigger than the limit is still kept when added", nm["id"] in {m["id"] for m in ctl.quarantine.items()})
ctl.settings.set("quarantine.max_size_mb", 0); ctl.quarantine.max_size_mb = 0
ctl.empty_quarantine()

# --- rescan: one real threat + one false positive
(dl / "eicarR.com").write_bytes(EICAR); ctl.quarantine.add(str(dl / "eicarR.com"), "Test.EICAR")
(dl / "report.pdf").write_bytes(b"%PDF-1.4 harmless"); ctl.quarantine.add(str(dl / "report.pdf"), "Heuristics.Fake.FP")
qp.tabs.setCurrentIndex(0); qp.refresh(); wait(200)
qp.b_rescan.click()
until(lambda: qp.rescan_lbl.text().startswith("Rescan finished"), 20000); wait(300)
res = {m["path"].rsplit("/", 1)[-1]: (m.get("rescan") or {}).get("result") for m in ctl.quarantine.items()}
check("rescan: real threat still detected", res.get("eicarR.com") == "threat", res)
check("rescan: false positive no longer detected", res.get("report.pdf") == "clean", res)
check("rescan summary shown", "1 no longer detected" in qp.rescan_lbl.text(), qp.rescan_lbl.text())
check("notification about false positive", ctl.events.all()[0]["title"].startswith("1 quarantined item"),
      ctl.events.all()[0]["title"])
statuses = [qp.tree.topLevelItem(i).text(5) for i in range(qp.tree.topLevelItemCount())]
check("status column filled", any("No longer detected" in s for s in statuses) and any("Still detected" in s for s in statuses), statuses)

# --- empty
qp.tabs.setCurrentIndex(1); qp.b_empty.click(); wait(300)
check("Empty quarantine removes everything", len(ctl.quarantine.items()) == 0 and not qp.b_empty.isEnabled())
win.grab().save(sys.argv[1] if len(sys.argv) > 1 else "/tmp/q.png")
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
