"""Headless smoke test: build the window, visit every page, save screenshots."""
import os, sys, time
if not os.environ.get("APPDIR"): sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = QApplication([])
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow, Onboarding
ctl = Controller(); ctl.settings.set("first_run_done", True)
theme = sys.argv[2] if len(sys.argv) > 2 else "dark"
ctl.settings.set("general.theme", theme)
win = MainWindow(ctl); win.resize(1180, 800); win.show()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
ctl.start()
for _ in range(60):
    wait(500)
    if ctl.engine.state in ("ready", "error", "no_signatures", "no_engine"): break
win.refresh(); wait(300)
def shot(name): wait(400); win.grab().save(f"{out}/{theme}-{name}.png")
for k in ("dashboard", "protection", "notifications", "settings", "support"):
    win.go(k); shot(k)
pp = win.pages["protection"]
for i, n in ((1, "antivirus"), (2, "quarantine"), (3, "exceptions"), (4, "schedule"), (5, "logs")):
    pp.open(i); win.go("protection"); pp.open(i); shot("prot-" + n)
pp.back()
# run a custom scan on Downloads (test signature catches EICAR)
job = ctl.start_scan("custom", [os.path.expanduser("~/Downloads")])
print("job", job)
for _ in range(60):
    wait(300)
    if job and not job.running: break
wait(800); shot("scan-result")
print("threats", [(t.name, t.action) for t in job.threats] if job else None)
win.go("dashboard"); shot("dashboard-after")
win.go("notifications"); shot("notifications-after")
ob = Onboarding(ctl, win); ob.show(); wait(400); ob.grab().save(f"{out}/{theme}-onboarding.png"); ob.close()
ctl.shutdown()
print("ok")
