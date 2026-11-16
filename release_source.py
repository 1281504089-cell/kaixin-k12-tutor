"""Frozen source and runtime inventory shared by the disposable release jobs."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DOC_FIGURES = ("assets/figs/web-dev/", "assets/figs/system/")
RUNTIME_ROOTS = ("deeptutor/", "deeptutor_cli/", "requirements/", "scripts/", "assets/")
RUNTIME_FILES = {"LICENSE", "THIRD_PARTY_NOTICES.md", "build_metadata.py", "build_support.py", "pyproject.toml", "setup.py"}


def sha(file):
    digest = hashlib.sha256()
    with Path(file).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def safe_name(value):
    name = PurePosixPath(value)
    if (not isinstance(value, str) or not value or name.is_absolute() or ".." in name.parts
        or "\\" in value or ":" in value or name.as_posix() != value
        or {".git", "node_modules", "__pycache__", ".DS_Store"}.intersection(name.parts)
        or "data/user" in value or "signing-private" in value.lower()):
        raise ValueError("Unsafe release path: " + str(value))
    return value


def aggregate(rows):
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda row: row["file"]):
        digest.update(row["file"].encode() + b"\0" + bytes.fromhex(row["sha256"]))
    return digest.hexdigest()


def inventory(source, excluded=()):
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode().rstrip("\0").split("\0")
    rows = []
    for name in sorted(name for name in names if name != "SOURCE_FREEZE.json" and name not in set(excluded)):
        safe_name(name)
        file = Path(source) / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("Source must contain regular frozen files: " + name)
        rows.append({"file": name, "bytes": file.stat().st_size, "sha256": sha(file), "mode": file.stat().st_mode & 0o777})
    return rows


def runtime_rows(rows):
    return [row for row in rows if (row["file"].startswith(RUNTIME_ROOTS) or row["file"] in RUNTIME_FILES)
            and not row["file"].startswith(DOC_FIGURES)]


def verify_files(root, rows):
    for row in rows:
        file = Path(root) / safe_name(row["file"])
        if file.is_symlink() or not file.is_file() or file.stat().st_size != row["bytes"] or sha(file) != row["sha256"]:
            raise ValueError("Frozen file differs: " + row["file"])


def add_file(package, name, stream, size, mode=0o644):
    safe_name(name)
    info = tarfile.TarInfo(name)
    info.size, info.mode = size, mode
    info.mtime = info.uid = info.gid = 0
    package.addfile(info, stream)


def join_source_overlay(root, archive, descriptor):
    """CI uses transport parts; small main metadata rebuilds from one release asset."""
    present = [(Path(root) / safe_name(row["file"])).is_file() for row in descriptor["parts"]]
    digest = hashlib.sha256()
    with Path(archive).open("xb") as output:
        if all(present):
            for row in descriptor["parts"]:
                file = Path(root) / row["file"]
                if file.stat().st_size != row["bytes"] or sha(file) != row["sha256"]:
                    raise ValueError("Source overlay part checksum mismatch")
                with file.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block); output.write(block)
        elif not any(present) and descriptor.get("remote_archive"):
            remote = descriptor["remote_archive"]
            url = urlparse(remote["url"])
            if (url.scheme != "https" or url.netloc != "github.com" or not url.path.startswith("/1281504089-cell/kaixin-k12-tutor/releases/download/")
                or url.query or url.fragment or not 0 < remote["bytes"] <= 256 * 1024 * 1024
                or remote["sha256"] != descriptor["archive_sha256"]):
                raise ValueError("Untrusted source overlay release asset")
            with urlopen(Request(remote["url"], headers={"User-Agent": "Kaixin-Frozen-Source"}), timeout=60) as stream:
                redirected = urlparse(stream.geturl())
                if redirected.scheme != "https" or redirected.hostname not in {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}:
                    raise ValueError("Untrusted source overlay redirect")
                total = 0
                while block := stream.read(1024 * 1024):
                    total += len(block)
                    if total > remote["bytes"]:
                        raise ValueError("Oversized source overlay release asset")
                    digest.update(block); output.write(block)
                if total != remote["bytes"]:
                    raise ValueError("Truncated source overlay release asset")
        else:
            raise ValueError("Source overlay transport parts are incomplete")
    if digest.hexdigest() != descriptor["archive_sha256"]:
        raise ValueError("Source overlay archive checksum mismatch")


def apply_overlay(root, destination, descriptor):
    """Apply only hash-bound regular files; never trust tar member destinations."""
    root, destination = Path(root), Path(destination)
    manifest_file = root / safe_name(descriptor["manifest"])
    if sha(manifest_file) != descriptor["manifest_sha256"]:
        raise ValueError("Frozen source inventory checksum mismatch")
    manifest = json.loads(manifest_file.read_text())
    if aggregate(inventory(destination)) != manifest["baseline_source_files_sha256"]:
        raise ValueError("Source overlay parent differs from the published source")
    for name in manifest["removed"]:
        file = destination / safe_name(name)
        if file.is_symlink():
            raise ValueError("Linked removed source")
        file.unlink()
    archive = root / "source-overlay.tar.gz"
    join_source_overlay(root, archive, descriptor)
    expected = {row["file"]: row for row in manifest["changed"]}
    seen = set()
    with tarfile.open(archive) as package:
        for item in package:
            name = safe_name(item.name)
            if not item.isfile() or name not in expected or name in seen:
                raise ValueError("Unexpected source overlay member")
            row = expected[name]
            if item.size != row["bytes"] or item.mode != row["mode"]:
                raise ValueError("Source overlay member metadata mismatch")
            target = destination / name
            current = destination
            for part in PurePosixPath(name).parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError("Source overlay enters linked path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output, package.extractfile(item) as stream:
                digest = hashlib.sha256()
                while block := stream.read(1024 * 1024):
                    output.write(block)
                    digest.update(block)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("Source overlay member checksum mismatch")
            target.chmod(row["mode"])
            seen.add(name)
    if seen != set(expected):
        raise ValueError("Source overlay is incomplete")
    verify_files(destination, manifest["files"])
    if aggregate(manifest["files"]) != descriptor["source_files_sha256"]:
        raise ValueError("Final source inventory differs")
    archive.unlink()
    return manifest
