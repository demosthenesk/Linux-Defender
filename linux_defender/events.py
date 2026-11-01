"""Notifications / event log."""
import json
import threading
import time
import uuid

from linux_defender import paths

CRITICAL, WARNING, INFO = "critical", "warning", "info"


class EventStore:
    MAX = 2000

    def __init__(self, path=paths.EVENTS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self.listeners = []

    def add(self, level: str, module: str, title: str, details: str = "", data: dict | None = None):
        ev = {"id": uuid.uuid4().hex, "ts": time.time(), "level": level, "module": module, "title": title,
              "details": details, "data": data or {}, "read": False}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev) + "\n")
        for cb in list(self.listeners):
            try:
                cb(ev)
            except Exception:
                pass
        return ev

    def all(self) -> list[dict]:
        out = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass
        if len(out) > self.MAX:
            out = out[-self.MAX:]
            self._rewrite(out)
        return list(reversed(out))

    def _rewrite(self, events_oldest_first):
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                for e in events_oldest_first:
                    f.write(json.dumps(e) + "\n")
            tmp.replace(self.path)

    @staticmethod
    def key(ev) -> str:
        return ev.get("id") or repr(ev.get("ts"))       # events written before ids existed

    def mark_read(self, keys) -> int:
        keys = set(keys)
        evs = list(reversed(self.all()))
        n = 0
        for e in evs:
            if not e.get("read") and self.key(e) in keys:
                e["read"] = True
                n += 1
        if n:
            self._rewrite(evs)
        return n

    def mark_all_read(self) -> int:
        evs = list(reversed(self.all()))
        n = sum(1 for e in evs if not e.get("read"))
        for e in evs:
            e["read"] = True
        if n:
            self._rewrite(evs)
        return n

    def unread_count(self) -> int:
        return sum(1 for e in self.all() if not e.get("read"))

    def clear(self):
        self._rewrite([])
