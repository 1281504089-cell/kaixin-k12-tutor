"""Prepare local candidate inputs from a clean owner-frozen source; never publish/sign."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

from release_source import add_file, aggregate, inventory, runtime_rows, sha


def write(file, value):
    file.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--bank-archive-prefix", required=True)
    parser.add_argument("--isolation-ledger", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source, base = args.source.resolve(), args.baseline_source.resolve()
    ledger = json.loads(args.isolation_ledger.read_text())
    from release_source import safe_name
    excluded = {safe_name(row["file"]) for row in ledger["excluded_files"]}
    assert len(excluded) == len(ledger["excluded_files"])
    assert all(len(row["sha256"]) == 64 and row["bytes"] > 0 and row["reason"] for row in ledger["excluded_files"])
    for tree, commit in [(source, args.commit), (base, "896e79b517a008ac6d584526151862ff6191cf77")]:
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tree).decode().strip() == commit
        changes = subprocess.check_output(["git", "status", "--porcelain", "-z", "--untracked-files=no"], cwd=tree).decode().rstrip("\0")
        assert not changes or (tree == source and all(change[3:] in excluded and change[:2].strip() == "D" for change in changes.split("\0"))), "Commit the tested source; only ledger-declared physical export deletions are permitted"
    assert args.tag.startswith("student-20261116-") and args.tag != "student-20261115-preview3"
    rows, base_rows = inventory(source, excluded), inventory(base)
    previous = {row["file"]: row for row in base_rows}
    changed = [row for row in rows if row != previous.get(row["file"])]
    removed = sorted(set(previous) - {row["file"] for row in rows})
    write(root / "isolation-ledger.json", ledger)
    manifest = {"schema_version": 1, "scope": "published_export", "source_commit": args.commit, "isolation_ledger_sha256": sha(root / "isolation-ledger.json"), "excluded_files": sorted(excluded), "baseline_source_commit": "896e79b517a008ac6d584526151862ff6191cf77", "baseline_source_files_sha256": aggregate(base_rows), "files": rows, "changed": changed, "removed": removed}
    archive = root / "source-overlay.tar.gz"
    assert not archive.exists() and not list(root.glob("source-overlay.0*")), "Preserve previous prepared inputs; use a fresh recipe clone"
    with archive.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as package:
        for row in changed:
            with (source / row["file"]).open("rb") as stream:
                add_file(package, row["file"], stream, row["bytes"], row["mode"])
    parts = []
    with archive.open("rb") as stream:
        while block := stream.read(2 * 1024 * 1024):
            file = root / f"source-overlay.{len(parts) + 1:03d}"
            file.write_bytes(block)
            parts.append({"file": file.name, "bytes": len(block), "sha256": sha(file)})
    source_hash = aggregate(rows)
    write(root / "source-inventory-20261116.json", manifest)
    chain = json.loads((root / "source-manifest.json").read_text())
    chain["sourceOverlay"] = {"manifest": "source-inventory-20261116.json", "manifest_sha256": sha(root / "source-inventory-20261116.json"), "source_commit": args.commit, "source_files_sha256": source_hash, "archive_sha256": sha(archive), "parts": parts}
    write(root / "source-manifest.json", chain)
    archive.unlink()
    runtime = {"schema_version": 1, "scope": "published_export", "source_commit": args.commit, "published_export_sha256": source_hash, "isolation_ledger_sha256": sha(root / "isolation-ledger.json"), "files": runtime_rows(rows)}
    write(root / "runtime-source-manifest.json", runtime)
    bank = args.bank.resolve()
    assert (bank / "manifest.json").is_file() and (bank / "index.sqlite3").is_file(), "Only the final student-only pack may be attached"
    # This payload is external to the source tree and remains read-only support data.
    payload = []
    prefix = args.bank_archive_prefix.rstrip("/")
    safe_name(prefix)
    assert prefix == "core/deeptutor/services/student_learning/question_bank_data", "Owner-confirmed read-only runtime resource path"
    for file in sorted(bank.rglob("*")):
        if file.is_dir():
            continue
        assert file.is_file() and not file.is_symlink()
        relative = file.relative_to(bank).as_posix()
        assert relative in {"manifest.json", "index.sqlite3"} or relative.startswith("student-assets/"), "Unexpected bank member"
        payload.append({"file": relative, "archive": prefix + "/" + relative, "bytes": file.stat().st_size, "sha256": sha(file)})
    bank_archive = root / "bank-payload.tar.gz"
    with bank_archive.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as package:
        for row in payload:
            with (bank / row["file"]).open("rb") as stream:
                add_file(package, row["archive"], stream, row["bytes"])
    bank_parts = []
    with bank_archive.open("rb") as stream:
        while block := stream.read(2 * 1024 * 1024):
            file = root / f"bank-payload.{len(bank_parts) + 1:03d}"
            file.write_bytes(block)
            bank_parts.append({"file": file.name, "bytes": len(block), "sha256": sha(file)})
    write(root / "bank-payload-manifest.json", {"schema_version": 1, "archive_prefix": prefix, "bank_revision": json.loads((bank / "manifest.json").read_text()), "files": payload, "parts": bank_parts, "archive_sha256": sha(bank_archive)})
    bank_archive.unlink()
    config = json.loads((root / "attachment-release.json").read_text())
    config.update(tag=args.tag, source_commit=args.commit, baseline_source_commit="896e79b517a008ac6d584526151862ff6191cf77", archive="kaixin-core-" + args.tag.removeprefix("student-") + ".tar.gz", source_files_sha256=source_hash, source_scope="published_export", isolation_ledger_sha256=sha(root / "isolation-ledger.json"), runtime_manifest_sha256=sha(root / "runtime-source-manifest.json"), bank_payload_manifest_sha256=sha(root / "bank-payload-manifest.json"), prepared=True)
    config.pop("pending_reason", None)
    config.pop("new_backend_files", None)
    config.pop("patch_sha256", None)
    write(root / "attachment-release.json", config)
    write(root / "PREPARED-INPUTS.json", {"status": "inputs_prepared_unsigned_not_built_not_published", "source_commit": args.commit, "tag": args.tag, "source_files_sha256": source_hash, "source_overlay_parts": parts, "runtime_files": len(runtime["files"]), "bank_bytes": sum(row["bytes"] for row in payload), "bank_parts": bank_parts, "bank_source": str(bank), "required_next": ["owner sign launcher descriptor with final source identity", "push candidate core branch", "read back core", "owner sign native batch", "all three native install/update jobs", "owner-only promotion"]})
    print(json.dumps({"prepared": True, "source_commit": args.commit, "overlay_parts": len(parts), "runtime_files": len(runtime["files"]), "bank_bytes": sum(row["bytes"] for row in payload)}))


if __name__ == "__main__":
    main()
