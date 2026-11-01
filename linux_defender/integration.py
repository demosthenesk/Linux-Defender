"""Desktop integration: autostart, applications menu, file-manager "Scan with" actions, URLs."""
import os
import shlex
import shutil
import webbrowser
from pathlib import Path

from linux_defender import APP_NAME, APP_ID

HOME = Path.home()
AUTOSTART = HOME / ".config/autostart" / f"{APP_ID}.desktop"
NAUTILUS_SCRIPT = HOME / ".local/share/nautilus/scripts" / f"Scan with {APP_NAME}"
NEMO_ACTION = HOME / ".local/share/nemo/actions" / f"{APP_ID}-scan.nemo_action"
DOLPHIN_MENU = HOME / ".local/share/kio/servicemenus" / f"{APP_ID}-scan.desktop"
# Caja (MATE): Scripts submenu (always available) and a top-level entry through caja-actions
CAJA_SCRIPT = HOME / ".config/caja/scripts" / f"Scan with {APP_NAME}"
FM_ACTION = HOME / ".local/share/file-manager/actions" / f"{APP_ID}-scan.desktop"
CAJA_ACTIONS_CONF = HOME / ".config/caja-actions/caja-actions.conf"


def _menu_icon() -> str:
    """Linux Defender's shield for the right-click entries (absolute path; falls back to a theme icon)."""
    try:
        from linux_defender import paths
        from linux_defender.ui.icons import app_icon_svg
        p = paths.DATA_DIR / "icons" / f"{APP_ID}-scan.svg"
        p.parent.mkdir(parents=True, exist_ok=True)
        svg = app_icon_svg("safe")
        if not p.exists() or p.read_text(encoding="utf-8") != svg:
            p.write_text(svg, encoding="utf-8")
        return str(p)
    except Exception:
        return "security-high"

CLAMAV_DOCS = "https://docs.clamav.net/"


def _target() -> list[str]:
    appimage = os.environ.get("APPIMAGE")
    return [appimage] if appimage else ["python3", "-m", "linux_defender"]


def launcher_command() -> str:
    """Command line for shell scripts (POSIX quoting)."""
    return " ".join(shlex.quote(a) for a in _target())


def desktop_command() -> str:
    """Command line for .desktop / .nemo_action Exec keys (freedesktop quoting)."""
    out = []
    for a in _target():
        if any(c in a for c in ' \t\n"\'\\><~|&;$*?#()`'):
            a = '"' + a.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'
        out.append(a)
    return " ".join(out)


def open_url(url: str):
    # xdg-open from inside an AppImage must not inherit our Python/Qt env
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH")}
    import subprocess
    try:
        subprocess.Popen(["xdg-open", url], env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        webbrowser.open(url)


def set_autostart(enabled: bool):
    if enabled:
        AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART.write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\nComment=Antivirus protection\n"
            f"Exec={desktop_command()} --tray\nIcon={APP_ID}\n"
            "X-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=10\nTerminal=false\n",
            encoding="utf-8")
    else:
        AUTOSTART.unlink(missing_ok=True)


MENU_ENTRY = HOME / ".local/share/applications" / f"{APP_ID}.desktop"
MENU_ICON = HOME / ".local/share/icons/hicolor/scalable/apps" / f"{APP_ID}.svg"


def set_menu_entry(enabled: bool, icon_svg: str = ""):
    if enabled:
        MENU_ENTRY.parent.mkdir(parents=True, exist_ok=True)
        MENU_ICON.parent.mkdir(parents=True, exist_ok=True)
        if icon_svg:
            MENU_ICON.write_text(icon_svg, encoding="utf-8")
        cmd = desktop_command()
        MENU_ENTRY.write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={APP_NAME}\nGenericName=Antivirus\nComment=Free antivirus protection\n"
            f"Exec={cmd} %F\nIcon={APP_ID}\nTerminal=false\nCategories=System;Security;\n"
            f"StartupWMClass={APP_ID}\nActions=QuickScan;Update;\n\n"
            f"[Desktop Action QuickScan]\nName=Quick Scan\nExec={cmd} --quick-scan\n\n"
            f"[Desktop Action Update]\nName=Update threat signatures\nExec={cmd} --update\n",
            encoding="utf-8")
    else:
        MENU_ENTRY.unlink(missing_ok=True)
        MENU_ICON.unlink(missing_ok=True)


