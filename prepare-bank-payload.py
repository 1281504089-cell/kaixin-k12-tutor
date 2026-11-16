"""Prepare only frozen public data/immutable blob plan; source/refs stay pending."""
import argparse
import json
from pathlib import Path

from release_bank import prepare_bank_payload

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bank", type=Path, required=True)
parser.add_argument("--manifest-sha", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
payload = prepare_bank_payload(args.bank, args.manifest_sha, root)
plan = {"schema_version": 1, "status": "bank-only-frozen", "source_pending": True, "source_prepared": False, "repository": "1281504089-cell/kaixin-k12-tutor", "bank_revision": payload["bank_manifest"]["bank_revision"], "bank_manifest_sha256": args.manifest_sha, "files": payload["parts"], "never_merge_into_main": True, "no_tree_commit_branch_ref_or_ci": True}
file = root / "BANK-CONNECTOR-UPLOAD-PLAN.json"
if file.exists():
    assert json.loads(file.read_text()) == plan
else:
    file.write_text(json.dumps(plan, indent=2) + "\n")
print((root / "BANK-PAYLOAD-STATE.json").read_text())
