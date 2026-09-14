"""Linux directory-fd filesystem operations; no user-controlled absolute paths."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat


class UnsafePath(ValueError):
    pass


def components(relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or "\0" in relative:
        raise UnsafePath("Invalid relative path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        raise UnsafePath("Invalid relative path")
    return parts


class SafeRoot:
    def __init__(self, path, *, require_linux=True):
        self.path = Path(path)
        if self.path.is_symlink() or not self.path.is_dir():
            raise UnsafePath("Storage root must be an existing ordinary directory")
        self.path = self.path.resolve(strict=True)
        self.use_dir_fd = os.name == "posix" and os.open in os.supports_dir_fd
        if require_linux and not self.use_dir_fd:
            raise RuntimeError("Production file isolation requires Linux directory-fd operations")
        self.fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)) if self.use_dir_fd else None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def test_path(self, parts):
        # Non-Linux fallback is available only to explicitly constructed local tests.
        current = self.path
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise UnsafePath("Symbolic links are not allowed")
        if not current.resolve(strict=False).is_relative_to(self.path):
            raise UnsafePath("Path escapes storage root")
        return current

    @contextmanager
    def parent(self, relative):
        parts = components(relative)
        if not self.use_dir_fd:
            yield None, self.test_path(parts)
            return
        parent_fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            yield parent_fd, parts[-1]
        finally:
            os.close(parent_fd)

    def entries(self, relative=""):
        """Snapshot a directory opened beneath the pinned root, never following links."""
        if not self.use_dir_fd:
            directory = self.test_path(components(relative)) if relative else self.path
            with os.scandir(directory) as scan:
                return [(entry.name, entry.is_dir(follow_symlinks=False),
                         entry.is_file(follow_symlinks=False), entry.is_symlink()) for entry in scan]
        fd = os.dup(self.fd)
        try:
            for part in components(relative) if relative else []:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            with os.scandir(fd) as scan:
                return [(entry.name, entry.is_dir(follow_symlinks=False),
                         entry.is_file(follow_symlinks=False), entry.is_symlink()) for entry in scan]
        finally:
            os.close(fd)

    def mkdir(self, relative):
        with self.parent(relative) as (parent_fd, name):
            if parent_fd is None:
                os.mkdir(name, mode=0o700)
            else:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)

    def open(self, relative, flags=os.O_RDONLY):
        with self.parent(relative) as (parent_fd, name):
            fd = os.open(name, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0), 0o600, dir_fd=parent_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                os.close(fd)
                raise UnsafePath("Only regular files are allowed")
            return os.fdopen(fd, "rb" if flags == os.O_RDONLY else "wb")

    def unlink(self, relative):
        with self.parent(relative) as (parent_fd, name):
            os.unlink(name, dir_fd=parent_fd)

    def rmdir(self, relative):
        with self.parent(relative) as (parent_fd, name):
            os.rmdir(name, dir_fd=parent_fd)

    def replace(self, source, target):
        with self.parent(source) as (source_fd, source_name), self.parent(target) as (target_fd, target_name):
            os.replace(source_name, target_name, src_dir_fd=source_fd, dst_dir_fd=target_fd)