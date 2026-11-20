"""Drive the frozen v7 and v8 production update modules in native Electron."""
import argparse
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import time

import ci_attachment_core as runner
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
        if remote[name]["digest"] == "sha256:" + proof["sha256"]:
            continue
        prior = stage['superseded_native_defaults'].get(name)
        assert prior and name == f'runtime-{target}.json' and remote[name]['digest'] == 'sha256:' + prior['sha256'] and remote[name]['size'] == prior['bytes']
        subprocess.run(['gh','release','upload',lock['tag'],str(path),'--clobber'], check=True, timeout=90)
    else:
        files.append(path)
if files:
    subprocess.run(["gh", "release", "upload", lock["tag"], *map(str,files)], check=True, timeout=180)
prior = root/"online17-prior-launcher"
descriptor = read(prior/"manifest.json")
assert descriptor["buildId"] == "20261120-updater-7" and descriptor["coreCommit"] == lock["old_source_commit"]
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
vendor_bin = app/("Contents/MacOS/Electron" if is_mac else "electron.exe")
assert vendor_bin.is_file() and resources.is_dir(), f"Missing vendor Electron binary at {vendor_bin}"
executable = vendor_bin.with_name("开心动力超级学霸" + ("" if is_mac else ".exe"))
vendor_bin.rename(executable)
if is_mac:
    plist = app/"Contents/Info.plist"
    metadata = plistlib.loads(plist.read_bytes())
    metadata.update(CFBundleExecutable=executable.name, CFBundleIdentifier="org.kaixindongli.super-scholar",
                    CFBundleName="开心动力超级学霸", CFBundleDisplayName="开心动力超级学霸")
    plist.write_bytes(plistlib.dumps(metadata,sort_keys=False))
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
old_state = read(root/'tested-native-bases.json')
native = old_state['native'][target]
manifest, row, old_overlay = native['manifest'], native['asset'], native['overlay']
assert manifest['sha256'] == row['sha256'] and manifest['archive'] == row['name'] and not manifest.get('baseRuntimeId')
assert old_overlay['baseRuntimeId'] == manifest['runtimeId'] and old_overlay['sha256'] == lock['old_core']['sha256']
write(seed/'runtime.json', manifest)
runner.PREVIOUS = old_state['native_tag']
archive = download(row, seed)
profile = work/'disposable-profile'
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
def install(manifest_file, home):
    subprocess.run(["node", "--input-type=module", "-e", code, str(resources/"app"), str(manifest_file), str(home)],
                   check=True, timeout=600)

install(seed/'runtime.json', profile)
archive.unlink()
if is_mac:
    subprocess.run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, timeout=120)
prior_core = profile/"runtimes"/manifest["runtimeId"]
native_python = prior_core/("python/bin/python3" if is_mac else "python/python.exe")
memory = profile/"workspace/data/user/memory/L3/profile.md"
memory.parent.mkdir(parents=True)
memory.write_text("k12-18 synthetic learning memory", encoding="utf-8")
core = "kaixin-core-20261117-k12-18.tar.gz"
delta = stage["proof"]["delta"]["archive"]