def _scan_script(fm: str, var: str) -> str:
    """File-manager script: scans the selected files and folders, or the open folder when nothing is selected.

    The file manager passes the selection as newline-separated absolute paths in `var` (local files) and as names
    relative to the open folder in the arguments. Paths may contain spaces and wildcard characters."""
    return f"""#!/bin/sh
# {fm}: scan the selected files and folders with {APP_NAME}
set -f
sel="${{{var}:-}}"
if [ -n "$sel" ]; then
    set --
    old_ifs=$IFS
    IFS='
'
    for p in $sel; do
        [ -n "$p" ] && set -- "$@" "$p"
    done
    IFS=$old_ifs
elif [ $# -gt 0 ]; then
    for a in "$@"; do
        shift
        case "$a" in
            /*) set -- "$@" "$a" ;;
            *) set -- "$@" "$PWD/$a" ;;
        esac
    done
else
    set -- "$PWD"
fi
exec {launcher_command()} --scan "$@"
"""


def _fm_action() -> str:
    """FileManager-Actions entry, read by caja-actions (Caja) and nautilus-actions."""
    return (
        "[Desktop Entry]\nType=Action\n"
        f"Name=Scan with {APP_NAME}\nTooltip=Scan the selected files and folders for threats\n"
        f"Icon={_menu_icon()}\nEnabled=true\nTargetContext=true\nTargetLocation=true\nProfiles=scan;\n\n"
        "[X-Action-Profile scan]\nName=Scan\n"
        f"Exec={desktop_command()} --scan %F\nMimeTypes=all/all;\nSchemes=file;\n"
    )


def _caja_actions_top_level():
    """caja-actions puts every action in a "Caja-Actions actions" submenu unless items-create-root-menu=false.
    Set it so "Scan with Linux Defender" is directly in the right-click menu, unless the user already chose."""
    try:
        text = CAJA_ACTIONS_CONF.read_text(encoding="utf-8") if CAJA_ACTIONS_CONF.exists() else ""
        if "items-create-root-menu" in text:
            return
        lines = text.splitlines()
        if "[runtime]" in (l.strip() for l in lines):
            i = next(n for n, l in enumerate(lines) if l.strip() == "[runtime]")
            lines.insert(i + 1, "items-create-root-menu=false")
        else:
            lines += ([""] if lines else []) + ["[runtime]", "items-create-root-menu=false"]
        CAJA_ACTIONS_CONF.parent.mkdir(parents=True, exist_ok=True)
        CAJA_ACTIONS_CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def file_managers() -> dict:
    """Which supported file managers are installed (and whether Caja has caja-actions)."""
    caja_actions = bool(shutil.which("caja-actions-config-tool")) or any(
        Path(d).glob("libcaja-actions*.so") for d in
        ("/usr/lib/x86_64-linux-gnu/caja/extensions-2.0", "/usr/lib/caja/extensions-2.0",
         "/usr/lib64/caja/extensions-2.0") if Path(d).is_dir())
    return {"nautilus": bool(shutil.which("nautilus")), "nemo": bool(shutil.which("nemo")),
            "dolphin": bool(shutil.which("dolphin")), "caja": bool(shutil.which("caja")),
            "caja_actions": caja_actions}


def set_file_manager_integration(enabled: bool):
    dcmd = desktop_command()
    if enabled:
        for script, fm, var in ((NAUTILUS_SCRIPT, "Files (Nautilus)", "NAUTILUS_SCRIPT_SELECTED_FILE_PATHS"),
                                (CAJA_SCRIPT, "Caja", "CAJA_SCRIPT_SELECTED_FILE_PATHS")):
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(_scan_script(fm, var), encoding="utf-8")
            script.chmod(0o755)
        FM_ACTION.parent.mkdir(parents=True, exist_ok=True)
        FM_ACTION.write_text(_fm_action(), encoding="utf-8")
        _caja_actions_top_level()
        NEMO_ACTION.parent.mkdir(parents=True, exist_ok=True)
        NEMO_ACTION.write_text(
            "[Nemo Action]\n"
            f"Name=Scan with {APP_NAME}\nComment=Scan for threats\n"
            f"Exec={dcmd} --scan %F\nIcon-Name=security-high\nSelection=Any\nExtensions=any;\n",
            encoding="utf-8")
        DOLPHIN_MENU.parent.mkdir(parents=True, exist_ok=True)
        DOLPHIN_MENU.write_text(
            "[Desktop Entry]\nType=Service\nMimeType=all/all;\nActions=linuxDefenderScan;\n"
            "X-KDE-ServiceTypes=KonqPopupMenu/Plugin\n\n[Desktop Action linuxDefenderScan]\n"
            f"Name=Scan with {APP_NAME}\nIcon={_menu_icon()}\nExec={dcmd} --scan %F\n",
            encoding="utf-8")
        DOLPHIN_MENU.chmod(0o755)
    else:
        for p in (NAUTILUS_SCRIPT, NEMO_ACTION, DOLPHIN_MENU, CAJA_SCRIPT, FM_ACTION):
            p.unlink(missing_ok=True)


def desktop_notify(title: str, body: str, urgency="normal"):
    import subprocess
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH")}
    try:
        subprocess.Popen(["notify-send", "-a", APP_NAME, "-u", urgency, "-i", "security-high", title, body],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
