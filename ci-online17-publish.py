"""Stage immutable signed files, then activate with complete native and COS receipts."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ci_attachment_core import REPO, digest, gh, read, write


root = Path.cwd()
batch = read(root/"online-stage.json")
tag = batch["proof"]["tag"]
source = batch["proof"]["source_commit"]
assert tag == "student-20261117-k12-17" and batch["release_id"] == 452647872
stable = "core-updates"
cos = "https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop"
work = root/"publication-work"
work.mkdir()
before = work/"previous"
before.mkdir()
next_files = work/"next"
next_files.mkdir()
targets = ("windows-x64", "macos-x64", "macos-arm64")
defaults = {f"runtime-{target}.json" for target in targets}
approval_file = root/"online-activate.json"


def api(path):
    return json.loads(gh("api", f"repos/{REPO}/{path}"))


def release(name):
    result = api("releases/tags/"+name)
    assert result["tag_name"] == name and not result["draft"]
    return result


def inventory(rel):
    return {a["name"]: a for a in rel["assets"]}


def open_url(url):
    response = urlopen(Request(url, headers={"User-Agent":"Kaixin-K12-Online-Readback","Cache-Control":"no-cache"}), timeout=80)
    parsed = urlparse(response.geturl())
    assert parsed.scheme == "https" and parsed.netloc in (
        "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", urlparse(cos).netloc)
    return response


def small(url):
    with open_url(url) as response:
        data = response.read(200_000)
    assert len(data) < 200_000
    return data


def verified(row, expected):
    assert row["digest"] == "sha256:" + expected["sha256"] and row["size"] == expected["bytes"] and row["state"] == "uploaded"


def download_verified(row, dest):
    digestor = sha256()
    total = 0
    with open_url(row["browser_download_url"]) as response, dest.open("xb") as output:
        while chunk := response.read(8 << 20):
            total += len(chunk)
            assert total <= row["size"]
            digestor.update(chunk)
            output.write(chunk)
    assert total == row["size"] and row["digest"] == "sha256:" + digestor.hexdigest()


def latest_check():
    latest = api("releases/latest")
    assert latest["id"] == 452304274 and latest["tag_name"] == "student-20261117-k12-16"


def upload(name, filenames, *, replace=False):
    if filenames:
        gh("release", "upload", name, *filenames, *(("--clobber",) if replace else ()))


def readback_stable(names, *, expected_prior=False):
    rows = inventory(release(stable))
    for name in names:
        if expected_prior:
            raw = small(rows[name]["browser_download_url"])
            assert json.loads(raw) == batch["prior"][name], "Stable feed changed outside this release"
            (before/name).write_bytes(raw)
        else:
            expected = batch["feeds"].get(name) or batch["proof"]["archives"][name]
            verified(rows[name], expected)
            if name in batch["feeds"]:
                assert small(rows[name]["browser_download_url"]) == (next_files/name).read_bytes()
    return rows


latest_check()
candidate = release(tag)
assert candidate["id"] == batch["release_id"] and candidate["prerelease"]
immutable = (set(batch["feeds"])-defaults) | set(batch["proof"]["archives"])
assert defaults == set(batch["prior"]) and len(immutable) == 65
for name, document in batch["manifests"].items():
    assert Path(name).name == name and document["commit"] == source
    path = next_files/name
    path.write_bytes((json.dumps(document, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    assert path.stat().st_size == batch["feeds"][name]["bytes"] and digest(path) == batch["feeds"][name]["sha256"]

existing = readback_stable(defaults, expected_prior=True)
candidate_assets = inventory(candidate)
archive_entries = batch["proof"]["archives"]
for name, expected in archive_entries.items():
    assert Path(name).name == name
    verified(candidate_assets[name], expected)
    if name in existing:
        verified(existing[name], expected)


def stage_archive(name):
    if name not in existing:
        path = work/name
        download_verified(candidate_assets[name], path)
        upload(stable, [path])
        path.unlink()
    return name


if not approval_file.exists():
    upload(stable, sorted(next_files/name for name in immutable if name in batch["feeds"] and name not in existing))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(stage_archive, archive_entries))
    readback_stable(immutable)
    readback_stable(defaults, expected_prior=True)
    latest_check()
    write(root/"PUBLICATION-RECEIPT.json", {"staged":True, "published":False, "tag":tag, "source_commit":source, "versioned_assets":sorted(immutable), "defaults_unchanged":True})
    raise SystemExit(0)

latest_check()
readback_stable(immutable)
approval = read(approval_file)
assert approval["source_commit"] == source and approval["core_sha256"] == archive_entries["kaixin-core-20261117-k12-17.tar.gz"]["sha256"]
assert approval["cos_archive_readback"] == archive_entries
assert set(approval["cos_feeds_sha256"]) == set(batch["feeds"])
for name, expected in batch["feeds"].items():
    assert approval["cos_feeds_sha256"][name] == expected["sha256"]
    assert small(cos+"/"+name) == (next_files/name).read_bytes()

run_id = approval["native_run_id"]
native = api("actions/runs/"+str(run_id))
assert native["head_sha"] == approval["native_commit"] and native["head_branch"] == "codex/k12-native-reverify-20261117-17-online"
assert native["status"] == "completed" and native["conclusion"] == "success"
checks = work/"native"
for target in targets:
    dest = checks/target
    gh("run","download",run_id,"--name","attachments-"+target,"--dir",dest)
    report = read(dest/"ONLINE-NATIVE-PASSED.json")
    assert report["passed"] and report["target"] == target and report["run_id"] == run_id and report["workflow_commit"] == native["head_sha"]
    assert report["source_commit"] == source and report["core_sha256"] == approval["core_sha256"] and report["delta_sha256"] == batch["proof"]["delta"]["sha256"]
    for scenario in ("launcher_migration", "matching_delta"):
        evidence = report[scenario]
        assert evidence["check_again_current"] and evidence["memory_preserved"] and evidence["backup_created"]
        assert len(evidence["checked_bank"]["questions"]) == 38

def edit_candidate(*, prerelease, body, title):
    params = {"prerelease":prerelease,"make_latest":"false","body":body,"name":title}
    write(work/"edit.json", params)
    gh("api","-X","PATCH",f"repos/{REPO}/releases/{candidate['id']}","--input",work/"edit.json")


attempted = []
made_public = False
try:
    for name in sorted(defaults):
        attempted.append(name)
        upload(stable, [next_files/name], replace=True)
        readback_stable([name])
    superseded = "kaixin-core-delta-20261117-k12-16-to-k12-17.tar.gz"
    obsolete = candidate_assets.get(superseded)
    if obsolete:
        assert obsolete["size"] == 574039 and obsolete["digest"] == "sha256:c9910cfe844bce7103d7c7c8f5e3033b488b095d09a27438fa9a7c1e1daa9720"
        gh("release", "delete-asset", tag, superseded, "--yes")
    identity = work/"online-release-identity.json"
    write(identity, {"tag":tag,"source_commit":source,"archives":archive_entries,"delta":batch["proof"]["delta"],
                     "signed_manifests":batch["feeds"],"native_run_id":run_id,
                     "first_installation_tag":"student-20261117-k12-16"})
    linked = inventory(release(tag)).get(identity.name)
    if linked:
        assert linked["digest"] == "sha256:" + digest(identity)
    else:
        upload(tag,[identity])
    notes = (root/"ONLINE-RELEASE-NOTES.md").read_text(encoding="utf-8")
    edit_candidate(prerelease=False, body=notes, title="开心动力超级学霸 · k12-17 在线更新")
    made_public = True
    assert not release(tag)["prerelease"]
    latest_check()
    readback_stable(set(batch["feeds"]) | set(archive_entries))
except BaseException:
    if made_public or not release(tag)["prerelease"]:
        edit_candidate(prerelease=True, body=candidate["body"], title=candidate["name"])
    for name in reversed(attempted):
        upload(stable, [before/name], replace=True)
        readback_stable([name], expected_prior=True)
    raise
write(root/"PUBLICATION-RECEIPT.json", {"staged":True, "published":True, "tag":tag, "source_commit":source,
      "release_id":candidate["id"], "native_run_id":run_id, "native_targets":list(targets), "first_install_release_id":452304274,
      "stable_manifests":sorted(defaults), "archives":archive_entries, "github_versioned_assets":len(immutable),
      "public_cos_signed_manifests_checked":len(batch["feeds"])})
