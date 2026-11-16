"""Bounded, hash-checked connector input/output. Never reads credentials."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from release_source import safe_name, sha

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["state", "read", "checkpoint"])
parser.add_argument("--file")
parser.add_argument("--offset", type=int, default=0)
parser.add_argument("--record-base64")
parser.add_argument("--plan", default="CONNECTOR-UPLOAD-PLAN.json", choices=["CONNECTOR-UPLOAD-PLAN.json", "BANK-CONNECTOR-UPLOAD-PLAN.json"])
args = parser.parse_args()
if args.action == "read" and (root / ".bank-upload.pause").exists():
    raise SystemExit("Paused before a new immutable blob request; checkpoints preserved")
plan = json.loads((root / args.plan).read_text())
checkpoint = root / ".connector-checkpoints"
checkpoint.mkdir(exist_ok=True)
if args.action == "state":
    print(json.dumps({"plan": plan, "checkpoint": [json.loads(file.read_text()) for file in checkpoint.glob("*.json")]}))
elif args.action == "read":
    row = next(row for row in plan["files"] if row["file"] == args.file)
    file = root / safe_name(row["file"])
    assert file.stat().st_size == row["bytes"] and sha(file) == row["sha256"]
    assert 0 <= args.offset <= row["bytes"]
    # A complete <=512 KiB part fits the measured output cap. Larger metadata
    # uses 384 KiB chunks divisible by three for safe base64 concatenation.
    length = 512 * 1024 if row["bytes"] <= 512 * 1024 else 384 * 1024
    with file.open("rb") as stream:
        stream.seek(args.offset);data = stream.read(length)
    print(json.dumps({"file": row["file"], "offset": args.offset, "bytes": len(data), "base64": base64.b64encode(data).decode()}))
else:
    record = json.loads(base64.b64decode(args.record_base64, validate=True))
    if "file" in record:
        row = next(row for row in plan["files"] if row["file"] == record["file"])
        assert record["sha256"] == row["sha256"] and record["blob_sha"] == row["git_blob_sha"]
        name = hashlib.sha256(row["file"].encode()).hexdigest() + ".json"
    else:
        assert record["branch"] == plan["branch"] and record["parent_sha"] == plan["parent_sha"]
        name = "FINAL.json"
    destination = checkpoint / name
    temporary = destination.with_suffix(".partial")
    temporary.write_text(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(destination)
    print(json.dumps({"saved": name}))
