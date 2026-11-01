"""Quarantine vault.

Each item is stored XOR-obfuscated (so it can't be executed or re-detected by
other scanners) next to a JSON metadata file. Permissions of the original file
are recorded and restored.

The vault folder can be moved anywhere the user can write (Protection › Quarantine ›
Quarantine folder). Only Linux Defender's own files (<32 hex>.bin / .json and a marker
file) are ever touched in that folder.
"""
import json
import os
import re
import shutil
import stat
import time
import uuid
from pathlib import Path

from linux_defender import paths

_KEY = 0xA7
_CHUNK = 1 << 20
MARKER = ".linux-defender-quarantine"
SUBFOLDER = "Linux Defender Quarantine"
_ID = re.compile(r"^[0-9a-f]{32}$")


def _xor(b: bytes) -> bytes:
    if not b:
        return b
    n = int.from_bytes(b, "little")
    mask = int.from_bytes(bytes([_KEY]) * len(b), "little")
    return (n ^ mask).to_bytes(len(b), "little")


# kept for compatibility with older code/tests
_xor_fast = _xor


def _xor_copy(src, dst):
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        os.fchmod(fo.fileno(), 0o600)
        while True:
            b = fi.read(_CHUNK)
            if not b:
                break
            fo.write(_xor(b))


def iter_plain(blob_path, chunk=_CHUNK):
    """Yield the original (de-obfuscated) content of a quarantined item, chunk by chunk."""
    with open(blob_path, "rb") as fi:
        while True:
            b = fi.read(chunk)
            if not b:
                break
            yield _xor(b)


def resolve_location(chosen: str | Path) -> Path:
    """Folder the vault should live in when the user picks `chosen`:
    the folder itself when it is empty or already a vault, otherwise a subfolder inside it."""
    p = Path(chosen).expanduser()
    if p.exists() and ((p / MARKER).exists() or not any(p.iterdir())):
        return p
    return p / SUBFOLDER


