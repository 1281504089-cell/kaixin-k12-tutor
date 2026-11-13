#!/usr/bin/env python3
"""Build a shell-only migration from an already built final installed app."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
APP = "开心动力超级学霸"
TARGETS = {"macos-x64", "macos-arm64", "windows-x64"}


def read_json(file):
    return json.loads(Path(file).read_text(encoding="utf-8"))


def digest(file):
    value = hashlib.sha256()
    with Path(file).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(p) for p in args], check=True, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout


def resources(app, target):
    return app / ("Contents/Resources" if target.startswith("macos-") else "resources")


def reject_overlap(*paths):
    resolved = [Path(p).resolve() for p in paths]
    for i, first in enumerate(resolved):
        for second in resolved[i + 1:]:
            if first == second or first in second.parents or second in first.parents:
                raise ValueError("Application, isolated profile and output must be separate directories")


def verify_shell(app, target, expected):
    shell = resources(app, target) / "app"
    pkg = read_json(shell / "package.json")
    if pkg.get("name") != "kaixin-super-scholar" or pkg.get("main") != "src/entry.mjs" or pkg.get("type") != "module":
        raise ValueError("Input is not a packaged Kaixin desktop application")
    allowed = {"src", "assets", "README.md", "package.json", "LICENSE"}
    if set(p.name for p in shell.iterdir()) - allowed:
        raise ValueError("Unexpected app payload; refuse to package possible developer or user data")
    for name, sha in expected["files"].items():
        if digest(shell / name) != sha:
            raise ValueError(f"Final shell differs from the frozen source: {name}")
    for folder in ("src", "assets"):
        actual = {p.relative_to(shell).as_posix() for p in (shell / folder).rglob("*") if p.is_file()}
        frozen = {p for p in expected["files"] if p.startswith(folder + "/")}
        if actual != frozen:
            raise ValueError(f"Unexpected file set in {folder}")


def verify_executable(app, target):
    executable = app / (f"Contents/MacOS/{APP}" if target.startswith("macos-") else f"{APP}.exe")
    with executable.open("rb") as stream:
        header = stream.read(64)
        if target == "windows-x64":
            if len(header) != 64 or header[:2] != b"MZ":
                raise ValueError("Not a Windows executable")
            stream.seek(struct.unpack_from("<I", header, 60)[0])
            pe = stream.read(6)
            if pe != b"PE\0\0\x64\x86":
                raise ValueError("Windows migration requires the final x64 executable")
        else:
            cpu = 0x0100000C if target == "macos-arm64" else 0x01000007
            if header[:4] == b"\xcf\xfa\xed\xfe":
                cpus = [struct.unpack_from("<I", header, 4)[0]]
            elif header[:4] == b"\xca\xfe\xba\xbe":
                count = struct.unpack_from(">I", header, 4)[0]
                if count > 16:
                    raise ValueError("Invalid Mach-O architecture count")
                stream.seek(8)
                rows = stream.read(count * 20)
                cpus = [struct.unpack_from(">I", rows, i * 20)[0] for i in range(count)]
            else:
                raise ValueError("Not a supported macOS executable")
            if cpu not in cpus:
                raise ValueError("macOS executable architecture differs from target")


def stage_app(source, stage, target, baseline):
    source = source.resolve()
    for file in source.rglob("*"):
        if file.is_symlink() and not file.resolve().is_relative_to(source):
            raise ValueError("Application contains an external symlink")
    skipped = resources(source, target)

    def ignore(directory, names):
        return [n for n in names if Path(directory) == skipped and n in {"seed", "update"}]

    shutil.copytree(source, stage, symlinks=True, ignore=ignore)
    seed = resources(stage, target) / "seed"
    seed.mkdir()
    shutil.copy2(baseline, seed / "runtime.json")
    shell = resources(stage, target) / "app"
    shutil.copy2(HERE / "launcher-migration-check.mjs", shell / "launcher-migration-check.mjs")
    return shell


def build(args):
    target = args.target
    source = Path(args.final_installed_app_dir).resolve(strict=True)
    profile = Path(args.existing_isolated_profile).resolve(strict=True)
    output = Path(args.output_dir).resolve()
    reject_overlap(source, profile, output)
    if read_json(profile / ".launcher-migration-synthetic.json").get("synthetic") is not True:
        raise ValueError("Use an existing synthetic isolated test profile, never a real learner profile")
    expected = read_json(HERE / "frozen-shell.json")
    verify_shell(source, target, expected)
    verify_executable(source, target)
    arch = target.split("-")[-1]
    baseline = Path(args.baseline_manifest).resolve(strict=True) if args.baseline_manifest else (
        HERE / "baselines" / f"runtime-{target}.json")
    baseline_raw = baseline.read_bytes()
    metadata = json.loads(baseline_raw)
    if metadata.get("baseRuntimeId") or metadata.get("runtimeId") != f"1.7.1-77f2ba387-{arch}":
        raise ValueError("Need authentic old 77f2ba387 full seed metadata, not a thin core update")
    output.mkdir(parents=True, exist_ok=True)
    version = expected["commit"][:12]
    name = f"Kaixin-Launcher-Migration-{version}-{target}"
    artifact = output / (name + (".zip" if target.startswith("macos-") else "-Setup.exe"))
    report_file = output / (name + "-report.json")
    if artifact.exists() or report_file.exists():
        raise FileExistsError("Existing output will not be overwritten; choose a clean output directory")
    with tempfile.TemporaryDirectory(prefix="launcher-migration-", dir=output) as temporary:
        root = Path(temporary)
        pending_artifact = root / artifact.name
        stage = root / (APP + ".app" if target.startswith("macos-") else "app")
        shell = stage_app(source, stage, target, baseline)
        inventory_root = stage / "Contents" if target.startswith("macos-") else stage
        code = "const {tree}=await import(process.env.MIGRATION_HELPER); console.log(JSON.stringify(await tree(process.env.MIGRATION_ROOT)));"
        env = {**os.environ, "MIGRATION_HELPER": (shell / "launcher-migration-check.mjs").as_uri(), "MIGRATION_ROOT": str(inventory_root)}
        files = json.loads(run([args.node, "--input-type=module", "-e", code], env=env))
        (shell / "launcher-migration-payload.json").write_text(json.dumps({"target": target, "commit": expected["commit"], "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
        check_args = [args.node, shell / "launcher-migration-check.mjs", "--profile", profile,
                      "--target", target, "--require-isolated", "--package-preflight"]
        check = json.loads(run(check_args))
        if target.startswith("macos-"):
            if sys.platform != "darwin":
                raise RuntimeError("Mac .app signing and ZIP must be built on macOS")
            run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", stage])
            run(["/usr/bin/codesign", "--verify", "--deep", "--strict", stage])
            json.loads(run(check_args))
            run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", stage, pending_artifact])
            container = "macOS app ZIP; ad-hoc signed, not notarized"
        else:
            makensis = args.makensis or shutil.which("makensis")
            if not makensis:
                raise RuntimeError("NSIS makensis is required. No portable ZIP is silently substituted for Setup.exe")
            icon = shell / "assets/icon.ico"
            if not icon.is_file():
                raise FileNotFoundError(icon)
            defines = [f"/DSOURCE={stage}", f"/DOUTFILE={pending_artifact}", f"/DICON={icon}", f"/DVERSION={version}", "/DFILEVERSION=1.7.1.0"]
            if args.test_installer:
                defines.append("/DTEST_MODE")
            run([makensis, "/INPUTCHARSET", "UTF8", *defines, HERE / "windows-migration.nsi"], errors="replace")
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            product_name = run([powershell, "-NoProfile", "-NonInteractive", "-Command",
                "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); [Diagnostics.FileVersionInfo]::GetVersionInfo($env:KX_MIGRATION_SETUP).ProductName"],
                env={**os.environ, "KX_MIGRATION_SETUP": str(pending_artifact)}).strip()
            if product_name != APP:
                raise ValueError("Compiled installer changed the Chinese application name: " + product_name)
            container = "per-user NSIS migration Setup; no Runtime parts"
        report = {"formatVersion": 1, "target": target, "frozenShellCommit": expected["commit"],
                  "artifact": artifact.name, "size": pending_artifact.stat().st_size, "sha256": digest(pending_artifact),
                  "testOnly": args.test_installer,
                  "container": container, "seedMetadataSha256": hashlib.sha256(baseline_raw).hexdigest(),
                  "originalSeedMetadataUnchanged": (resources(stage, target) / "seed/runtime.json").read_bytes() == baseline_raw,
                  "runtimeArchivesIncluded": False, "bundledUpdateIncluded": False,
                  "learnerDataIncluded": False, "apiKeysIncluded": False,
                  "preflight": check, "nativeMigration": "not_run", "nativeUpdateUI": "not_run",
                  "shellSelfUpdate": "unsupported: this is a one-time shell replacement; subsequent current updater handles signed core updates"}
        pending_report = root / report_file.name
        pending_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending_artifact.rename(artifact)
        pending_report.rename(report_file)
    print(json.dumps(report, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final-installed-app-dir", required=True)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--existing-isolated-profile", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--baseline-manifest", help="Authentic signed old77 seed; defaults to baselines/runtime-<target>.json")
    parser.add_argument("--node", default=shutil.which("node"), required=not bool(shutil.which("node")))
    parser.add_argument("--makensis")
    parser.add_argument("--test-installer", action="store_true", help="Build a Windows TEST_MODE installer, not a student deliverable")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Migration packaging failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stderr[-2000:], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
