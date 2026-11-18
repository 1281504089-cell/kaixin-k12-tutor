"""Freeze a temporary candidate-branch upload plan; never upload or promote."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from release_source import safe_name, sha


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-sha", required=True)
    parser.add_argument("--base-tree-sha", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"codex/k12-core-202611(?:16|17)-[A-Za-z0-9._-]+", args.branch)
    assert all(re.fullmatch(r"[a-f0-9]{40}", value) for value in [args.parent_sha, args.base_tree_sha])
    root = Path(__file__).resolve().parent
    config = json.loads((root / "attachment-release.json").read_text())
    assert config.get("prepared") is True and config["tag"].startswith(("student-20261116-", "student-20261117-"))
    source = json.loads((root / "source-manifest.json").read_text())["sourceOverlay"]
    bank = json.loads((root / "bank-payload-manifest.json").read_text())
    names = {row["file"] for row in json.loads((root / "RECIPE-FILES-20261116.json").read_text())}
    names.update(["RECIPE-FILES-20261116.json", "source-manifest.json", "source-inventory-20261116.json", "runtime-source-manifest.json", "bank-payload-manifest.json", "isolation-ledger.json", "launcher-manifest.json"])
    names.update(row["file"] for row in [*source["parts"], *bank["parts"]])
    rows = []
    for name in sorted(names, key=lambda name: (name.startswith("bank-payload.") and not name.endswith(".json"), name)):
        file = root / safe_name(name)
        assert file.is_file() and not file.is_symlink()
        size = file.stat().st_size
        git = hashlib.sha1(("blob " + str(size) + "\0").encode())
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                git.update(chunk)
        rows.append({"file": name, "bytes": size, "sha256": sha(file), "git_blob_sha": git.hexdigest()})
    plan = {"schema_version": 1, "status": "owner_frozen_temporary_transport_branch_only", "repository": "1281504089-cell/kaixin-k12-tutor", "branch": args.branch, "parent_sha": args.parent_sha, "base_tree_sha": args.base_tree_sha, "source_commit": config["source_commit"], "tag": config["tag"], "files": rows, "never_merge_into_main": True, "main_publication_parent": "verified previous main, plus small metadata/recipe/source-asset references only", "delete_old_releases": False}
    destination = root / "CONNECTOR-UPLOAD-PLAN.json"
    assert not destination.exists(), "Preserve the frozen plan; use a new attempt for changed inputs"
    destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": len(rows), "bytes": sum(row["bytes"] for row in rows), "plan_sha256": sha(destination), "branch": args.branch}))