class Quarantine:
    def __init__(self, root=None, max_size_mb=0):
        self.root = Path(root) if root else paths.QUARANTINE_DIR
        self.max_size_mb = max_size_mb
        self._prepare(self.root)

    @staticmethod
    def _prepare(root: Path):
        root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
        (root / MARKER).touch(exist_ok=True)

    # -- items ---------------------------------------------------------------
    def _meta_files(self, root=None):
        root = root or self.root
        return [f for f in root.glob("*.json") if _ID.match(f.stem)]

    def add(self, path: str, threat: str) -> dict:
        st = os.lstat(path)
        qid = uuid.uuid4().hex
        blob = self.root / f"{qid}.bin"
        _xor_copy(path, blob)
        meta = {"id": qid, "path": path, "threat": threat, "added": time.time(),
                "size": st.st_size, "mode": stat.S_IMODE(st.st_mode)}
        self._write_meta(meta)
        try:
            os.remove(path)
        except OSError:
            blob.unlink(missing_ok=True)
            (self.root / f"{qid}.json").unlink(missing_ok=True)
            raise
        if self.max_size_mb:
            self.enforce_size_limit(self.max_size_mb, keep={qid})
        return meta

    def _write_meta(self, meta):
        f = self.root / f"{meta['id']}.json"
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)

    def update_meta(self, qid: str, **fields):
        meta = self.get(qid)
        meta.update(fields)
        self._write_meta(meta)
        return meta

    def get(self, qid: str) -> dict:
        return json.loads((self.root / f"{qid}.json").read_text(encoding="utf-8"))

    def blob(self, qid: str) -> Path:
        return self.root / f"{qid}.bin"

    def items(self) -> list[dict]:
        out = []
        for f in self._meta_files():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return sorted(out, key=lambda m: m["added"], reverse=True)

    def restore(self, qid: str, dest: str | None = None, overwrite=False) -> str:
        meta = self.get(qid)
        dest = dest or meta["path"]
        if os.path.exists(dest) and not overwrite:
            raise FileExistsError(dest)
        os.makedirs(os.path.dirname(dest) or "/", exist_ok=True)
        tmp = dest + ".linux-defender-restore"
        _xor_copy(self.blob(qid), tmp)
        os.chmod(tmp, meta.get("mode", 0o644))
        os.replace(tmp, dest)
        self.delete(qid)
        return dest

    def delete(self, qid: str):
        for ext in (".bin", ".json"):
            try:
                (self.root / f"{qid}{ext}").unlink()
            except FileNotFoundError:
                pass

    def empty(self) -> int:
        n = 0
        for m in self.items():
            self.delete(m["id"])
            n += 1
        return n

    # -- limits --------------------------------------------------------------
    def purge_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = time.time() - days * 86400
        n = 0
        for m in self.items():
            if m["added"] < cutoff:
                self.delete(m["id"])
                n += 1
        return n

    def enforce_size_limit(self, max_mb: int, keep=()) -> int:
        """Delete the oldest items until the vault is within max_mb (0 = no limit)."""
        if max_mb <= 0:
            return 0
        limit = max_mb << 20
        items = [m for m in sorted(self.items(), key=lambda m: m["added"]) if m["id"] not in keep]  # oldest first
        total = sum(self._disk_size(m["id"]) for m in self.items())
        n = 0
        for m in items:
            if total <= limit:
                break
            total -= self._disk_size(m["id"])
            self.delete(m["id"])
            n += 1
        return n

    # -- usage ---------------------------------------------------------------
    def _disk_size(self, qid) -> int:
        size = 0
        for ext in (".bin", ".json"):
            try:
                size += (self.root / f"{qid}{ext}").stat().st_size
            except OSError:
                pass
        return size

    def total_size(self) -> int:
        return sum(m.get("size", 0) for m in self.items())

    def disk_usage(self) -> dict:
        items = self.items()
        used = sum(self._disk_size(m["id"]) for m in items)
        try:
            du = shutil.disk_usage(self.root)
            free, total = du.free, du.total
        except OSError:
            free = total = 0
        oldest = min((m["added"] for m in items), default=0)
        return {"items": len(items), "used": used, "free": free, "disk_total": total, "oldest": oldest}

    # -- moving the vault --------------------------------------------------------
    def move_to(self, new_root, progress=None) -> Path:
        """Move every item to `new_root` (created if needed). Each item is copied, verified
        and only then removed from the old folder. Returns the new root."""
        new_root = Path(new_root).expanduser().resolve()
        old_root = self.root.resolve()
        if new_root == old_root:
            return self.root
        if str(new_root).startswith(str(old_root) + os.sep):
            raise ValueError("The new folder can't be inside the current quarantine folder.")
        self._prepare(new_root)
        if not os.access(new_root, os.W_OK):
            raise PermissionError(f"Can't write to {new_root}")
        items = self.items()
        need = sum(self._disk_size(m["id"]) for m in items)
        try:
            same_fs = os.stat(new_root).st_dev == os.stat(old_root).st_dev
        except OSError:
            same_fs = False
        if not same_fs and shutil.disk_usage(new_root).free < need + (16 << 20):
            raise OSError(f"Not enough free space in {new_root}")
        for i, m in enumerate(items, 1):
            qid = m["id"]
            for ext in (".bin", ".json"):
                src, dst = old_root / f"{qid}{ext}", new_root / f"{qid}{ext}"
                if not src.exists():
                    continue
                if same_fs:
                    os.replace(src, dst)
                else:
                    shutil.copy2(src, dst)
                    if dst.stat().st_size != src.stat().st_size:
                        dst.unlink(missing_ok=True)
                        raise OSError(f"Copy verification failed for {src.name}")
                    os.chmod(dst, 0o600)
                    src.unlink()
            if progress:
                progress(i, len(items))
        # tidy up the old vault if nothing else is in it
        try:
            (old_root / MARKER).unlink(missing_ok=True)
            if old_root != paths.QUARANTINE_DIR.resolve() and not any(old_root.iterdir()):
                old_root.rmdir()
        except OSError:
            pass
        self.root = new_root
        return new_root


def delete_file(path: str):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
