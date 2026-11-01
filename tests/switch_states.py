"""Flip every on/off switch off and on and check that the text/controls that depend on it follow.

Run twice: once with signatures present (engine ready) and once without (engine waiting).
"""
import os, sys
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from linux_defender.controller import Controller
from linux_defender.ui.main_window import MainWindow
ctl = Controller(); ctl.settings.set("first_run_done", True)
win = MainWindow(ctl); win.resize(1180, 800); win.show()
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
ctl.start()
for _ in range(80):
    wait(250)
    if ctl.engine.state not in ("stopped", "loading"):
        break
engine_ready = ctl.engine.state == "ready"
print("engine state:", ctl.engine.state)
pp, sp = win.pages["protection"], win.pages["settings"]
av, sch = pp.av, pp.sched
fails = []

def check(name, cond, detail):
    print(("OK   " if cond else "FAIL ") + f"{name:38} {detail[:110]}")
    if not cond:
        fails.append(name)

def flip(toggle, value, settle=300):
    if toggle.isChecked() != value:
        toggle.click()
    wait(settle)

def until(pred, ms=15000):
    for _ in range(ms // 250):
        if pred():
            return True
        wait(250)
    return pred()

# ---- Shield
win.go("protection"); pp.open(1)
flip(av.shield_toggle, False)
check("Shield off", "turned off" in av.shield_info.text(), av.shield_info.text())
flip(av.shield_toggle, True, 500)
if engine_ready:
    until(lambda: (av.refresh() or True) and "Watching" in av.shield_info.text())
    check("Shield on (engine ready)", "Shield is active" in av.shield_info.text(), av.shield_info.text())
else:
    check("Shield on (no signatures)", "signatures" in av.shield_info.text() and "turned off" not in av.shield_info.text(),
          av.shield_info.text())
flip(av.shield_toggle, False)
check("Shield off again", "turned off" in av.shield_info.text(), av.shield_info.text())
flip(av.shield_toggle, True, 500)
if engine_ready:
    until(lambda: (av.refresh() or True) and "Watching" in av.shield_info.text())
check("Shield on again", "turned off" not in av.shield_info.text(), av.shield_info.text())
win.go("dashboard"); wait(200)
check("Dashboard shows Shield state", win.pages["dashboard"].ov_shield.text() == ctl.shield_state()[1],
      win.pages["dashboard"].ov_shield.text())
check("Tray menu text", "Turn Shield off" == win.act_shield.text() if hasattr(win, "act_shield") else True,
      getattr(getattr(win, "act_shield", None), "text", lambda: "no tray")())

# ---- Advanced
win.go("protection"); pp.open(1)
for t, word in ((av.t_arch, "archives"), (av.t_pua, "unwanted apps"), (av.t_heur, "heuristics"), (av.t_mounts, "other drives")):
    before = av.adv_status.text()
    t.click(); wait(300)
    after = av.adv_status.text()
    check(f"Advanced: {word} toggled", before != after and word in after, after)
    t.click(); wait(300)
if engine_ready:
    until(lambda: (av.refresh() or True) and av.adv_status.text().startswith("Active"), 60000)
    check("Advanced settings applied", av.adv_status.text().startswith("Active"), av.adv_status.text())

# ---- Schedule
pp.open(4); wait(200)
flip(sch.t_en, False)
check("Schedule off", "turned off" in sch.status.text() and not sch.cb_type.isEnabled(), sch.status.text())
flip(sch.t_en, True)
check("Schedule on", sch.status.text().startswith("Next") and sch.cb_type.isEnabled(), sch.status.text())
check("Schedule on: no immediate scan", not (ctl.job and ctl.job.running and ctl.job.kind == "scheduled"), "")

# ---- Settings
win.go("settings"); wait(200)
pairs = [
    (sp.t_upd, lambda: sp.auto_status.text(), "Automatic updates are on", "Automatic updates are off",
     lambda on: sp.cb_int.isEnabled() == on),
    (sp.t_px, lambda: sp.px_status.text(), "Enter the proxy", "directly",
     lambda on: sp.px_host.isEnabled() == on),
    (sp.t_fm, lambda: sp.fm_status.text(), "Installed", "Not installed", None),
    (sp.t_menu, lambda: sp.menu_status.text(), "Installed", "Not installed", None),
    (sp.t_auto, lambda: sp.auto_start_status.text(), "will start", "does not start", None),
    (sp.t_min, lambda: sp.min_status.text(), "stays hidden", "window opens", None),
    (sp.t_notif, lambda: sp.notif_status.text(), "are on", "are off", None),
    (sp.t_tray, lambda: sp.tray_status.text(), "keeps Linux Defender running", "quits", None),
]
for t, txt, on_word, off_word, extra in pairs:
    for v in (False, True, False, True):
        flip(t, v)
        good = (on_word in txt()) if v else (off_word in txt())
        if extra:
            good = good and extra(v)
        check(f"{txt()[:20]}… switch {'on ' if v else 'off'}", good, txt())

print(f"\n{len(fails)} failures")
ctl.shutdown()
sys.exit(1 if fails else 0)
