"""Click every on/off switch in the app twice and check it stays at the right edge of its row."""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
from linux_defender.ui.widgets import Toggle
ctl = Controller(); ctl.settings.set("first_run_done", True)
win = MainWindow(ctl); win.resize(1180, 800); win.show()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
# visit every page / sub-page so all switches are laid out
for k in ("dashboard", "protection", "notifications", "settings", "support"):
    win.go(k); wait(150)
pp = win.pages["protection"]
for i in range(1, 6):
    win.go("protection"); pp.open(i); wait(150)
toggles = win.findChildren(Toggle)
bad = 0
for t in toggles:
    # make the switch's tab/page visible so geometry is real
    w = t
    while w is not None:
        p = w.parentWidget()
        if p is not None and hasattr(p, "setCurrentWidget") and hasattr(p, "indexOf") and p.indexOf(w) >= 0:
            p.setCurrentWidget(w)
        w = p
    wait(120)
    before = t.geometry()
    row_w = t.parentWidget().width()
    t.click(); wait(400); t.click(); wait(400)
    after = t.geometry()
    ok = before == after and after.right() > row_w - 80
    bad += not ok
    print(("OK  " if ok else "BAD ") + f"{t.parentWidget().findChildren(type(win.side_status))[0].text()[:45]:45} {before.x():4}->{after.x():4} (row width {row_w})")
print(f"{len(toggles)} switches tested, {bad} bad")
ctl.shutdown()
sys.exit(1 if bad else 0)
