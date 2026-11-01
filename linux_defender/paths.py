"""Filesystem locations (XDG) and lookup of bundled/system ClamAV binaries."""
import os
import shutil
from pathlib import Path

from linux_defender import APP_ID


def _xdg(var: str, default: str) -> Path:
    v = os.environ.get(var)
    return Path(v) if v else Path.home() / default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
DB_DIR = DATA_DIR / "signatures"
QUARANTINE_DIR = DATA_DIR / "quarantine"
LOG_DIR = DATA_DIR / "logs"
SCAN_LOG_DIR = LOG_DIR / "scans"
EVENTS_FILE = DATA_DIR / "events.jsonl"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
CLAMD_CONF = CONFIG_DIR / "clamd.conf"
FRESHCLAM_CONF = CONFIG_DIR / "freshclam.conf"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP_ID}-{os.getuid()}"
    p = Path(base) / APP_ID
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def clamd_socket() -> Path:
    p = runtime_dir() / "clamd.sock"
    if len(os.fsencode(str(p))) >= 100:          # UNIX socket paths are limited to 107 bytes
        alt = Path(f"/tmp/{APP_ID}-{os.getuid()}")
        alt.mkdir(mode=0o700, exist_ok=True)
        os.chmod(alt, 0o700)
        p = alt / "clamd.sock"
    return p


def instance_socket() -> str:
    """Socket the running Linux Defender listens on, so a second launch (file manager, tray, menu, command line)
    hands its request over instead of starting another copy. Lives in the private runtime folder; it must not be
    /tmp/linux-defender-<uid>, which is a folder (icons, clamd fallback)."""
    p = runtime_dir() / "app.sock"
    if len(os.fsencode(str(p))) >= 100:
        alt = Path(f"/tmp/{APP_ID}-{os.getuid()}")
        alt.mkdir(mode=0o700, exist_ok=True)
        os.chmod(alt, 0o700)
        p = alt / "app.sock"
    return str(p)


def _migrate_from_bulwark() -> None:
    """1.0.0 was called Bulwark: move its settings/signatures/quarantine and drop its launchers."""
    import shutil
    old_cfg = CONFIG_DIR.parent / "bulwark"
    old_data = DATA_DIR.parent / "bulwark"
    for old, new in ((old_cfg, CONFIG_DIR), (old_data, DATA_DIR)):
        if old.is_dir() and not new.exists():
            try:
                shutil.move(str(old), str(new))
            except OSError:
                pass
    for gen in (CONFIG_DIR / "clamd.conf", CONFIG_DIR / "freshclam.conf"):
        try:
            if gen.exists() and "bulwark" in gen.read_text(encoding="utf-8"):
                gen.unlink()                     # regenerated with the new paths
        except OSError:
            pass
    home = Path.home()
    for p in (home / ".config/autostart/bulwark.desktop",
              home / ".local/share/applications/bulwark.desktop",
              home / ".local/share/icons/hicolor/scalable/apps/bulwark.svg",
              home / ".local/share/nautilus/scripts/Scan with Bulwark",
              home / ".local/share/nemo/actions/bulwark-scan.nemo_action",
              home / ".local/share/kio/servicemenus/bulwark-scan.desktop"):
        try:
            p.unlink()
        except OSError:
            pass


def ensure_dirs() -> None:
    _migrate_from_bulwark()
    for d in (CONFIG_DIR, DATA_DIR, DB_DIR, QUARANTINE_DIR, LOG_DIR, SCAN_LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
    os.chmod(QUARANTINE_DIR, 0o700)


def appdir() -> Path | None:
    """Root of the mounted AppImage (or None when running from source)."""
    v = os.environ.get("APPDIR")
    return Path(v) if v and Path(v).is_dir() else None


def find_tool(name: str) -> str | None:
    """Prefer the ClamAV binaries bundled in the AppImage, then the system ones."""
    ad = appdir()
    if ad:
        for sub in ("usr/clamav/bin", "usr/clamav/sbin"):
            cand = ad / sub / name
            if cand.exists():
                return str(cand)
    for d in ("/usr/sbin", "/usr/bin", "/usr/local/sbin", "/usr/local/bin"):
        cand = Path(d) / name
        if cand.exists():
            return str(cand)
    return shutil.which(name)


def cvd_certs_dir() -> Path | None:
    """Folder with ClamAV's root certificate (clamav.crt), used by ClamAV 1.5+ to verify signature databases.

    The AppImage ships its own copy, so updates and scans work on systems without ClamAV installed (where
    /etc/clamav/certs doesn't exist). From source, the system ClamAV's folder is used."""
    ad = appdir()
    cands = []
    if ad:
        cands.append(ad / "usr/clamav/certs")
    cands.append(Path("/etc/clamav/certs"))
    for c in cands:
        try:
            if c.is_dir() and any(c.glob("*.crt")):
                return c
        except OSError:
            continue
    return None


def certs_config_lines() -> list[str]:
    """`CVDCertsDirectory` line for clamd.conf / freshclam.conf (only with a ClamAV that has the option)."""
    d = cvd_certs_dir()
    return [f"CVDCertsDirectory {d}"] if d else []


def tool_env() -> dict:
    """Environment for running the bundled ClamAV tools."""
    env = dict(os.environ)
    ad = appdir()
    if ad and (ad / "usr/clamav/lib").is_dir():
        env["LD_LIBRARY_PATH"] = str(ad / "usr/clamav/lib")
    else:
        env.pop("LD_LIBRARY_PATH", None)
    certs = cvd_certs_dir()
    if certs:
        env["CVD_CERTS_DIR"] = str(certs)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def resource(name: str) -> Path:
    return Path(__file__).resolve().parent / "resources" / name
