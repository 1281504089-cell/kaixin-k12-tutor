"""Prepare locked FFmpeg/ffprobe, OCR and Cairo resources on their native build host."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote
import urllib.request

DESKTOP = Path(__file__).resolve().parents[1]


def fetch(url: str, digest: str, target: Path) -> Path:
    if target.is_file():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == digest:
                return target
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".partial", dir=target.parent
    )
    os.close(descriptor)
    partial = Path(name)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
        with partial.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("Native asset checksum mismatch: " + target.name)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def host_target() -> str:
    if sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}:
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos-" + ("arm64" if platform.machine().lower() == "arm64" else "x64")
    raise ValueError("Native preparation requires Windows x64 or macOS")


def prepare(target: str, cache: Path, prefix: Path | None, download_only: bool):
    if not download_only and (target != host_target() or prefix is None):
        raise ValueError(
            "Install on the matching native host and provide --prefix; use --download-only for cross-platform preparation"
        )
    lock = json.loads((DESKTOP / "platforms" / target / "native-lock.json").read_text())
    if lock["target"] != target:
        raise ValueError("Native lock target mismatch")
    packages = lock["packages"]
    for item in packages:
        if not item["url"].startswith("https://conda.anaconda.org/conda-forge/"):
            raise ValueError("Unexpected native package origin")
        if len(item["sha256"]) != 64:
            raise ValueError("Missing native package hash")

    def download(item):
        filename = unquote(item["url"].rsplit("/", 1)[1])
        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise ValueError("Unsafe native package filename")
        return fetch(item["url"], item["sha256"], cache / item["sha256"] / filename)

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(download, packages))
    if not download_only:
        spec = json.loads((DESKTOP / "student-resources.json").read_text())["micromamba"][target]
        executable = fetch(
            spec["url"],
            spec["sha256"],
            cache / ("micromamba.exe" if sys.platform == "win32" else "micromamba"),
        )
        executable.chmod(0o755)
        explicit = cache / (target + "-explicit.txt")
        explicit.write_text(
            "@EXPLICIT\n"
            + "\n".join(
                file.resolve().as_uri() + "#" + item["md5"] for file, item in zip(files, packages)
            )
            + "\n"
        )
        subprocess.run(
            [
                str(executable),
                "create",
                "--yes",
                "--no-rc",
                "--offline",
                "--prefix",
                str(prefix.resolve()),
                "--file",
                str(explicit.resolve()),
            ],
            env={**os.environ, "MAMBA_ROOT_PREFIX": str((cache / "mamba-root").resolve())},
            check=True,
        )
    result = {
        "target": target,
        "packages": len(files),
        "sha256_verified": True,
        "installed": not download_only,
    }
    (cache / (target + "-receipt.json")).write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", choices=("macos-x64", "macos-arm64", "windows-x64"), required=True
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--prefix", type=Path)
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.target, args.cache, args.prefix, args.download_only)))
