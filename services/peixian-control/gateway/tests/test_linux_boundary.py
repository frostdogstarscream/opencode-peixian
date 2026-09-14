"""These cases must run inside the Linux gateway image before deployment acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from gateway.safe_fs import SafeRoot, UnsafePath

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires Linux production isolation primitives")


def test_pinned_root_and_parent_symlink_substitution(tmp_path):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "sub").mkdir()
    (workspace / "sub" / "data.txt").write_text("account data", encoding="utf-8")
    (outside / "data.txt").write_text("external private data", encoding="utf-8")
    root = SafeRoot(workspace)
    try:
        # Replacement between operations cannot cause traversal to the target.
        (workspace / "sub").rename(workspace / "original-sub")
        (workspace / "sub").symlink_to(outside, target_is_directory=True)
        with pytest.raises((OSError, UnsafePath)):
            root.open("sub/data.txt")
        assert next(item for item in root.entries() if item[0] == "sub")[3]
        with root.open("original-sub/data.txt") as handle:
            assert handle.read() == b"account data"
        # Replacing the root path itself cannot replace the already pinned FD.
        workspace.rename(tmp_path / "old-workspace")
        workspace.symlink_to(outside, target_is_directory=True)
        with root.open("original-sub/data.txt") as handle:
            assert handle.read() == b"account data"
    finally:
        root.close()


def test_parser_address_space_cpu_filesize_and_fd_limits():
    package_root = str(Path(__file__).resolve().parents[2])
    script = (
        "import sys,json,resource;"
        f"sys.path.insert(0,{package_root!r});"
        "from gateway.parser import apply_limits;apply_limits();"
        "print(json.dumps({k:resource.getrlimit(getattr(resource,k))[0] "
        "for k in ('RLIMIT_AS','RLIMIT_CPU','RLIMIT_FSIZE','RLIMIT_NOFILE','RLIMIT_CORE')}))"
    )
    response = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, timeout=10, check=True)
    assert json.loads(response.stdout) == {
        "RLIMIT_AS": 384 * 1024 * 1024, "RLIMIT_CPU": 60,
        "RLIMIT_FSIZE": 200 * 1024 * 1024, "RLIMIT_NOFILE": 64, "RLIMIT_CORE": 0,
    }


def test_named_pipe_is_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    root = SafeRoot(tmp_path)
    try:
        with pytest.raises(UnsafePath):
            root.open("pipe")
    finally:
        root.close()
