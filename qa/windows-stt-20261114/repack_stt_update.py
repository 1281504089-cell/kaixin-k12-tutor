"""Overlay the frozen STT fix on pinned public archives without extracting resources."""

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import tarfile
import tempfile


SOURCE_COMMIT = "525157ebded003193f2927960d983e4819e08513"
SOURCE_FILES = {
    "deeptutor/api/main.py": "9ac66c355c4e5c4f61593b436b9bc246bd16c3704a0e1742523fb03b26e5aa96",
    "deeptutor/services/local_ai/__init__.py": "4a8329855a88c06944fca84ab98c5374d88586ef7358199b456bb9e633951f5f",
    "deeptutor/services/local_ai/worker.py": "057a2f9c0f0ff9311d09bd26f1f3031cd9ecf42505d3523865675945176afaed",
    "deeptutor/services/voice/adapters/local.py": "95126dc3d215d9890c3244126e2910f56ca9fbb69c9b9f1d07daeade180af3ce",
}
BASELINES = {
    "core": ("kaixin-core-20261113-sync2.tar.gz", "0b1102e17c2c9f08f0840d883ca583bf94c1dafff72c85d08ce5b4daf5b1a129"),
    "windows-x64": ("kaixin-bridge-20261113-sync2-windows-x64.tar.gz", "e7ea03c8d66eb755aaff380631cad70567e0bcbe841a4658a3dfdada237c3754"),
    "macos-x64": ("kaixin-bridge-20261113-sync2-macos-x64.tar.gz", "a8304460b78e4dd6b93a335b5403a16d6d79bd5a16f4ad7027742138df85e358"),
    "macos-arm64": ("kaixin-bridge-20261113-sync2-macos-arm64.tar.gz", "e531791f8355607d2ba4eb9b2b2d1ab3500f5aecfbad5a9ac66382ca4947d960"),
}


def sha256(file):
    digest = hashlib.sha256()
    with Path(file).open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name):
    if "\\" in name or "\0" in name or PurePosixPath(name).is_absolute() or re.match(r"^[A-Za-z]:", name):
        raise ValueError("Unsafe archive path")
    if ".." in PurePosixPath(name).parts:
        raise ValueError("Archive path traversal")
    return posixpath.normpath(name)


def validate_member(member, seen):
    name = safe_name(member.name)
    if name in seen:
        raise ValueError("Duplicate archive member: " + name)
    seen.add(name)
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()) or member.issparse():
        raise ValueError("Unsupported archive member: " + name)
    if member.issym() or member.islnk():
        target = member.linkname
        if "\\" in target or "\0" in target or PurePosixPath(target).is_absolute() or re.match(r"^[A-Za-z]:", target):
            raise ValueError("Unsafe archive link")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target) if member.issym() else target)
        if resolved == ".." or resolved.startswith("../"):
            raise ValueError("Archive link traversal")
    return name


class HashedReader:
    def __init__(self, stream):
        self.stream = stream
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        data = self.stream.read(size)
        self.digest.update(data)
        return data


def fingerprint(member, digest):
    metadata = member.get_info()
    metadata.pop("chksum")  # A changed file size necessarily changes its tar header checksum.
    return (metadata, member.pax_headers, digest)


