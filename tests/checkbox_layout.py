"""Checkboxes in Logs and Quarantine lists sit in their own column and never cover any text."""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication
app = QApplication([])
from linux_defender import paths
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:70]}")
    if not cond: fails.append(name)
ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
(paths.LOG_DIR / "freshclam.log").write_text("x\n")
f = Path.home() / "a.exe"; f.write_text("a"); ctl.quarantine.add(str(f), "Test.A")
win = MainWindow(ctl); win.resize(1180, 820); win.show()
pp = win.pages["protection"]
for idx, name in ((5, "Logs"), (2, "Quarantine")):
    win.go("protection"); pp.open(idx); wait(300)
    tree = pp.stack.currentWidget().tree
    it = tree.topLevelItem(0)
    cb_rect = tree.visualItemRect(it)
    col0 = tree.header().sectionSize(0)
    text_x = tree.header().sectionPosition(1)
    check(f"{name}: checkbox column has no text", it.text(0) == "", repr(it.text(0)))
    check(f"{name}: first text column starts after the checkbox column", text_x >= col0 and col0 >= 30, f"col0={col0} text_x={text_x}")
    # the indicator is drawn inside column 0
    from PySide6.QtWidgets import QStyleOptionViewItem, QStyle
    opt = QStyleOptionViewItem(); opt.rect = tree.visualRect(tree.indexFromItem(it, 0))
    opt.features |= QStyleOptionViewItem.HasCheckIndicator
    ind = tree.style().subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, tree)
    check(f"{name}: checkbox drawn inside its own column", ind.right() < text_x, f"indicator right={ind.right()} text_x={text_x}")
    full = tree.topLevelItem(0).text(1)
    w = tree.fontMetrics().horizontalAdvance(full) + 12
    check(f"{name}: first text column wide enough for its text", tree.columnWidth(1) >= w - 2, f"{tree.columnWidth(1)} vs {w}")
    win.grab().save(f"{sys.argv[1] if len(sys.argv) > 1 else '/tmp'}/cb-{name}.png")
print(f"\n{len(fails)} failures")
sys.exit(1 if fails else 0)
