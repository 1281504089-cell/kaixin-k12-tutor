"""One deterministic student-only payload used before and after source freeze."""
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import time

from release_source import add_file, safe_name, sha

PREFIX = "core/deeptutor/services/student_learning/question_bank_data"
PART_BYTES = 512 * 1024


def prepare_bank_payload(bank, expected_manifest_sha, root):
    bank, root = Path(bank).resolve(), Path(root).resolve()
    assert sha(bank / "manifest.json") == expected_manifest_sha, "Wrong bank freeze"
    identity = json.loads((bank / "manifest.json").read_text())
    assert identity["teacher_evidence_included"] is False and identity["raw_snapshots_included"] is False
    assert (bank / "index.sqlite3").stat().st_size == identity["index_bytes"] and sha(bank / "index.sqlite3") == identity["index_sha256"]
    manifest_file = root / "bank-payload-manifest.json"
    state_file = root / "BANK-PAYLOAD-STATE.json"
    if manifest_file.exists() or state_file.exists():
        assert manifest_file.is_file() and state_file.is_file(), "Incomplete bank preparation; preserve this attempt"
        state = json.loads(state_file.read_text())
        assert state["bank_manifest_sha256"] == expected_manifest_sha and sha(manifest_file) == state["payload_manifest_sha256"]
        payload = json.loads(manifest_file.read_text())
        assert payload["bank_manifest"] == identity and payload["archive_prefix"] == PREFIX
        for row in payload["parts"]:
            file = root / safe_name(row["file"])
            assert file.stat().st_size == row["bytes"] and sha(file) == row["sha256"]
        return payload  # Reuse the same already-uploaded bytes; never regenerate them.
    assert not list(root.glob("bank-payload.0*")) and not (root / "bank-payload.tar.gz").exists(), "Preserve partial inputs"
    rows = []
    for file in sorted(bank.rglob("*")):
        if file.is_dir():
            assert not file.is_symlink()
            continue
        relative = file.relative_to(bank).as_posix()
        if relative == "isolation-report.json":
            continue  # Never read/copy isolated IDs or teacher evidence.
        assert file.is_file() and not file.is_symlink()
        assert relative in {"manifest.json", "index.sqlite3"} or relative.startswith("student-assets/")
        rows.append({"file": relative, "archive": PREFIX + "/" + relative, "bytes": file.stat().st_size, "sha256": sha(file)})
    assets = [row for row in rows if row["file"].startswith("student-assets/")]
    assert len(assets) == identity["asset_count"] and sum(row["bytes"] for row in assets) == identity["asset_bytes"]
    started = time.monotonic()
    archive = root / "bank-payload.tar.gz"
    with archive.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as package:
        for row in rows:
            with (bank / row["file"]).open("rb") as stream:
                add_file(package, row["archive"], stream, row["bytes"])
    parts = []
    with archive.open("rb") as stream:
        while block := stream.read(PART_BYTES):
            file = root / f"bank-payload.{len(parts) + 1:03d}"
            file.write_bytes(block)
            parts.append({"file": file.name, "bytes": len(block), "sha256": hashlib.sha256(block).hexdigest(), "git_blob_sha": hashlib.sha1(("blob " + str(len(block)) + "\0").encode() + block).hexdigest()})
    payload = {"schema_version": 1, "archive_prefix": PREFIX, "bank_manifest": identity, "private_isolation_receipt_sha256": identity["isolation_report_sha256"], "files": rows, "parts": parts, "archive_sha256": sha(archive)}
    manifest_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {"status": "bank-only-frozen", "source_pending": True, "source_prepared": False, "bank_manifest_sha256": expected_manifest_sha, "bank_revision": identity["bank_revision"], "payload_manifest_sha256": sha(manifest_file), "raw_bytes": sum(row["bytes"] for row in rows), "compressed_bytes": archive.stat().st_size, "archive_sha256": payload["archive_sha256"], "parts": len(parts), "part_bytes": PART_BYTES, "compression_seconds": round(time.monotonic() - started, 3), "teacher_or_isolation_report_included": False, "ref_or_ci_created": False}
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    archive.unlink()
    return payload