def repack(baseline, destination, replacements, expected_baseline_sha):
    if sha256(baseline) != expected_baseline_sha:
        raise ValueError("Published baseline SHA256 mismatch")
    if destination.exists():
        raise ValueError("Refusing to replace an existing output archive")
    partial = destination.with_suffix(destination.suffix + ".partial")
    seen, changed, expected = set(), set(), {}
    try:
        with tarfile.open(baseline, "r|gz") as source, partial.open("xb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as output:
                    for member in source:
                        name = validate_member(member, seen)
                        info = copy.copy(member)
                        info.pax_headers = dict(member.pax_headers)
                        digest = None
                        if name in replacements:
                            if not member.isfile():
                                raise ValueError("Replacement is not a regular file: " + name)
                            data = replacements[name]
                            info.size = len(data)
                            info.pax_headers.pop("size", None)
                            output.addfile(info, io.BytesIO(data))
                            digest = hashlib.sha256(data).hexdigest()
                            changed.add(name)
                        elif member.isfile():
                            reader = HashedReader(source.extractfile(member))
                            output.addfile(info, reader)
                            digest = reader.digest.hexdigest()
                        else:
                            output.addfile(info)
                        expected[name] = fingerprint(info, digest)
        if changed != replacements.keys():
            raise ValueError("Archive must contain every replacement exactly once")
        verified = set()
        with tarfile.open(partial, "r|gz") as output:
            for member in output:
                name = validate_member(member, verified)
                digest = None
                if member.isfile():
                    reader = HashedReader(output.extractfile(member))
                    while reader.read(8 * 1024 * 1024):
                        pass
                    digest = reader.digest.hexdigest()
                if name not in expected or fingerprint(member, digest) != expected[name]:
                    raise ValueError("Repacked member content or metadata changed: " + name)
        if verified != seen:
            raise ValueError("Repacked member inventory differs from baseline")
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return len(seen)


def source_replacements(source):
    if os.environ.get("SOURCE_COMMIT", SOURCE_COMMIT) != SOURCE_COMMIT:
        raise ValueError("Unexpected frozen source commit")
    result = {"BUILD_COMMIT": (SOURCE_COMMIT + "\n").encode()}
    for name, expected in SOURCE_FILES.items():
        data = (source / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Frozen source file differs: " + name)
        result["core/" + name] = data
    return result


def build(target, source, output):
    replacements = source_replacements(source)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "baseline"
    cache.mkdir()
    old_name, old_sha = BASELINES[target]
    subprocess.run(["gh", "release", "download", "core-updates", "--pattern", old_name, "--dir", str(cache)], check=True)
    new_name = "kaixin-core-20261114-stt.tar.gz" if target == "core" else f"kaixin-bridge-20261114-stt-{target}.tar.gz"
    archive = output / new_name
    count = repack(cache / old_name, archive, replacements, old_sha)
    report = {
        "target": target,
        "source_commit": SOURCE_COMMIT,
        "baseline_archive": old_name,
        "baseline_sha256": old_sha,
        "baseline_sha256_verified": True,
        "archive": new_name,
        "sha256": sha256(archive),
        "bytes": archive.stat().st_size,
        "member_count": count,
        "replaced_member_count": len(replacements),
        "replaced_members": {name: hashlib.sha256(data).hexdigest() for name, data in replacements.items()},
        "unchanged_members": count - len(replacements),
        "all_member_contents_and_metadata_verified": True,
        "new_members": 0,
        "private_signing_key_used": False,
        "production_manifest_changed": False,
        "validation_scope": "Reused the previously validated public native-resource baseline; overlaid four Python files and BUILD_COMMIT only. No physical Apple Silicon Mac microphone test.",
    }
    report_file = output / f"stt-repack-20261114-{target}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return archive, report_file


def self_test():
    with tempfile.TemporaryDirectory(prefix="stt-repack-") as temporary:
        root = Path(temporary)
        replacements = {"BUILD_COMMIT": b"new\n", **{f"core/file{i}.py": f"new{i}".encode() for i in range(4)}}

        def fixture(path, extra=()):
            with tarfile.open(path, "w:gz") as archive:
                for name in replacements:
                    info = tarfile.TarInfo("./" + name)
                    info.size, info.mode, info.mtime = 3, 0o640, 123
                    archive.addfile(info, io.BytesIO(b"old"))
                directory = tarfile.TarInfo("lib")
                directory.type, directory.mode = tarfile.DIRTYPE, 0o750
                archive.addfile(directory)
                link = tarfile.TarInfo("lib/link")
                link.type, link.linkname = tarfile.SYMTYPE, "../BUILD_COMMIT"
                archive.addfile(link)
                for name in extra:
                    archive.addfile(tarfile.TarInfo(name))

        baseline = root / "baseline.tar.gz"
        fixture(baseline)
        assert repack(baseline, root / "result.tar.gz", replacements, sha256(baseline)) == 7
        for index, (extra, expected) in enumerate([
            (("core/../outside",), "traversal"),
            (("core/file0.py",), "Duplicate"),
        ]):
            invalid = root / f"invalid{index}.tar.gz"
            fixture(invalid, extra)
            try:
                repack(invalid, root / f"rejected{index}.tar.gz", replacements, sha256(invalid))
            except ValueError as exc:
                assert expected in str(exc)
            else:
                raise AssertionError("Unsafe archive was accepted")
        try:
            repack(baseline, root / "bad-hash.tar.gz", replacements, "0" * 64)
        except ValueError as exc:
            assert "SHA256" in str(exc)
        else:
            raise AssertionError("Wrong baseline hash was accepted")
    print("PASS: streaming replacement, inventory, modes, symlinks, traversal, duplicates and baseline hash")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--target", choices=BASELINES)
    parser.add_argument("--source", type=Path, default=Path("student-source"))
    parser.add_argument("--output", type=Path, default=Path("stt-release"))
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.target:
        build(args.target, args.source, args.output)
    else:
        parser.error("--target is required")
