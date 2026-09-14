from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import uuid

from .safe_fs import SafeRoot, UnsafePath
from .settings import MAX_ACCOUNT_UPLOADS, MAX_UPLOAD


class QuotaExceeded(Exception):
    pass


ID = re.compile(r"^[0-9a-f]{32}$")
SOURCE = re.compile(r"^source\.[a-z0-9]{1,8}$")
SUPPORTED = {".txt", ".md", ".csv", ".xlsx", ".pdf", ".docx"}


def file_id(value):
    if not ID.fullmatch(value):
        raise FileNotFoundError("File not found")
    return value


def display_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError("Invalid file name")
    if any(char in value for char in '/\\\0') or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid file name")
    return value.strip()


def now():
    return datetime.now(timezone.utc).isoformat()


class FileStore:
    def __init__(self, files_root, workspace, *, require_linux=True, quota_bytes=MAX_ACCOUNT_UPLOADS):
        Path(files_root).mkdir(parents=True, exist_ok=True)
        self.files = SafeRoot(files_root, require_linux=require_linux)
        self.workspace = SafeRoot(workspace, require_linux=require_linux)
        self.lock = threading.RLock()
        if not isinstance(quota_bytes, int) or quota_bytes <= 0:
            raise ValueError("Invalid account upload quota")
        self.quota_bytes = quota_bytes
        self.committed = {}
        self.reservations = {}
        self.written = {}
        self.committed_bytes = self.reserved_bytes = 0
        try:
            self.recount()
        except BaseException:
            self.close()
            raise

    def quota(self):
        with self.lock:
            return {"limit": self.quota_bytes, "used": self.committed_bytes, "reserved": self.reserved_bytes}

    def recount(self):
        # Source-file stat sizes are authoritative. Neither metadata.size nor
        # an HTTP Content-Length can reset or under-report persistent usage.
        with self.lock:
            if self.reservations:
                raise RuntimeError("Cannot recount while uploads are active")
            self.committed.clear()
            for identity, is_directory, _, is_link in self.files.entries():
                if not ID.fullmatch(identity) or is_link or not is_directory:
                    continue
                for name, _, is_file, is_link in self.files.entries(identity):
                    if SOURCE.fullmatch(name) and is_file and not is_link:
                        relative = identity + "/" + name
                        with self.files.open(relative) as handle:
                            self.committed[relative] = os.fstat(handle.fileno()).st_size
            self.committed_bytes = sum(self.committed.values())
            # Only records explicitly left uploading by this gateway are
            # incomplete and may be cleaned up after a process crash.
            for identity, is_directory, _, is_link in self.files.entries():
                if not ID.fullmatch(identity) or is_link or not is_directory:
                    continue
                try:
                    item = self.metadata(identity)
                except (FileNotFoundError, ValueError):
                    continue
                if (item.get("status") == "uploading" and
                        item.get("source") == identity + "/source" + item.get("extension", "") and
                        SOURCE.fullmatch(Path(item["source"]).name)):
                    self.delete(identity, incomplete=True)

    def reserve(self, identity, size):
        # Must be called with self.lock held.
        previous = self.reservations.get(identity, 0)
        growth = size - previous
        if growth > 0 and self.committed_bytes + self.reserved_bytes + growth > self.quota_bytes:
            raise QuotaExceeded("Account upload quota exceeded")
        self.reservations[identity] = size
        self.reserved_bytes += growth

    def release_reservation(self, identity):
        self.reserved_bytes -= self.reservations.pop(identity, 0)
        self.written.pop(identity, None)

    def close(self):
        self.files.close()
        self.workspace.close()

    def read_json(self, relative):
        with self.files.open(relative) as handle:
            return json.load(handle)

    def write_json(self, relative, data):
        parts = relative.split("/")
        temporary = "/".join(parts[:-1] + [".write-" + uuid.uuid4().hex])
        try:
            with self.files.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as handle:
                handle.write(json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            self.files.replace(temporary, relative)
        finally:
            try:
                self.files.unlink(temporary)
            except FileNotFoundError:
                pass

    def metadata(self, identity):
        return self.read_json(file_id(identity) + "/metadata.json")

    def update(self, identity, **values):
        with self.lock:
            metadata = self.metadata(identity)
            metadata.update(values, updated_at=now())
            self.write_json(identity + "/metadata.json", metadata)
            return metadata

    def public(self, metadata):
        return {key: value for key, value in metadata.items() if key != "source"}

    def list(self):
        items = []
        for item in self.files.path.iterdir():
            if not ID.fullmatch(item.name) or item.is_symlink() or not item.is_dir():
                continue
            try:
                items.append(self.public(self.metadata(item.name)))
            except (OSError, ValueError):
                continue
        return sorted(items, key=lambda item: item["created_at"], reverse=True)

    def begin_upload(self, name, *, expected_size=0):
        name = display_name(name)
        if not isinstance(expected_size, int) or not 0 <= expected_size <= MAX_UPLOAD:
            raise ValueError("Invalid upload size")
        identity = uuid.uuid4().hex
        suffix = Path(name).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = ".bin"
        source = identity + "/source" + suffix
        metadata = {
            "id": identity, "name": name, "extension": suffix,
            "size": 0, "status": "uploading", "created_at": now(), "updated_at": now(),
            "source": source, "truncated": False, "error": None,
        }
        with self.lock:
            self.reserve(identity, expected_size)
            self.written[identity] = 0
            handle = None
            made_directory = False
            try:
                self.files.mkdir(identity)
                made_directory = True
                handle = self.files.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                self.write_json(identity + "/metadata.json", metadata)
                return identity, handle, metadata
            except BaseException:
                if not made_directory:
                    self.release_reservation(identity)
                    raise
                if handle:
                    handle.close()
                try:
                    self.files.unlink(source)
                except FileNotFoundError:
                    pass
                finally:
                    # A failed unlink retains its actual source bytes as usage.
                    try:
                        with self.files.open(source) as remaining:
                            size = os.fstat(remaining.fileno()).st_size
                        self.committed[source] = size
                        self.committed_bytes += size
                    except FileNotFoundError:
                        pass
                    self.release_reservation(identity)
                if made_directory:
                    try:
                        self.files.unlink(identity + "/metadata.json")
                    except FileNotFoundError:
                        pass
                    self.files.rmdir(identity)
                raise

    def write_upload(self, identity, handle, data):
        with self.lock:
            if identity not in self.reservations:
                raise ValueError("Upload is not active")
            count = self.written[identity] + len(data)
            if count > MAX_UPLOAD:
                raise ValueError("File exceeds upload limit")
            if count > self.reservations[identity]:
                self.reserve(identity, count)
            written = handle.write(data)
            if written != len(data):
                raise OSError("Incomplete file write")
            self.written[identity] = count

    def finish_upload(self, identity, size):
        with self.lock:
            metadata = self.metadata(identity)
            if identity not in self.reservations:
                raise ValueError("Upload is not active")
            with self.files.open(metadata["source"]) as handle:
                actual = os.fstat(handle.fileno()).st_size
            if actual != size or actual > MAX_UPLOAD:
                raise ValueError("Upload size does not match stored source")
            self.reserve(identity, actual)
            status = "queued" if metadata["extension"] in SUPPORTED else "unsupported"
            metadata = self.update(identity, size=actual, status=status)
            self.committed[metadata["source"]] = actual
            self.committed_bytes += actual
            self.release_reservation(identity)
            return metadata

    def delete(self, identity, *, incomplete=False):
        with self.lock:
            metadata = self.metadata(identity)
            if metadata["status"] in ("parsing", "uploading") and not incomplete:
                raise ValueError("File is being parsed or uploaded")
            source = metadata["source"]
            try:
                self.files.unlink(source)
            except FileNotFoundError:
                pass
            # Free quota only after the original is gone. A cleanup error must
            # not free capacity for bytes that still remain on disk.
            self.committed_bytes -= self.committed.pop(source, 0)
            self.release_reservation(identity)
            for relative in (identity + "/result.json", identity + "/metadata.json"):
                try:
                    self.files.unlink(relative)
                except FileNotFoundError:
                    pass
            self.files.rmdir(identity)

    def source_path(self, identity):
        # Parser input is gateway-owned and never writable in the Agent container.
        metadata = self.metadata(identity)
        with self.files.open(metadata["source"]):
            pass
        return self.files.path / metadata["source"]

    def text(self, identity):
        metadata = self.metadata(identity)
        try:
            result = self.read_json(identity + "/result.json")
        except FileNotFoundError:
            result = {"text": "", "chunks": [], "truncated": False}
        return {
            "text": result["text"], "chunks": result["chunks"],
            "truncated": result.get("truncated", False),
            "status": metadata["status"], "name": metadata["name"],
        }

    def results(self, limit=2000):
        found = []
        stack = [""]
        examined = 0
        while stack and len(found) < limit and examined < 10000:
            directory = stack.pop()
            try:
                entries = self.workspace.entries(directory)
            except (OSError, UnsafePath):
                continue
            for name, is_directory, is_file, is_link in entries:
                examined += 1
                if examined > 10000 or len(found) >= limit:
                    break
                if name.startswith(".") or is_link:
                    continue
                relative = directory + "/" + name if directory else name
                if is_directory:
                    if relative.count("/") < 24:
                        stack.append(relative)
                    continue
                if not is_file:
                    continue
                try:
                    with self.workspace.open(relative) as handle:
                        info = os.fstat(handle.fileno())
                except (OSError, UnsafePath):
                    continue
                found.append({
                    "id": hashlib.sha256(relative.encode()).hexdigest(),
                    "name": name, "relative_path": relative,
                    "size": info.st_size, "modified_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                })
        return {"items": found, "truncated": bool(stack) or examined >= 10000 or len(found) >= limit}

    def result(self, identity):
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise FileNotFoundError("Result not found")
        for item in self.results()["items"]:
            if item["id"] == identity:
                return item
        raise FileNotFoundError("Result not found")