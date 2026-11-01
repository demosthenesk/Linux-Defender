"""Log management: scan reports (JSON) plus the scan-engine and update logs (text).

Engine and update logs may be open by clamd / freshclam while they run. Those files are
emptied (truncated) instead of deleted, so the running program keeps logging into the same file.
Moving such a file copies it and then empties the original.
"""
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from linux_defender import paths

KIND_TITLES = {"scan": "Scan report", "engine": "Scan engine log", "update": "Update log"}
SCAN_TITLES = {"quick": "Quick Scan", "system": "System Scan", "custom": "Custom Scan", "scheduled": "Scheduled Scan"}
ACTIVE_NAMES = {"clamd.log", "clamd.stdout.log", "freshclam.log"}


@dataclass
class LogFile:
    path: Path
    kind: str                      # scan | engine | update
    title: str
    ts: float
    size: int
    summary: str = ""
    data: dict = field(default_factory=dict)

    locked: bool = False           # report of a scan that is running or paused

    @property
    def active(self) -> bool:
        """A log a running/next clamd or freshclam writes to (emptied, never deleted)."""
        return self.kind != "scan" and self.path.name in ACTIVE_NAMES


def is_locked(path) -> bool:
    """True while a running (or paused) scan holds the lock on this report."""
    import fcntl
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def _scan_entry(f: Path) -> LogFile | None:
    locked = is_locked(f)
    try:
        st = f.stat()
        d = json.loads(f.read_text(encoding="utf-8"))
    except OSError:
        return None
    except ValueError:
        if not locked:
            return None
        d = {}                                       # being rewritten right now
    status = d.get("status") or ("stopped" if d.get("cancelled") else "finished")
    if status in ("running", "paused") and not locked:
        status = "interrupted"                     # the app ended while this scan was running
    elapsed = d.get("elapsed")
    dur = int(elapsed if elapsed is not None else max(0, d.get("finished", 0) - d.get("started", 0)))
    suffix = {"stopped": " (stopped)", "running": " (running)", "paused": " (paused)",
              "interrupted": " (interrupted)"}.get(status, "")
    kind = d.get("kind") or f.stem.rsplit("-", 1)[-1]
    title = SCAN_TITLES.get(kind, "Scan") + suffix
    summary = (f"{d.get('scanned', 0):,} scanned · {d.get('infected', 0)} threat(s) · "
               f"{d.get('resolved', 0)} resolved · {dur // 60}m {dur % 60}s")
    if locked:
        summary = "In use by the running scan — locked · " + summary
    e = LogFile(f, "scan", title, d.get("started") or st.st_mtime, st.st_size, summary, d)
    e.locked = locked
    return e


def list_logs() -> list[LogFile]:
    out = []
    if paths.SCAN_LOG_DIR.is_dir():
        for f in paths.SCAN_LOG_DIR.glob("*.json"):
            e = _scan_entry(f)
            if e:
                out.append(e)
    if paths.LOG_DIR.is_dir():
        for f in paths.LOG_DIR.iterdir():
            if not f.is_file():
                continue
            n = f.name
            if n.startswith("clamd"):
                kind = "engine"
            elif n.startswith("freshclam"):
                kind = "update"
            else:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            title = KIND_TITLES[kind] + ("" if n in ACTIVE_NAMES else f" (archived: {n})")
            if n == "clamd.stdout.log":
                title = "Scan engine output"
            out.append(LogFile(f, kind, title, st.st_mtime, st.st_size,
                               f"{_count_lines(f):,} line(s)" + (" · in use" if n in ACTIVE_NAMES else "")))
    return sorted(out, key=lambda e: e.ts, reverse=True)


def _count_lines(f: Path) -> int:
    try:
        with open(f, "rb") as fh:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 16), b""))
    except OSError:
        return 0


