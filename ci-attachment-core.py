"""Build and read back the one frozen, credential-free core for all three targets."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from release_source import DOC_FIGURES, add_file, aggregate, inventory, join_source_overlay, safe_name, sha, verify_files

ROOT = Path.cwd()
CONFIG = json.loads((ROOT / "attachment-release.json").read_text())
assert CONFIG.get("prepared") is True, "Prepare a final clean owner-frozen source first"
assert CONFIG["source_scope"] == "published_export"
assert sha(ROOT / "isolation-ledger.json") == CONFIG["isolation_ledger_sha256"]
isolation = json.loads((ROOT / "isolation-ledger.json").read_text())
isolated_hashes = {row["sha256"] for row in isolation["excluded_files"]}
subprocess.run([sys.executable, "bootstrap_source.py", "--with-updates"], check=True)
SOURCE = ROOT / "student-source"
WEB = SOURCE / "web"
assert aggregate(inventory(SOURCE)) == CONFIG["source_files_sha256"], "Rebuilt source differs from owner freeze"
runtime_file = ROOT / "runtime-source-manifest.json"
assert sha(runtime_file) == CONFIG["runtime_manifest_sha256"]
runtime = json.loads(runtime_file.read_text())
assert runtime["source_commit"] == CONFIG["source_commit"]
verify_files(SOURCE, runtime["files"])
for row in runtime["files"]:
    if row["file"].startswith(("deeptutor/", "deeptutor_cli/")):
        data = (SOURCE / row["file"]).read_bytes()
        assert not any(prefix.encode() in data for prefix in DOC_FIGURES), "Required omitted documentation figure: " + row["file"]

env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1", "NEXT_PUBLIC_API_BASE": "__NEXT_PUBLIC_API_BASE_PLACEHOLDER__", "NEXT_PUBLIC_AUTH_ENABLED": "__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__"}
for command in [["npm", "ci", "--legacy-peer-deps", "--no-audit", "--no-fund"], ["npm", "run", "build"], ["npx", "vitest", "run", "--maxWorkers=1", *CONFIG["web_tests"]]]:
    subprocess.run(command, cwd=WEB, env=env, check=True)
word = SOURCE / "scripts/report-word"
subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=word, check=True)
generated_word = ROOT / "word-runtime.cjs"
subprocess.run(["node", "build.mjs", str(generated_word)], cwd=word, check=True)
assert generated_word.is_file()

payload_file = ROOT / "bank-payload-manifest.json"
assert sha(payload_file) == CONFIG["bank_payload_manifest_sha256"]
payload = json.loads(payload_file.read_text())
assert payload["archive_prefix"] == "core/deeptutor/services/student_learning/question_bank_data"
bank_archive = ROOT / "bank-payload.tar.gz"
digest = hashlib.sha256()
with bank_archive.open("xb") as output:
    for part in payload["parts"]:
        file = ROOT / safe_name(part["file"])
        assert file.stat().st_size == part["bytes"] and sha(file) == part["sha256"]
        with file.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                output.write(block)
                digest.update(block)
assert digest.hexdigest() == payload["archive_sha256"]

OUT = ROOT / "attachment-core"
OUT.mkdir()
archive = OUT / CONFIG["archive"]
files = {}


def add(out, name, data, mode=0o644):
    safe_name(name)
    assert name not in files and not name.lower().endswith((".node", ".dll", ".dylib", ".exe", ".so", ".pem")), name
    digest = hashlib.sha256(data).hexdigest()
    assert digest not in isolated_hashes, "An isolated asset was renamed into the export"
    assert name.removeprefix("core/") not in {row["file"] for row in isolation["excluded_files"]}
    files[name] = {"file": name, "bytes": len(data), "sha256": digest, "mode": mode}
    add_file(out, name, io.BytesIO(data), len(data), mode)


with archive.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz, tarfile.open(fileobj=gz, mode="w|", format=tarfile.PAX_FORMAT) as out:
    for row in runtime["files"]:
        data = (SOURCE / row["file"]).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
        add(out, "core/" + row["file"], data, row["mode"])
    add(out, "core/deeptutor/services/student_learning/word-runtime.cjs", generated_word.read_bytes())
    expected = {row["archive"]: row for row in payload["files"]}
    seen = set()
    with tarfile.open(bank_archive) as package:
        for item in package:
            name = safe_name(item.name)
            assert item.isfile() and name in expected and name not in seen
            row = expected[name]
            assert item.size == row["bytes"] and item.mode == 0o644
            data = package.extractfile(item).read()
            assert hashlib.sha256(data).hexdigest() == row["sha256"]
            add(out, name, data)
            seen.add(name)
    assert seen == set(expected), "Incomplete student-only question bank payload"
    descriptor = json.loads((ROOT / "launcher-manifest.json").read_text())
    assert descriptor["coreCommit"] == CONFIG["source_commit"], "Owner must sign the final descriptor"
    add(out, "launcher/manifest.json", (ROOT / "launcher-manifest.json").read_bytes())
    for row in descriptor["files"]:
        data = (SOURCE / "apps/desktop" / safe_name(row["file"])).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
        add(out, "launcher/" + row["file"], data)
    add(out, "BUILD_COMMIT", (CONFIG["source_commit"] + "\n").encode())
    standalone = WEB / ".next/standalone"
    assert (standalone / "server.js").is_file()
    for file in sorted(standalone.rglob("*")):
        relative = file.relative_to(standalone)
        if any(part in {"node_modules", "__pycache__", ".DS_Store"} for part in relative.parts) or file.is_dir():
            continue
        assert file.is_file() and not file.is_symlink(), str(relative)
        add(out, "web/" + relative.as_posix(), file.read_bytes(), file.stat().st_mode & 0o777)
assert archive.stat().st_size < 2_000_000_000, "Current signed core protocol archive limit"
required = {"core/deeptutor/services/student_learning/word-runtime.cjs", "core/deeptutor/services/student_learning/reference.cjs", "core/deeptutor/services/student_learning/miniapp/textbook-library.cjs", "core/deeptutor/services/student_learning/miniapp/retrieval.cjs", "core/deeptutor/services/student_learning/question_bank_data/manifest.json", "core/deeptutor/services/student_learning/question_bank_data/index.sqlite3", "web/server.js", "web/.next/BUILD_ID", "BUILD_COMMIT"}
assert required.issubset(files), required - set(files)

# Re-open the actual archive, check every member and run the existing static audit.
with tempfile.TemporaryDirectory(prefix="core-readback-", dir=OUT) as directory:
    seen = set()
    with tarfile.open(archive) as package:
        for item in package:
            assert item.isfile() and item.name in files and item.name not in seen
            row = files[item.name]
            with package.extractfile(item) as stream:
                assert item.size == row["bytes"] and hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"]
            seen.add(item.name)
        assert seen == set(files)
        package.extractall(directory, filter="data")
    result = subprocess.check_output([sys.executable, str(Path(directory) / "core/scripts/audit-student-bundle.py"), directory], text=True)
    audit = json.loads(result)
bank_archive.unlink()
file_manifest = {"source_commit": CONFIG["source_commit"], "files": sorted(files.values(), key=lambda row: row["file"])}
(OUT / "core-file-manifest.json").write_text(json.dumps(file_manifest, indent=2) + "\n")
report = {"source_commit": CONFIG["source_commit"], "backend_source_commit": CONFIG["source_commit"], "source_scope": "published_export", "source_files_sha256": CONFIG["source_files_sha256"], "isolation_ledger_sha256": CONFIG["isolation_ledger_sha256"], "isolated_assets": isolation["excluded_files"], "frontend_build": (WEB / ".next/BUILD_ID").read_text().strip(), "archive": archive.name, "sha256": sha(archive), "bytes": archive.stat().st_size, "files": len(files), "runtime_source_files": len(runtime["files"]), "generated_word_sha256": sha(generated_word), "generated_word_bytes": generated_word.stat().st_size, "generated_word_archive_readback": files["core/deeptutor/services/student_learning/word-runtime.cjs"]["sha256"] == sha(generated_word), "bank_payload_manifest_sha256": sha(payload_file), "file_manifest_sha256": sha(OUT / "core-file-manifest.json"), "archive_full_readback": True, "static_bundle_audit": audit, "real_keys_used": False, "personal_records_included": False}
(OUT / "attachment-core.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
source_manifest = json.loads((ROOT / "source-manifest.json").read_text())
overlay_descriptor = ([source_manifest["sourceOverlay"], *source_manifest.get("additionalSourceOverlays", [])])[-1]
source_asset = OUT / safe_name(overlay_descriptor["remote_archive"]["file"])
join_source_overlay(ROOT, source_asset, overlay_descriptor)
subprocess.run(["gh", "release", "upload", CONFIG["tag"], str(archive), str(source_asset), str(OUT / "attachment-core.json"), str(OUT / "core-file-manifest.json"), "--clobber"], check=True)
