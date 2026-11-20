"""Build a signed-launcher core update over the verified public k12-16 bytes."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

REPO = "1281504089-cell/kaixin-k12-tutor"
ROOT = Path.cwd()
PREVIOUS = "student-20261117-k12-16"


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def gh(*args):
    return subprocess.check_output(["gh", *map(str, args)])


def download(row, directory):
    path = directory / row["name"]
    assert path.name == row["name"] and Path(row["name"]).name == row["name"]
    partial = path.with_suffix(path.suffix + ".partial")
    urls = [f"https://github.com/{REPO}/releases/download/{PREVIOUS}/{path.name}"]
    if row.get("id"):
        urls.append(f"https://api.github.com/repos/{REPO}/releases/assets/{row['id']}")
    for url in urls:
        try:
            with urlopen(Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "Kaixin-Release-Readback"}),
                         timeout=90) as response, partial.open("xb") as output:
                final = urlparse(response.geturl())
                assert final.scheme == "https" and final.hostname in {
                    "github.com", "api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
                state = sha256()
                total = 0
                while chunk := response.read(8 << 20):
                    total += len(chunk)
                    assert total <= row["bytes"]
                    state.update(chunk)
                    output.write(chunk)
            assert total == row["bytes"] and state.hexdigest() == row["sha256"], path.name
            partial.rename(path)
            return path
        except (OSError, AssertionError) as error:
            partial.unlink(missing_ok=True)
            failure = error
    raise failure


def archive_files(root):
    rows = []
    for path in sorted(root.rglob("*")):
        assert not path.is_symlink(), path
        if path.is_file():
            rows.append({"file": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                         "sha256": digest(path), "mode": path.stat().st_mode & 0o777})
    return sorted(rows, key=lambda row: row["file"])


def emit_tar(destination, populate):
    with destination.open("xb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=6) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as out:
            populate(out)


def main():
    lock = read(ROOT / "online-update-lock.json")
    config = read(ROOT / "attachment-release.json")
    assert lock["tag"] == config["tag"] == "student-20261117-k12-17" and config["prepared"]
    assert config["source_commit"] == lock["source_commit"] and config["launcher_build"] == "20261120-updater-7"
    before = json.loads(gh("api", f"repos/{REPO}/releases/tags/{PREVIOUS}"))
    assert before["id"] == 452304274 and not before["prerelease"]
    assets = {row["name"]: row for row in before["assets"]}
    for row in [lock["old_core"], lock["old_file_manifest"], *lock["old_bridges"].values()]:
        remote = assets[row["name"]]
        assert (remote["size"], remote["digest"], remote["id"]) == (row["bytes"], "sha256:" + row["sha256"], row["id"])
    work = ROOT / "attachment-core"
    work.mkdir()
    old_index_path = download(lock["old_file_manifest"], work)
    old_index = read(old_index_path)
    assert old_index["source_commit"] == lock["old_source_commit"]
    previous = download(lock["old_core"], work)
    core = work / "runtime"
    core.mkdir()
    with tarfile.open(previous, "r:gz") as archive:
        archive.extractall(core, filter="data")
    assert archive_files(core) == old_index["files"], "The baseline core differs from its public file inventory"
    previous.unlink()
    payload = work / "online-supplement.tar.gz"
    with payload.open("xb") as stream:
        for part in lock["input_parts"]:
            name = Path(part["name"])
            assert name.name == str(name) and name.name.startswith("online-supplement.")
            data = (ROOT / name).read_bytes()
            assert len(data) == part["bytes"] and sha256(data).hexdigest() == part["sha256"]
            stream.write(data)
    assert digest(payload) == lock["supplement_sha256"]
    inputs = work / "inputs"
    with tarfile.open(payload, "r:gz") as archive:
        archive.extractall(inputs, filter="data")
    expected = {r["file"]: r for r in lock["source_files"]}
    assert archive_files(inputs / "source") == list(expected.values())
    changed_runtime = set()
    for name, row in expected.items():
        if name.startswith(("deeptutor/", "scripts/")):
            target = core / "core" / name
        elif name.startswith("apps/desktop/src/"):
            target = core / "launcher/src" / Path(name).name
        else:
            assert name.startswith(("tests/", "apps/desktop/scripts/", "apps/desktop/test/")), name
            continue
        assert target.parent.is_dir() and not target.is_symlink()
        shutil.copyfile(inputs / "source" / name, target)
        target.chmod(row["mode"])
        changed_runtime.add(target.relative_to(core).as_posix())
    descriptor = ROOT / "launcher-manifest.json"
    signed_launcher = read(descriptor)
    assert signed_launcher["coreCommit"] == lock["source_commit"] and signed_launcher["buildId"] == config["launcher_build"]
    for row in signed_launcher["files"]:
        path = core / "launcher" / row["file"]
        assert path.stat().st_size == row["bytes"] and digest(path) == row["sha256"]
    shutil.copyfile(descriptor, core / "launcher/manifest.json")
    (core / "BUILD_COMMIT").write_text(lock["source_commit"] + "\n")
    bank = core / "core/deeptutor/services/student_learning"
    repacked = subprocess.check_output(["python", str(inputs/"source/scripts/merge_question_supplements.py"),
        "--bank", str(bank/"question_bank_data"), "--pack", str(inputs/"packs/recovered"),
        "--pack", str(inputs/"packs/instruments")])
    bank_proof = json.loads(repacked)
    assert bank_proof["bank_revision"] == lock["bank_revision"] and bank_proof["question_count"] == 20864
    assert len(bank_proof["recovered"]) == 36 and len(bank_proof["added"]) == 2 and bank_proof["previous_revision_retained"]
    current_index = {"source_commit": lock["source_commit"], "files": archive_files(core)}
    new_index = work / "core-file-manifest.json"
    write(new_index, current_index)
    old_rows = {row["file"]: row for row in old_index["files"]}
    new_rows = {row["file"]: row for row in current_index["files"]}
    assert set(old_rows) <= set(new_rows)
    assert {name: row for name, row in old_rows.items() if name.startswith("web/")} == {
        name: row for name, row in new_rows.items() if name.startswith("web/")}
    actual_changes = {name for name, row in new_rows.items() if old_rows.get(name) != row}
    assert changed_runtime <= actual_changes
    assert all(name in changed_runtime or name in {"BUILD_COMMIT", "launcher/manifest.json"}
               or name.startswith("core/deeptutor/services/student_learning/question_") for name in actual_changes)
    clean_core = work / config["archive"]

    def append_core(out):
        for row in current_index["files"]:
            name = row["file"]
            info = tarfile.TarInfo(name)
            info.size = row["bytes"]
            info.mode = row["mode"]
            with (core / name).open("rb") as source:
                out.addfile(info, source)

    emit_tar(clean_core, append_core)
    delta = work / "kaixin-core-delta-20261117-k12-16-to-k12-17.tar.gz"
    with (work / "delta-descriptor.json").open("wb") as f:
        subprocess.run(["python", str(inputs/"source/apps/desktop/scripts/build-core-delta.py"),
            str(old_index_path), str(new_index), lock["old_core"]["sha256"], str(clean_core), str(delta)], stdout=f, check=True)
    delta_proof = read(work/"delta-descriptor.json")
    assert delta.stat().st_size < clean_core.stat().st_size and digest(delta) == delta_proof["sha256"]

    def bridge(entry):
        target, row = entry
        previous_bridge = download(row, work)
        destination = work / f"kaixin-bridge-20261117-k12-17-{target}.tar.gz"
        preserved = 0

        def populate(out):
            nonlocal preserved
            with tarfile.open(previous_bridge, mode="r|gz") as previous:
                for member in previous:
                    name = member.name
                    if name == "BUILD_COMMIT" or name.split("/", 1)[0] in {"core", "web", "launcher"}:
                        continue
                    assert not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
                    out.addfile(member, previous.extractfile(member) if member.isfile() else None)
                    preserved += 1
            append_core(out)

        emit_tar(destination, populate)
        previous_bridge.unlink()
        assert preserved > 0 and destination.stat().st_size < 2 * 1024**3
        return target, (destination, preserved)

    with ThreadPoolExecutor(max_workers=2) as pool:
        bridges = dict(pool.map(bridge, sorted(lock["old_bridges"].items())))
    archives = [clean_core, delta, *(path for path, _ in bridges.values())]
    proof = {"passed": True, "tag": lock["tag"], "source_commit": lock["source_commit"],
             "source_tree": lock["source_tree"], "launcher_build": config["launcher_build"], "bank": bank_proof,
             "run_id": int(os.environ["GITHUB_RUN_ID"]), "workflow_commit": os.environ["GITHUB_SHA"],
             "archives": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in archives},
             "delta": delta_proof, "web_file_count_reused": sum(n.startswith("web/") for n in old_rows),
             "bridge_native_members_reused": {target: item[1] for target, item in bridges.items()},
             "runtime_file_changes": sorted(actual_changes)}
    receipt = work / "attachment-core.json"
    write(receipt, proof)
    source_archive = work / "source-overlay-20261117-k12-17.tar.gz"
    payload.rename(source_archive)
    gh("release", "upload", config["tag"], *archives, receipt, new_index, source_archive, work/"delta-descriptor.json")
    print(json.dumps({"built": True, "tag": lock["tag"], "archives": proof["archives"]}), flush=True)


if __name__ == "__main__":
    main()