def read_text(e: LogFile, max_lines: int = 3000) -> str:
    if e.kind == "scan":
        d = e.data
        targets = d.get("targets", [])
        fin = d.get("finished")
        lines = [f"{e.title}" + ("   [locked: the scan is still running]" if e.locked else ""),
                 f"Started:  {time.strftime('%d %b %Y %H:%M:%S', time.localtime(d.get('started', 0)))}",
                 f"Finished: " + (time.strftime('%d %b %Y %H:%M:%S', time.localtime(fin)) if fin else "—"),
                 f"Targets:  {', '.join(targets[:10])}{' …' if len(targets) > 10 else ''}",
                 f"Scanned: {d.get('scanned', 0)}   Skipped: {d.get('skipped', 0)}   Errors: {d.get('errors', 0)}",
                 f"Threats: {d.get('infected', 0)}   Resolved: {d.get('resolved', 0)}   "
                 f"Unresolved: {d.get('unresolved', 0)}", ""]
        for t in d.get("threats", []):
            lines.append(f"[{t['action']}] {t['name']}  —  {t['path']}" + (f"  ({t['error']})" if t.get("error") else ""))
        if not d.get("threats"):
            lines.append("No threats found.")
        errs = d.get("error_samples") or []
        if errs:
            lines += ["", f"Errors (first {min(len(errs), 50)}):"] + [f"  {p}: {m}" for p, m in errs[:50]]
        lines += ["", f"File: {e.path}"]
        return "\n".join(lines)
    try:
        with open(e.path, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
    except OSError as ex:
        return f"Can't read {e.path}: {ex}"
    if not all_lines:
        return "(empty)"
    head = "" if len(all_lines) <= max_lines else f"… showing the last {max_lines} of {len(all_lines)} lines …\n"
    return head + "".join(all_lines[-max_lines:])


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suf = dest.stem, dest.suffix
    i = 1
    while (dest.parent / f"{stem} ({i}){suf}").exists():
        i += 1
    return dest.parent / f"{stem} ({i}){suf}"


def _empty(f: Path):
    with open(f, "r+b") as fh:
        fh.truncate(0)


def move_logs(entries: list[LogFile], dest_dir) -> tuple[list[Path], list[str]]:
    """Move logs into dest_dir. In-use engine/update logs are copied, then emptied."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(dest_dir, os.W_OK):
        raise PermissionError(f"Can't write to {dest_dir}")
    moved, failed = [], []
    for e in entries:
        if e.locked or (e.kind == "scan" and is_locked(e.path)):
            failed.append(f"{e.path.name}: in use by the running scan")
            continue
        target = _unique(dest_dir / e.path.name)
        try:
            if e.active:
                shutil.copy2(e.path, target)
                if target.stat().st_size < e.path.stat().st_size:
                    raise OSError("copy incomplete")
                _empty(e.path)
            else:
                shutil.move(str(e.path), str(target))
            moved.append(target)
        except OSError as ex:
            failed.append(f"{e.path.name}: {ex.strerror or ex}")
    return moved, failed


def delete_logs(entries: list[LogFile]) -> tuple[int, list[str]]:
    """Delete logs; in-use engine/update logs are emptied instead."""
    n, failed = 0, []
    for e in entries:
        if e.locked or (e.kind == "scan" and is_locked(e.path)):
            failed.append(f"{e.path.name}: in use by the running scan")
            continue
        try:
            if e.active:
                _empty(e.path)
            else:
                e.path.unlink()
            n += 1
        except FileNotFoundError:
            n += 1
        except OSError as ex:
            failed.append(f"{e.path.name}: {ex.strerror or ex}")
    return n, failed


def apply_retention(max_age_days: int, max_scan_logs: int) -> int:
    """Remove scan reports (and archived engine/update logs) older than max_age_days, and keep at most
    max_scan_logs scan reports (newest first). 0 disables a rule. Returns how many files were removed."""
    logs = [e for e in list_logs() if not e.locked]
    remove = []
    if max_age_days > 0:
        cutoff = time.time() - max_age_days * 86400
        remove += [e for e in logs if e.ts < cutoff and not e.active]
    if max_scan_logs > 0:
        scans = [e for e in logs if e.kind == "scan" and e not in remove]
        remove += scans[max_scan_logs:]
    n, _ = delete_logs(remove)
    return n


def total_size() -> int:
    return sum(e.size for e in list_logs())
