"""Notifications: unread markers, per-item read, Mark all as read, badge, persistence, new events."""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from linux_defender.controller import Controller
from linux_defender.events import EventStore
from linux_defender.ui.main_window import MainWindow
ctl = Controller(); ctl.settings.set("first_run_done", True)
ctl.events.clear()
for lvl, t in (("info", "Update finished"), ("warning", "Real-time protection turned off"),
               ("info", "Real-time protection turned on"), ("critical", "Threat blocked: Test.EICAR"),
               ("warning", "Update failed")):
    ctl.events.add(lvl, "Test", t, "details for " + t)
win = MainWindow(ctl); win.resize(1180, 800); win.show()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
page = win.pages["notifications"]
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:46} {detail}")
    if not cond: fails.append(name)
def tags():
    return sum(1 for i in range(page.list.count()) if page.list.itemWidget(page.list.item(i)).tag.isVisible())

win.go("notifications"); wait(400)
check("5 unread after opening", ctl.events.unread_count() == 5, page.unread_lbl.text())
check("5 NEW markers shown", tags() == 5, str(tags()))
check("badge shows 5", win.badge.isVisible() and win.badge.text() == "5", win.badge.text())
check("Mark all enabled", page.b_read.isEnabled())
wait(2500)
check("no automatic mark-all after 2.5 s", ctl.events.unread_count() == 5, str(ctl.events.unread_count()))
page.list.setCurrentRow(2); wait(1200)
check("opening one item marks only it", ctl.events.unread_count() == 4 and tags() == 4, page.unread_lbl.text())
check("badge shows 4", win.badge.text() == "4", win.badge.text())
page.b_read.click(); wait(300)
check("Mark all as read → 0 unread", ctl.events.unread_count() == 0, page.unread_lbl.text())
check("all NEW markers gone", tags() == 0, str(tags()))
check("badge hidden", not win.badge.isVisible())
check("Mark all disabled when nothing unread", not page.b_read.isEnabled())
check("persisted to disk", EventStore().unread_count() == 0)
ctl.events.add("critical", "Shield", "Threat blocked: New.Test", "x"); wait(400)
check("new event appears unread while page open", ctl.events.unread_count() == 1 and tags() == 1, page.unread_lbl.text())
check("badge shows 1", win.badge.isVisible() and win.badge.text() == "1", win.badge.text())
check("Mark all re-enabled", page.b_read.isEnabled())
page.fbtn["critical"].click(); wait(300)
check("Critical filter lists critical only", page.list.count() == 2, str(page.list.count()))
page.b_read.click(); wait(300)
check("Mark all from a filter", ctl.events.unread_count() == 0 and tags() == 0, page.unread_lbl.text())
page.fbtn["all"].click(); wait(300)
check("All tab shows 6, none unread", page.list.count() == 6 and tags() == 0, str(page.list.count()))
win.go("dashboard"); wait(200); win.go("notifications"); wait(300)
check("state kept after leaving and returning", tags() == 0 and not page.b_read.isEnabled())
win.grab().save(sys.argv[1] if len(sys.argv) > 1 else "/tmp/notif.png")
print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