for scene, expected, forbidden, restart in [("launcher-migration", core, delta, True), ("matching-delta", delta, core, False)]:
    output = evidence/(scene+".json")
    before = read(profile/"active.json")
    env = dict(os.environ, OPEN_DEEPTUTOR_TEST_HOME=str(profile), KX_UPDATE_FLOW_RESULT=str(output),
               KX_CANDIDATE_TAG=lock["tag"], KX_ONLINE_SOURCE=lock["source_commit"], KX_ONLINE_EXPECT_ARCHIVE=expected,
               KX_ONLINE_FORBID_ARCHIVE=forbidden, KX_EXPECT_SHELL_RESTART="1" if restart else "0",
               KX_START_LAUNCHER_BUILD=descriptor["buildId"] if restart else stage["proof"]["launcher_build"])
    with (evidence/(scene+".log")).open("wb") as log:
        result = subprocess.run([str(executable)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1400)
    if result.returncode and (profile/'logs/runtime.log').is_file():
        shutil.copyfile(profile/'logs/runtime.log', evidence/(scene+'-runtime.log'))
    result.check_returncode()
    deadline = time.monotonic() + 180
    while not output.is_file():
        error = output.with_suffix(".json.error.json")
        assert not error.exists(), error.read_text(encoding="utf-8") if error.exists() else ""
        assert time.monotonic() < deadline, "Signed desktop restart did not produce its receipt"
        time.sleep(1)
    receipt = read(output)
    active = read(profile/"active.json")
    assert receipt["check_again_current"] and receipt["memory_preserved"] and receipt["backup_created"]
    assert receipt["from_runtime"] == before["runtimeId"] and receipt["to_launcher"] == stage["proof"]["launcher_build"]
    assert receipt["signed_launcher_restarted"] is restart and receipt["requested_archives"] == [expected]
    assert active["commit"] == lock["source_commit"] and active["baseRuntimeId"] == manifest["runtimeId"]
    assert receipt["checked_bank"]["revision"] == read(root/"online-bank-expectations.json")["revision"] and len(receipt["checked_bank"]["questions"]) == 38
    subprocess.run([str(native_python), "-c",
                    "import psutil,sys; p=int(sys.argv[1]); psutil.Process(p).wait(timeout=60) if psutil.pid_exists(p) else None",
                    str(receipt["restarted_pid"])], check=True, timeout=70)
    if restart:
        # Retain the validated native base and load the signed k12-17 compatibility overlay.
        assert active['runtimeId'] != manifest['runtimeId']
        shutil.rmtree(profile/'runtimes'/active['runtimeId'])
        (profile/'upgrade.json').unlink()
        overlay = work/'prior-compatible-core'
        overlay.mkdir()
        write(overlay/'runtime.json', old_overlay)
        runner.PREVIOUS = old_state['overlay_tag']
        old_asset = download(old_state['overlay_assets'], overlay)
        install(overlay/'runtime.json', profile)
        old_asset.unlink()
        assert read(profile/'active.json')['runtimeId'] == old_overlay['runtimeId']

# The no-compatible-base path must actually boot using all its own native dependencies.
shutil.rmtree(profile/'runtimes')
bridge = stage['manifests'][f'runtime-{target}.json']
bridge_assets = work/'standalone-bridge'
bridge_assets.mkdir()
write(bridge_assets/'runtime.json', bridge)
assert bridge['archive'].endswith(f'-r2-{target}.tar.gz')
bridge_asset = remote[bridge['archive']]
assert bridge_asset['digest'] == 'sha256:' + bridge['sha256']
runner.PREVIOUS = lock['tag']
archive = download(dict(name=bridge_asset['name'],bytes=bridge_asset['size'],sha256=bridge['sha256'],id=bridge_asset['id']), bridge_assets)
install(bridge_assets/'runtime.json', profile)
archive.unlink()
output = evidence/'standalone-bridge.json'
with (evidence/'standalone-bridge.log').open('wb') as log:
    result = subprocess.run([str(executable)], stdout=log, stderr=subprocess.STDOUT, timeout=400,
                            env=dict(os.environ, OPEN_DEEPTUTOR_TEST_HOME=str(profile), KX_UPDATE_FLOW_RESULT=str(output), KX_BRIDGE_BOOT='1'))
if result.returncode and (profile/'logs/runtime.log').is_file():
    shutil.copyfile(profile/'logs/runtime.log', evidence/'standalone-bridge-runtime.log')
result.check_returncode()
bridge_receipt = read(output)
assert bridge_receipt['booted'] and bridge_receipt['runtime_id'] == bridge['runtimeId'] and bridge_receipt['commit'] == lock['source_commit']

write(evidence/"ONLINE-NATIVE-PASSED.json", {"passed": True, "target": target, "source_commit": lock["source_commit"],
      "run_id": int(os.environ["GITHUB_RUN_ID"]), "workflow_commit": os.environ["GITHUB_SHA"],
      "prior_core_sha256": lock["old_core"]["sha256"], "prior_bridge_sha256": row["sha256"], "electron": version,
      "core_sha256": stage["proof"]["archives"][core]["sha256"], "delta_sha256": stage["proof"]["delta"]["sha256"],
      "launcher_migration": read(evidence/"launcher-migration.json"), "matching_delta": read(evidence/"matching-delta.json"), "standalone_bridge": bridge_receipt})
