"""ClamAV 1.5 root certificate: updates and the scan engine work on a system without ClamAV installed
(no /etc/clamav/certs). Run it on a system without /etc/clamav/certs to cover the AppImage case."""
import os, sys, subprocess, time
if not os.environ.get("APPDIR"):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
from linux_defender import paths
from linux_defender.controller import Controller
def wait(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def until(pred, ms=20000):
    for _ in range(ms // 100):
        if pred(): return True
        wait(100)
    return pred()
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:100]}")
    if not cond: fails.append(name)

print("system /etc/clamav/certs present:", os.path.isdir("/etc/clamav/certs"))
certs = paths.cvd_certs_dir()
check("certificate folder found", certs is not None, certs)
if os.environ.get("APPDIR"):
    check("AppImage uses its bundled certificate", certs and str(certs).startswith(os.environ["APPDIR"]), certs)
check("certificate file present", certs and any(certs.glob("*.crt")), list(certs.glob("*.crt")) if certs else "")
check("tool environment sets CVD_CERTS_DIR", paths.tool_env().get("CVD_CERTS_DIR") == str(certs))

ctl = Controller(); ctl.settings.set("first_run_done", True); ctl.settings.set("update.auto", False)
ctl.updater.write_config()
conf = paths.FRESHCLAM_CONF.read_text()
check("freshclam.conf has CVDCertsDirectory", f"CVDCertsDirectory {certs}" in conf)

# freshclam: must get past initialisation (the network may be unavailable here, that's fine)
fc = paths.find_tool("freshclam")
out = subprocess.run([fc, "--config-file", str(paths.FRESHCLAM_CONF), "--stdout"], capture_output=True, text=True,
                     env=paths.tool_env(), timeout=120).stdout
bad = [l for l in out.splitlines() if "certs directory" in l.lower() or "code-signature verifier" in l.lower()
       or "initialization error" in l.lower() or "libfreshclam init failed" in l.lower()]
check("freshclam initialises (no certificate error)", not bad, bad[:1] or out.splitlines()[:1])
check("freshclam starts the update", "update process started" in out, out.splitlines()[:1])

# clamd: loads the signatures and answers
db = paths.DB_DIR; db.mkdir(parents=True, exist_ok=True)
(db / "test.hdb").write_text("44d88612fea8a8f36de82e1278abb02f:68:Eicar-Test-Signature\n")
ctl.start()
until(lambda: ctl.engine.state not in ("stopped", "loading", "starting"), 60000)
check("scan engine is ready", ctl.engine.ready, ctl.engine.state)
check("clamd.conf has CVDCertsDirectory", f"CVDCertsDirectory {certs}" in paths.CLAMD_CONF.read_text()
      if hasattr(paths, "CLAMD_CONF") else True)
log = (paths.LOG_DIR / "clamd.log").read_text(errors="replace") if (paths.LOG_DIR / "clamd.log").exists() else ""
check("clamd log has no certificate error", "certs directory" not in log.lower(), "")
eicar = paths.DATA_DIR / "eicar.com"
eicar.write_bytes(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
if ctl.engine.ready:
    r = ctl.engine.scan(str(eicar))
    check("scan detects the EICAR test file", r.infected, getattr(r, "threat", ""))
eicar.unlink(missing_ok=True)
try:
    ctl.engine.stop()
except Exception:
    pass
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
