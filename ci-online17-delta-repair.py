"""Recreate only the delta using separately named old and new inventories."""
import json
import os
from pathlib import Path
import subprocess
import tarfile

import ci_attachment_core as build

root = Path.cwd()
stage = build.read(root/"online-stage.json")
lock = build.read(root/"online-update-lock.json")
tag = lock["tag"]
assert tag == stage["proof"]["tag"] == "student-20261117-k12-17"
work = root/"fresh-evidence/macos-x64"
work.mkdir(parents=True)
before = work/"previous"
before.mkdir()
baseline = build.download(lock["old_file_manifest"], before)
assert build.read(baseline)["source_commit"] == lock["old_source_commit"]
build.PREVIOUS = tag
rel = json.loads(build.gh("api",f"repos/{build.REPO}/releases/tags/{tag}"))
assert rel["id"] == stage["release_id"] and rel["prerelease"]
remote = {r["name"]: r for r in rel["assets"]}
core_name = "kaixin-core-20261117-k12-17.tar.gz"
def asset(name):
    row = remote[name]
    assert row["digest"].startswith("sha256:")
    return build.download({"name": name, "sha256":row["digest"][7:], "bytes":row["size"], "id":row["id"]}, work)
core = asset(core_name)
next_index = asset("core-file-manifest.json")
assert baseline != next_index
assert build.digest(core) == stage["proof"]["archives"][core_name]["sha256"]
assert build.read(next_index)["source_commit"] == lock["source_commit"]
name = "kaixin-core-delta-20261117-k12-16-to-k12-17-r2.tar.gz"
out = work/name
descriptor = json.loads(subprocess.check_output(["python",str(root/"build-online-core-delta.py"),
    str(baseline),str(next_index),lock["old_core"]["sha256"],str(core),str(out)]))
assert descriptor["archive"] == name and descriptor["toCoreSha256"] == build.digest(core)
assert descriptor["fromCoreSha256"] == lock["old_core"]["sha256"] and descriptor["sha256"] == build.digest(out)
expected = set(stage["proof"]["runtime_file_changes"])
assert "core/deeptutor/services/student_learning/question_bank_data/index.sqlite3" in expected
with tarfile.open(out,mode="r:gz") as delta:
    assert len(expected) > 50 and set(delta.getnames()) == expected | {"delta-inventory.json"}
receipt = work/"delta-receipt-r2.json"
build.write(receipt,{"passed":True,"run_id":int(os.environ["GITHUB_RUN_ID"]),"workflow_commit":os.environ["GITHUB_SHA"],
      "source_commit":lock["source_commit"],"changed_files":sorted(expected),"delta":descriptor})
build.gh("release","upload",tag,out,receipt)
core.unlink()
print(json.dumps(descriptor),flush=True)
