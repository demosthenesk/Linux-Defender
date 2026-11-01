"""Every number / time field shows its whole value (longest value, special text, suffix), next to its arrows."""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import (QApplication, QAbstractSpinBox, QSpinBox, QDateTimeEdit, QTabWidget, QStyle,
                               QStyleOptionSpinBox)
app = QApplication([])
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:62} {str(detail)[:80]}")
    if not cond: fails.append(name)

def longest_texts(sb):
    if isinstance(sb, QDateTimeEdit):
        return [sb.displayFormat().replace("HH", "23").replace("mm", "59").replace("ss", "59")]
    out = [sb.prefix() + sb.textFromValue(v) + sb.suffix() for v in (sb.minimum(), sb.maximum(), sb.value())]
    if sb.specialValueText():
        out.append(sb.specialValueText())
    return out

def check_box(where, sb, seen):
    if id(sb) in seen or not sb.isVisible():
        return
    seen.add(id(sb))
    le = sb.lineEdit()
    fm = le.fontMetrics()
    need = max(fm.horizontalAdvance(t) for t in longest_texts(sb))
    avail = le.contentsRect().width() - 4            # QLineEdit's own horizontal margin
    opt = QStyleOptionSpinBox(); sb.initStyleOption(opt)
    up = sb.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxUp, sb)
    name = f"{where}: {type(sb).__name__} '{max(longest_texts(sb), key=len)}'"
    check(name + " fits", avail >= need, f"text needs {need}px, editor has {avail}px (widget {sb.width()}px)")
    check(name + " not under arrows", le.geometry().right() <= up.left() + 1 or up.width() <= 0,
          f"editor right={le.geometry().right()} arrows left={up.left()}")

ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
win = MainWindow(ctl); win.resize(1180, 820); win.show(); wait(300)
seen = set()
def sweep(where):
    wait(150)
    for sb in win.findChildren(QAbstractSpinBox):
        check_box(where, sb, seen)
    for tw in win.findChildren(QTabWidget):
        if not tw.isVisible():
            continue
        for i in range(tw.count()):
            tw.setCurrentIndex(i); wait(120)
            for sb in win.findChildren(QAbstractSpinBox):
                check_box(f"{where}/{tw.tabText(i)}", sb, seen)
        tw.setCurrentIndex(0)

for key in win.pages:
    win.go(key); sweep(key)
    if key == "protection":
        pp = win.pages["protection"]
        for idx in range(pp.stack.count()):
            pp.open(idx); sweep(f"protection[{idx}]")
# narrow window too: fields must not shrink below their content
win.resize(900, 700)
seen.clear()
for idx in range(win.pages["protection"].stack.count()):
    win.go("protection"); win.pages["protection"].open(idx); sweep(f"narrow protection[{idx}]")
win.go("settings"); sweep("narrow settings")
# light theme
win.resize(1180, 820); win.apply_theme("light"); wait(200)
seen.clear()
for idx in range(win.pages["protection"].stack.count()):
    win.go("protection"); win.pages["protection"].open(idx); sweep(f"light protection[{idx}]")
win.apply_theme("dark")
total = len([1 for sb in win.findChildren(QAbstractSpinBox)])
print(f"\n{total} number/time fields in the app; {len(fails)} failure(s)")
ctl.shutdown() if hasattr(ctl, "shutdown") else None
sys.exit(1 if fails else 0)
