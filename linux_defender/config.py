"""Persistent JSON settings."""
import copy
import json
import os
import threading
from pathlib import Path

from linux_defender import paths

HOME = str(Path.home())

DEFAULTS = {
    "first_run_done": False,
    "general": {
        "theme": "dark",               # dark | light
        "notifications": True,
        "close_to_tray": True,
        "start_minimized": False,
        "autostart": False,
    },
    "antivirus": {
        "shield_enabled": True,        # real-time (user-level, inotify) protection
        "shield_paths": [f"{HOME}/Downloads", f"{HOME}/Desktop", f"{HOME}/Documents", "/tmp"],
        "scan_archives": True,
        "archive_max_mb": 100,
        "max_file_mb": 100,
        "detect_pua": False,
        "scan_scripts": True,
        "heuristic_alerts": True,
        "action": "quarantine",        # quarantine | delete | report
        "system_scan_other_mounts": False,
    },
    "exceptions": [],                  # list of {"path": str, "added": ts}
    "update": {
        "auto": True,
        "interval_hours": 2,
        "last_success": 0,
        "last_check": 0,
        "proxy": {"enabled": False, "host": "", "port": 8080, "user": "", "password": ""},
    },
    "schedule": {
        "enabled": False,
        "type": "quick",               # quick | system
        "frequency": "weekly",         # daily | weekly
        "weekday": 6,                  # 0=Mon … 6=Sun
        "time": "12:00",
        "last_run": 0,
    },
    "quarantine": {"auto_delete_days": 30, "location": "", "max_size_mb": 0, "rescan_after_update": True},
    "integration": {"file_manager": False, "menu_entry": False},
    "logs": {"max_age_days": 90, "max_scan_logs": 500},
    "custom_scans": [],                # [{"name": str, "paths": [..]}]
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self, path: Path = paths.SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            self.data = copy.deepcopy(DEFAULTS)

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    def get(self, dotted: str, default=None):
        cur = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value, save: bool = True):
        with self._lock:
            parts = dotted.split(".")
            cur = self.data
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = value
            if save:
                self.save()

    # --- exceptions -------------------------------------------------------
    def exception_paths(self) -> list[str]:
        return [e["path"] for e in self.data.get("exceptions", [])]

    def is_excepted(self, path: str) -> bool:
        for ex in self.exception_paths():
            ex = ex.rstrip("/") or "/"
            if path == ex or path.startswith(ex + "/") or (ex == "/" and path.startswith("/")):
                return True
        return False
