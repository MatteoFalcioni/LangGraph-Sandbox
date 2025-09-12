# tests/test_io_put_bytes.py
import io
import tarfile

import pytest

from src.sandbox.io import put_bytes, _tar_single_file_bytes


class FakeContainer:
    def __init__(self):
        self.mkdirs = []
        self.archives = []  # (path, tar_bytes)

    def exec_run(self, cmd):
        # Expect: ["/bin/sh","-lc","mkdir -p -- <dir>"]
        assert isinstance(cmd, list) and cmd[:2] == ["/bin/sh", "-lc"]
        assert "mkdir -p" in cmd[2]
        self.mkdirs.append(cmd[2])
        return (0, b"")

    def put_archive(self, path, data):
        assert path.startswith("/")
        assert isinstance(data, (bytes, bytearray))
        # verify tar looks valid and contains one file
        bio = io.BytesIO(data)
        with tarfile.open(fileobj=bio, mode="r:*") as tar:
            members = tar.getmembers()
            assert len(members) == 1
            m = members[0]
            f = tar.extractfile(m)
            assert f is not None
            _ = f.read()
        self.archives.append((path, data))
        return True


def test_tar_single_file_bytes_basic():
    content = b"hello"
    tb = _tar_single_file_bytes("foo.txt", content, mode=0o600, mtime=1)
    bio = io.BytesIO(tb)
    with tarfile.open(fileobj=bio, mode="r:*") as tar:
        members = tar.getmembers()
        assert len(members) == 1
        m = members[0]
        assert m.name == "foo.txt"
        assert m.size == 5
        assert (m.mode & 0o777) == 0o600
        assert m.mtime == 1
        f = tar.extractfile(m)
        assert f.read() == content


def test_put_bytes_happy_path(tmp_path):
    fake = FakeContainer()
    put_bytes(fake, "/session/data/test.parquet", b"BYTES", mode=0o644)
    assert any("/session/data" in s for s in fake.mkdirs)
    assert fake.archives and fake.archives[0][0] == "/session/data"


def test_put_bytes_requires_file_path(Fake=FakeContainer):
    fake = Fake()
    with pytest.raises(ValueError):
        put_bytes(fake, "/session/data/", b"x")
