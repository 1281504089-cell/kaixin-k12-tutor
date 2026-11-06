"""Prepare platform resources; textbooks and private settings stay on the maintainer's Mac."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request


def run(args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def fetch(url, digest, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=90) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)
    with target.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == digest, "Asset checksum mismatch"
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=("macos-arm64", "windows-x64"))
    parser.add_argument("--common", type=Path, required=True)
    parser.add_argument("--common-sha256", required=True)
    args = parser.parse_args()
    expected = "windows-x64" if sys.platform == "win32" else "macos-" + ("arm64" if platform.machine().lower() == "arm64" else "x64")
    assert expected == args.target, f"Wrong native host: {expected}"
    with args.common.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == args.common_sha256
    root = Path.cwd()
    desktop = root / "apps/desktop"
    local = desktop / ".local"
    assets = local / "student-assets"
    assets.mkdir(parents=True)
    with tarfile.open(args.common) as package:
        package.extractall(assets, filter="data")
    ocr = root.parent / "student-ocr-languages.tar.gz"
    with ocr.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == "b37f2f975303543a6c3e391b3cb6e528bdec911e7918920af4b220a7c1c2ef36"
    with tarfile.open(ocr) as package:
        package.extractall(assets, filter="data")
    assert not (assets / "student-seed").exists()
    (assets / "student-seed").mkdir()
    prefix = local / "native-prefix"
    run([sys.executable, desktop / "scripts/prepare-student-native.py", "--target", args.target,
         "--cache", local / "native-cache", "--prefix", prefix])
    shutil.copytree(assets / "support/tessdata", prefix / ("Library/share/tessdata" if sys.platform == "win32" else "share/tessdata"), dirs_exist_ok=True)
    env = os.environ.copy()
    if sys.platform == "win32":
        spec = next(x for x in json.loads((desktop / "student-resources.json").read_text())["assets"] if x["file"].startswith("TinyTeX-1-windows"))
        installer = fetch(spec["url"], spec["sha256"], local / spec["file"])
        extracted = local / "windows-tex"
        seven = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "7-Zip/7z.exe"
        assert seven.is_file(), "Runner must have its standard 7-Zip installation"
        run([seven, "x", installer, "-y", "-o" + str(extracted)])
        pdftex = next(extracted.rglob("pdftex.exe"))
        windows_tex = pdftex.parent.parent.parent
        tex = assets / "support/tex"
        # TeX macros/fonts are the validated common snapshot; executable binaries are Windows-native.
        shutil.rmtree(tex / "bin")
        shutil.copytree(windows_tex / "bin", tex / "bin")
        for name in ("tlpkg/tlperl", "texmf-var", "texmf-config"):
            if (windows_tex / name).exists():
                shutil.copytree(windows_tex / name, tex / name, dirs_exist_ok=True)
        dvisvgm = next(x for x in json.loads((desktop / "student-resources.json").read_text())["assets"] if x["file"].startswith("dvisvgm.windows"))
        package_path = root.parent / dvisvgm["file"]
        with package_path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == dvisvgm["sha256"]
        with tarfile.open(package_path) as package:
            package.extractall(tex, filter="data")
        assert (tex / "bin/windows/dvisvgm.exe").is_file()
        run([tex / "bin/windows/mktexlsr.exe"])
    else:
        env.update(PATH=str(prefix / "bin") + os.pathsep + env["PATH"],
                   PKG_CONFIG_PATH=str(prefix / "lib/pkgconfig"),
                   DYLD_LIBRARY_PATH=str(prefix / "lib"), MACOSX_DEPLOYMENT_TARGET="13.0")
        run([sys.executable, "-m", "pip", "install", "delocate==0.13.0", "wheel==0.45.1"], env=env)
        metadata = json.load(urllib.request.urlopen("https://pypi.org/pypi/pycairo/1.29.2/json", timeout=60))
        source = next(x for x in metadata["urls"] if x["packagetype"] == "sdist")
        lock = (root / "requirements/student-runtime-macos-arm64.lock").read_text()
        section = re.search(r"(?ms)^pycairo==1\.29\.2.*?(?=^\S|\Z)", lock).group()
        assert "sha256:" + source["digests"]["sha256"] in section
        sdist = fetch(source["url"], source["digests"]["sha256"], local / source["filename"])
        wheels = local / "cairo-wheel"
        run([sys.executable, "-m", "pip", "wheel", sdist, "--no-deps", "--wheel-dir", wheels], env=env)
        run(["delocate-wheel", "--require-archs", "arm64",
             "-w", assets / "python-wheels", next(wheels.glob("pycairo-*.whl"))], env=env)
    run([sys.executable, desktop / "scripts/prepare-student-support.py", "--native-prefix", prefix,
         "--output", assets, "--models"], env=env)
    receipt = json.loads((assets / "RESOURCE_INFO.json").read_text())
    assert receipt["target"] == args.target
    print("Prepared locked native components; no API settings or textbook originals uploaded")


if __name__ == "__main__":
    main()
