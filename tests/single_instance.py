"""Single instance: a second launch (as from a file manager's Scan with Linux Defender) hands its request to the
running copy and exits; the running copy scans the files. Regression test for the instance socket clashing
with the /tmp/linux-defender-<uid> folder."""
import os, sys, subprocess, time, json, glob
from pathlib import Path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.environ.get("APPDIR"):
    launch = [sys.executable, "-s", os.path.join(os.environ["APPDIR"], "usr/lib/linux-defender/launch.py")]
else:
    sys.path.insert(0, root)
    launch = [sys.executable, "-m", "linux_defender"]
fails = []
def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + f"{name:58} {str(detail)[:100]}")
    if not cond: fails.append(name)
from linux_defender import paths
cfg = paths.SETTINGS_FILE; cfg.parent.mkdir(parents=True, exist_ok=True)
cfg.write_text(json.dumps({"first_run_done": True, "update": {"auto": False}, "antivirus": {"action": "quarantine"}}))
# the folder that used to block the instance socket
Path(f"/tmp/linux-defender-{os.getuid()}").mkdir(exist_ok=True)
env = dict(os.environ)
first = subprocess.Popen(launch, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
sock = paths.instance_socket()
for _ in range(100):
    if os.path.exists(sock): break
    time.sleep(0.2)
check("running copy listens on its socket", os.path.exists(sock), sock)
check("socket is not the /tmp/linux-defender-<uid> folder", sock != f"/tmp/linux-defender-{os.getuid()}", sock)
time.sleep(2)
d = Path.home() / "Test Files"; d.mkdir(exist_ok=True)
eicar = d / "eicar test.com"
eicar.write_bytes(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
t0 = time.time()
second = subprocess.run(launch + ["--scan", str(eicar)], env=env, capture_output=True, text=True, timeout=60)
check("second launch hands over and exits quickly", second.returncode == 0 and time.time() - t0 < 15,
      f"rc={second.returncode} in {time.time() - t0:.1f}s")
check("only one copy keeps running", first.poll() is None)
# the running copy scans the file (waits for the engine if it is still starting)
reports = []
for _ in range(120):
    reports = [json.loads(Path(f).read_text()) for f in glob.glob(str(paths.SCAN_LOG_DIR / "*.json"))]
    reports = [r for r in reports if r.get("status") not in ("running", "paused") and r.get("finished")]
    if reports: break
    time.sleep(0.5)
r = reports[0] if reports else {}
check("running copy scanned the file", bool(reports) and str(eicar) in r.get("targets", []), r.get("targets"))
check("threat found", r.get("infected") == 1, r.get("infected"))
check("file moved to quarantine", not eicar.exists())
clamds = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "clamd"], capture_output=True, text=True).stdout.split()
check("one scan engine", len(clamds) == 1, clamds)
first.terminate()
try:
    out, _ = first.communicate(timeout=20)
except subprocess.TimeoutExpired:
    first.kill(); out = ""
check("no listen error", "can't listen" not in (out or ""), (out or "")[-200:])
print(f"\n{len(fails)} failure(s)")
sys.exit(1 if fails else 0)
