"""Caja (MATE) integration: Scripts entry and caja-actions top-level entry, for files, folders, several items,
names with spaces / wildcards, and the open folder (empty-area right-click). Also checks Files' script and removal."""
import os, sys, subprocess, tempfile
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:100]}")
    if not cond: fails.append(name)

tmp = Path(tempfile.mkdtemp())
log = tmp / "args.log"
fake = tmp / "fake launcher.sh"            # a launcher path with a space, like an AppImage in "My Apps"
fake.write_text(f'#!/bin/sh\n{{ echo ---; for a in "$@"; do echo "[$a]"; done; }} >> "{log}"\n')
fake.chmod(0o755)
os.environ["APPIMAGE"] = str(fake)
from linux_defender import integration as i
i.set_file_manager_integration(True)
check("Caja script installed and executable", os.access(i.CAJA_SCRIPT, os.X_OK), i.CAJA_SCRIPT)
check("caja-actions entry installed", i.FM_ACTION.exists(), i.FM_ACTION)
act = i.FM_ACTION.read_text()
check("caja-actions entry: files and folders", "MimeTypes=all/all;" in act)
check("caja-actions entry: empty-area menu (open folder)", "TargetLocation=true" in act)
check("caja-actions entry: launcher quoted", f'Exec="{fake}" --scan %F' in act, [l for l in act.splitlines() if l.startswith("Exec")])
check("caja-actions shows the entry at the top level",
      "items-create-root-menu=false" in i.CAJA_ACTIONS_CONF.read_text())

d = tmp / "Test Files"; (d / "Some Folder").mkdir(parents=True)
for n in ("my file.txt", "star*.txt", "plain.txt"):
    (d / n).write_text("x")
def run(script, env=None, args=()):
    log.unlink(missing_ok=True)
    e = dict(os.environ); e.update(env or {})
    subprocess.run([str(script), *args], cwd=d, env=e, check=True)
    return [l[1:-1] for l in log.read_text().splitlines() if l.startswith("[")]
sel = [str(d / "my file.txt"), str(d / "star*.txt"), str(d / "Some Folder")]
got = run(i.CAJA_SCRIPT, {"CAJA_SCRIPT_SELECTED_FILE_PATHS": "\n".join(sel) + "\n"}, ["my file.txt", "star*.txt", "Some Folder"])
check("Scripts: several items (spaces, wildcard, folder)", got == ["--scan", *sel], got)
got = run(i.CAJA_SCRIPT, {"CAJA_SCRIPT_SELECTED_FILE_PATHS": ""}, ["my file.txt", "Some Folder"])
check("Scripts: names relative to the open folder", got == ["--scan", str(d / "my file.txt"), str(d / "Some Folder")], got)
got = run(i.CAJA_SCRIPT, {"CAJA_SCRIPT_SELECTED_FILE_PATHS": ""})
check("Scripts: nothing selected scans the open folder", got == ["--scan", str(d)], got)
got = run(i.NAUTILUS_SCRIPT, {"NAUTILUS_SCRIPT_SELECTED_FILE_PATHS": str(d / "my file.txt") + "\n"})
check("Files script keeps a name with spaces whole", got == ["--scan", str(d / "my file.txt")], got)

# a user's own caja-actions choice is respected
i.CAJA_ACTIONS_CONF.write_text("[runtime]\nitems-create-root-menu=true\n")
i.set_file_manager_integration(True)
check("existing caja-actions setting kept", "items-create-root-menu=true" in i.CAJA_ACTIONS_CONF.read_text())

i.set_file_manager_integration(False)
check("turning it off removes the Caja entries", not i.CAJA_SCRIPT.exists() and not i.FM_ACTION.exists())
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
