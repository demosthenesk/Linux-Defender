"""Click every visible button on every page/tab (dialogs stubbed) and report buttons whose click raises."""
import os, sys, traceback
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QPushButton, QTabWidget, QDialog
from PySide6.QtGui import QDesktopServices
app = QApplication([])
errors = []
sys.excepthook = lambda t, v, tb: errors.append("".join(traceback.format_exception(t, v, tb)))
# stub every modal so clicks never block
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: ([], ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QDialog.exec = lambda self: 0
QDesktopServices.openUrl = staticmethod(lambda *a, **k: True)
from linux_defender import integration
integration.open_url = lambda url: None
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
ctl = Controller(); ctl.settings.set("first_run_done", True)
ctl.open_url = lambda url: None
ctl.update_now = lambda silent=False: None          # no network in tests
ctl.engine.restart = lambda: None
win = MainWindow(ctl); win.resize(1180, 800); win.show()
win.quit = lambda: None
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
ctl.start()
for _ in range(60):
    wait(250)
    if ctl.engine.state not in ("stopped", "loading"):
        break
print("engine:", ctl.engine.state)
SKIP = {"Stop", "Pause", "Finish"}
clicked = 0
pp = win.pages["protection"]

def locations():
    """(name, function that navigates there)"""
    out = []
    for page in ("dashboard", "notifications", "settings", "support"):
        tabs = win.pages[page].findChildren(QTabWidget)
        for ti in range(tabs[0].count() if tabs else 1):
            def go(page=page, ti=ti, tabs=tabs):
                win.go(page)
                if tabs: tabs[0].setCurrentIndex(ti)
            out.append((f"{page}/tab{ti}", go))
    out.append(("protection/home", lambda: (win.go("protection"), pp.back())))
    for i in range(1, 6):
        w = pp.stack.widget(i)
        tabs = w.findChildren(QTabWidget)
        for ti in range(tabs[0].count() if tabs else 1):
            def go(i=i, ti=ti, tabs=tabs):
                win.go("protection"); pp.open(i)
                if tabs: tabs[0].setCurrentIndex(ti)
            out.append((f"protection/{i}/tab{ti}", go))
    return out

for where, go in locations():
    go(); wait(150)
    page_widget = win.stack.currentWidget()
    names = [b.text().strip() for b in page_widget.findChildren(QPushButton)
             if b.isVisible() and b.objectName() != "Nav" and b.text().strip() not in SKIP]
    seen = {}
    for name in names:
        go(); wait(80)
        # buttons can be rebuilt by a refresh (e.g. dashboard "Fix" buttons): look them up again
        idx = seen.get(name, 0); seen[name] = idx + 1
        same = [x for x in win.stack.currentWidget().findChildren(QPushButton)
                if x.isVisible() and x.text().strip() == name]
        if idx >= len(same):
            continue
        b = same[idx]
        label_ = name
        if not b.isEnabled():
            print(f"       [{where}] '{label_}' disabled")
            continue
        n = len(errors)
        print(f"click  [{where}] '{label_}'", flush=True)
        b.click(); wait(80)
        clicked += 1
        started = ctl.job is not None and ctl.job.running
        if len(errors) > n:
            print(f"ERROR  [{where}] button '{label_}': " + errors[-1].strip().splitlines()[-1])
        else:
            print(f"ok     [{where}] '{label_}'" + ("  → scan started" if started else ""))
        if started:                                    # stop it so the next scan buttons are testable
            ctl.job.stop()
            for _ in range(80):
                wait(100)
                if not ctl.job.running:
                    break
            wait(300)
            win.go("dashboard")
print(f"{clicked} button clicks, {len(errors)} errors")
ctl.shutdown()
sys.exit(1 if errors else 0)
