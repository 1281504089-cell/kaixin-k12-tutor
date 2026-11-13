#!/usr/bin/env python3
"""Compare synthetic learner data before/after native launcher migration; never copy it into an installer."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3

APP = "开心动力超级学霸"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    if isinstance(value, bytes):
        return {"blob": base64.b64encode(value).decode("ascii")}
    raise TypeError(type(value).__name__)


def profile_snapshot(directory):
    profile = Path(directory).resolve(strict=True)
    if json.loads((profile / ".launcher-migration-synthetic.json").read_text()).get("synthetic") is not True:
        raise ValueError("Only a marked synthetic profile may be inspected")
    roots = [Path(os.environ[name]) / APP for name in ("LOCALAPPDATA", "APPDATA") if name in os.environ]
    roots.append(Path.home() / "Library/Application Support" / APP)
    if any(profile == root.resolve() or root.resolve() in profile.parents for root in roots):
        raise ValueError("Real learner profile is forbidden")
    result = {}
    for file in sorted((profile / "workspace").rglob("*")):
        if file.is_symlink():
            raise ValueError("Synthetic workspace symlinks are not accepted")
        if not file.is_file():
            continue
        name = file.relative_to(profile).as_posix()
        if file.name.endswith(("-wal", "-journal")) and file.stat().st_size:
            raise ValueError("Close the app cleanly before taking a SQLite checkpoint")
        if file.name.endswith(("-wal", "-shm", "-journal")):
            continue
        if file.suffix == ".db":
            # Read-only SQLite takes no write locks and never runs application migrations.
            with sqlite3.connect(file.as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Synthetic learning database is corrupt")
                tables = {}
                for (table,) in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
                    quoted = '"' + table.replace('"', '""') + '"'
                    rows = [sha(json.dumps(row, ensure_ascii=False, default=encode, separators=(",", ":")).encode()) for row in db.execute("select * from " + quoted)]
                    tables[table] = sorted(rows)
                result[name] = {"tables": tables}
        else:
            result[name] = {"sha256": sha(file.read_bytes())}
    if not result:
        raise ValueError("Synthetic profile has no learner fixtures; an empty preservation test is invalid")
    return {"formatVersion": 1, "synthetic": True, "files": result}


def compare(before, after):
    problems = []
    for name, prior in before["files"].items():
        current = after["files"].get(name)
        if current is None:
            problems.append(name + ": missing")
        elif "tables" in prior:
            from collections import Counter
            for table, rows in prior["tables"].items():
                if Counter(rows) - Counter(current.get("tables", {}).get(table, [])):
                    problems.append(name + ": existing rows changed or missing in " + table)
        elif current != prior:
            problems.append(name + ": changed")
    return {"passed": not problems, "synthetic": True, "checkedFiles": len(before["files"]),
            "originalRowsAndSettingsRetained": not problems, "problems": problems,
            "nativeLaunch": "requires separate CI evidence", "nativeUpdateUI": "requires separate CI evidence"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--before", help="Omit to create a checkpoint; otherwise compare against it")
    args = parser.parse_args()
    profile, output = Path(args.profile).resolve(), Path(args.out).resolve()
    if output == profile or profile in output.parents:
        raise ValueError("Checkpoints/reports must be written outside the profile")
    after = profile_snapshot(profile)
    report = compare(json.loads(Path(args.before).read_text(encoding="utf-8")), after) if args.before else after
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, ensure_ascii=False))
    return 0 if report.get("passed", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
