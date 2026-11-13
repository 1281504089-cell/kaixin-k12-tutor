"""Publish only the locally signed speech batch whose immutable assets match GitHub."""

import json
from pathlib import Path
import subprocess

root = Path.cwd()
batch = json.loads((root / "qa/windows-stt-20261114/signed-manifests.json").read_text())
repo = "1281504089-cell/kaixin-k12-tutor"


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


for check in batch["validation_runs"]:
    run = api(f'repos/{repo}/actions/runs/{check["id"]}')
    assert run["head_sha"] == check["head_sha"]
    assert run["status"] == "completed" and run["conclusion"] == "success"
release = api(f"repos/{repo}/releases/tags/core-updates")
assets = {item["name"]: item for item in release["assets"]}
for name, expected in batch["archives"].items():
    assert assets[name]["digest"] == "sha256:" + expected["sha256"], name
    assert assets[name]["size"] == expected["bytes"], name

subprocess.run(["python", "bootstrap_source.py", "--with-updates"], check=True)
folder = root / "stt-promotion"
folder.mkdir()
for name, manifest in batch["manifests"].items():
    assert manifest["commit"] == batch["source_commit"]
    assert manifest["corePayloadSha256"] == batch["core_sha256"]
    assert manifest["sha256"] == batch["archives"][manifest["archive"]]["sha256"]
    (folder / name).write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run(["node", "--input-type=module", "-e", """
import {readFileSync,readdirSync} from 'node:fs';
import {verifyManifest} from './student-source/apps/desktop/src/bundles.mjs';
const key=readFileSync('./student-source/apps/desktop/assets/runtime-public.pem');
for (const name of readdirSync('stt-promotion')) {
 const m=JSON.parse(readFileSync('stt-promotion/'+name));
 verifyManifest(m,key,m.arch,m.platform);
}
console.log('Verified all nine maintainer signatures');
"""], check=True)

previous = root / "stt-previous-feeds"
previous.mkdir()
for target in ("windows-x64", "macos-x64", "macos-arm64"):
    subprocess.run(["gh", "release", "download", "core-updates", "--pattern", f"runtime-{target}.json", "--dir", str(previous)], check=True)
    old = previous / f"runtime-{target}.json"
    current = json.loads(old.read_text())
    new = batch["manifests"][old.name]
    assert current["commit"] == batch["expected_previous_commit"], "Production feed changed concurrently"
    assert current["builtAt"] < new["builtAt"]
    old.rename(previous / f"before-stt-20261114-runtime-{target}.json")
subprocess.run(["gh", "release", "upload", "core-updates", *map(str, previous.iterdir())], check=True)
qualified = [p for p in folder.iterdir() if p.name not in {f"runtime-{t}.json" for t in ("windows-x64", "macos-x64", "macos-arm64")}]
subprocess.run(["gh", "release", "upload", "core-updates", *map(str, qualified), "--clobber"], check=True)
for target in ("windows-x64", "macos-x64", "macos-arm64"):
    subprocess.run(["gh", "release", "upload", "core-updates", str(folder / f"runtime-{target}.json"), "--clobber"], check=True)
print("PASS: three production feeds updated; signatures, archive digests and rollback feeds verified")
