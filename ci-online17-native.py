"""Drive the frozen v6 and v7 production update modules in native Electron."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

from ci_attachment_core import REPO, digest, download, read, write

parser = argparse.ArgumentParser()
parser.add_argument("--target", required=True)
target = parser.parse_args().target
expected_machine = {"macos-arm64": "arm64", "macos-x64": "x86_64", "windows-x64": "AMD64"}
assert platform.machine() == expected_machine[target]
is_mac = target.startswith("macos")
root = Path.cwd()
stage = read(root / "online-stage.json")
lock = read(root / "online-update-lock.json")
assert stage["proof"]["source_commit"] == lock["source_commit"]
evidence = root/"fresh-evidence"/target
evidence.mkdir(parents=True)
write(evidence/"qa-inputs.json", {"target": target, "source_commit": lock["source_commit"], "launcher_build": stage["proof"]["launcher_build"]})
work = root/"online-native"
work.mkdir()
candidate = json.loads(subprocess.check_output(["gh", "api", f"repos/{REPO}/releases/tags/{lock['tag']}"]))
assert candidate["id"] == stage["release_id"] and candidate["prerelease"]
remote = {row["name"]: row for row in candidate["assets"]}
signed = work/"feeds"
signed.mkdir()
files = []
for name, document in stage["manifests"].items():
    if name != f"runtime-{target}.json" and not name.startswith(f"runtime-{target}-"):
        continue
    path = signed/name
    path.write_bytes((json.dumps(document, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    proof = stage["feeds"][name]
    assert path.stat().st_size == proof["bytes"] and digest(path) == proof["sha256"]
    if name in remote:
        assert remote[name]["digest"] == "sha256:" + proof["sha256"]
    else:
        files.append(path)
if files:
    subprocess.run(["gh", "release", "upload", lock["tag"], *map(str,files)], check=True, timeout=180)
prior = root/"online17-prior-launcher"
descriptor = read(prior/"manifest.json")
assert descriptor["buildId"] == "20261119-updater-6" and descriptor["coreCommit"] == lock["old_source_commit"]
for row in descriptor["files"]:
    file = prior/row["file"]
    assert file.stat().st_size == row["bytes"] and digest(file) == row["sha256"]
version = read(prior/"package.json")["devDependencies"]["electron"]
assert version == "45.1.0"
electron = work/"electron"
electron.mkdir()
archive_name = "electron-v"+version+"-"+("darwin" if is_mac else "win32")+"-"+target.split("-")[-1]+".zip"
official = "https://github.com/electron/electron/releases/download/v"+version+"/"
checksums = subprocess.check_output(["curl", "-fLsS", "--retry", "2", official+"SHASUMS256.txt"], text=True)
pinned = {line.split()[1].lstrip("*"): line.split()[0] for line in checksums.splitlines() if line.strip()}
electron_archive = work/archive_name
subprocess.run(["curl", "-fLsS", "--retry", "2", official+archive_name, "-o", str(electron_archive)], check=True, timeout=240)
assert digest(electron_archive) == pinned[archive_name]
if is_mac:
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(electron_archive), str(electron)], check=True, timeout=120)
else:
    subprocess.run([str(Path(os.environ["SystemRoot"])/"System32/tar.exe"), "-xf", str(electron_archive), "-C", str(electron)], check=True, timeout=120)
electron_archive.unlink()
app = electron/"Electron.app" if is_mac else electron
resources = app/("Contents/Resources" if is_mac else "resources")
executable = app/("Contents/MacOS/Electron" if is_mac else "electron.exe")
assert executable.is_file() and resources.is_dir(), f"Missing vendor Electron binary at {executable}"
(resources/"default_app.asar").unlink(missing_ok=True)
shutil.copytree(prior, resources/"app")
qa = resources/"app/qa"
qa.mkdir()
for name, dest in [("ci-online17-update-flow.cjs","update-flow.cjs"),
                   ("verify-online17-bank.cjs","verify-online17-bank.cjs"),
                   ("online-bank-expectations.json","online-bank-expectations.json")]:
    shutil.copyfile(root/name, qa/dest)
seed = resources/"seed"
seed.mkdir()
manifest = stage["prior"]["runtime-"+target+".json"]
row = lock["old_bridges"][target]
assert manifest["sha256"] == row["sha256"] and manifest["archive"] == row["name"]
assert not manifest.get("baseRuntimeId")
write(seed/"runtime.json", manifest)
archive = download(row, seed)
profile = work/"disposable-profile"
profile.mkdir()
code = """
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';
const [app, seed, profile] = process.argv.slice(1);
const { canonicalManifest, installBundle } = await import(pathToFileURL(app + '/src/bundles.mjs'));
const { verify } = await import('node:crypto');
const key = await readFile(app + '/assets/runtime-public.pem');
const descriptor = JSON.parse(await readFile(app + '/manifest.json'));
assert(verify(null, Buffer.from(canonicalManifest(descriptor)), key, Buffer.from(descriptor.signature, 'base64')));
const result = await installBundle(seed, profile, key);
await writeFile(profile + '/active.json', JSON.stringify(result.manifest));
"""
subprocess.run(["node", "--input-type=module", "-e", code, str(resources/"app"), str(seed/"runtime.json"), str(profile)],
               check=True, timeout=600)
archive.unlink()
if is_mac:
    subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, timeout=120)
prior_core = profile/"runtimes"/manifest["runtimeId"]
native_python = prior_core/("python/bin/python3" if is_mac else "python/python.exe")
old_active = (profile/"active.json").read_bytes()
memory = profile/"workspace/data/user/memory/L3/profile.md"
memory.parent.mkdir(parents=True)
memory.write_text("k12-17 synthetic learning memory", encoding="utf-8")
core = "kaixin-core-20261117-k12-17.tar.gz"
delta = stage["proof"]["delta"]["archive"]

for scene, expected, forbidden, restart in [("launcher-migration", core, delta, True), ("matching-delta", delta, core, False)]:
    output = evidence/(scene+".json")
    env = dict(os.environ, OPEN_DEEPTUTOR_TEST_HOME=str(profile), KX_UPDATE_FLOW_RESULT=str(output),
               KX_CANDIDATE_TAG=lock["tag"], KX_ONLINE_SOURCE=lock["source_commit"], KX_ONLINE_EXPECT_ARCHIVE=expected,
               KX_ONLINE_FORBID_ARCHIVE=forbidden, KX_EXPECT_SHELL_RESTART="1" if restart else "0",
               KX_START_LAUNCHER_BUILD=descriptor["buildId"] if restart else stage["proof"]["launcher_build"])
    with (evidence/(scene+".log")).open("wb") as log:
        subprocess.run([str(executable)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1400)
    deadline = time.monotonic() + 180
    while not output.is_file():
        error = output.with_suffix(".json.error.json")
        assert not error.exists(), error.read_text(encoding="utf-8") if error.exists() else ""
        assert time.monotonic() < deadline, "Signed desktop restart did not produce its receipt"
        time.sleep(1)
    receipt = read(output)
    active = read(profile/"active.json")
    assert receipt["check_again_current"] and receipt["memory_preserved"] and receipt["backup_created"]
    assert receipt["from_runtime"] == manifest["runtimeId"] and receipt["to_launcher"] == stage["proof"]["launcher_build"]
    assert receipt["signed_launcher_restarted"] is restart and receipt["requested_archives"] == [expected]
    assert active["commit"] == lock["source_commit"] and active["baseRuntimeId"] == manifest["runtimeId"]
    assert receipt["checked_bank"]["revision"] == lock["bank_revision"] and len(receipt["checked_bank"]["questions"]) == 38
    subprocess.run([str(native_python), "-c",
                    "import psutil,sys; p=int(sys.argv[1]); psutil.Process(p).wait(timeout=60) if psutil.pid_exists(p) else None",
                    str(receipt["restarted_pid"])], check=True, timeout=70)
    if restart:
        # Exercise the same verified prior core again, with the new launcher installed.
        assert active["runtimeId"] != manifest["runtimeId"]
        shutil.rmtree(profile/"runtimes"/active["runtimeId"])
        (profile/"active.json").write_bytes(old_active)
        (profile/"upgrade.json").unlink()

write(evidence/"ONLINE-NATIVE-PASSED.json", {"passed": True, "target": target, "source_commit": lock["source_commit"],
      "run_id": int(os.environ["GITHUB_RUN_ID"]), "workflow_commit": os.environ["GITHUB_SHA"],
      "prior_core_sha256": lock["old_core"]["sha256"], "prior_bridge_sha256": row["sha256"], "electron": version,
      "core_sha256": stage["proof"]["archives"][core]["sha256"], "delta_sha256": stage["proof"]["delta"]["sha256"],
      "launcher_migration": read(evidence/"launcher-migration.json"), "matching_delta": read(evidence/"matching-delta.json")})
