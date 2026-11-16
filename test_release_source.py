"""Offline hostile-input checks; no product import, model, network or signing key."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from release_source import add_file, aggregate, apply_overlay, inventory, runtime_rows, safe_name, sha


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "student-source"
        self.source.mkdir()
        subprocess.run(["git", "init", "--quiet"], cwd=self.source, check=True)
        (self.source / "keep.py").write_text("published\n")
        (self.source / "remove.py").write_text("obsolete\n")
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        self.base = inventory(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def overlay(self, entries=None):
        content = b"new frozen bytes\n"
        row = {"file": "keep.py", "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "mode": 0o644}
        archive = self.root / "source-overlay.001"
        with archive.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped, tarfile.open(fileobj=zipped, mode="w|") as package:
            for name in entries or ["keep.py"]:
                add_file(package, name, io.BytesIO(content), len(content))
        manifest = {"source_commit": "f" * 40, "baseline_source_files_sha256": aggregate(self.base), "files": [row], "changed": [row], "removed": ["remove.py"]}
        file = self.root / "inventory.json"
        file.write_text(json.dumps(manifest))
        return {"manifest": file.name, "manifest_sha256": sha(file), "parts": [{"file": archive.name, "bytes": archive.stat().st_size, "sha256": sha(archive)}], "archive_sha256": sha(archive), "source_files_sha256": aggregate([row])}

    def test_source_overlay_roundtrip_preserves_exact_hash_and_removes_deleted(self):
        descriptor = self.overlay()
        result = apply_overlay(self.root, self.source, descriptor)
        self.assertEqual(result["source_commit"], "f" * 40)
        self.assertEqual((self.source / "keep.py").read_text(), "new frozen bytes\n")
        self.assertFalse((self.source / "remove.py").exists())

    def test_changed_published_parent_rejected_before_overlay(self):
        descriptor = self.overlay()
        (self.source / "keep.py").write_text("not published\n")
        with self.assertRaisesRegex(ValueError, "parent differs"):
            apply_overlay(self.root, self.source, descriptor)
        self.assertTrue((self.source / "remove.py").exists())

    def test_tampered_overlay_part_rejected(self):
        descriptor = self.overlay()
        with (self.root / "source-overlay.001").open("ab") as file:
            file.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "part checksum"):
            apply_overlay(self.root, self.source, descriptor)

    def test_duplicate_overlay_member_rejected(self):
        descriptor = self.overlay(["keep.py", "keep.py"])
        with self.assertRaisesRegex(ValueError, "Unexpected source overlay"):
            apply_overlay(self.root, self.source, descriptor)

    def test_unlisted_overlay_member_rejected(self):
        descriptor = self.overlay(["outside.py"])
        with self.assertRaisesRegex(ValueError, "Unexpected source overlay"):
            apply_overlay(self.root, self.source, descriptor)

    def test_symlink_source_rejected(self):
        descriptor = self.overlay()
        (self.source / "keep.py").unlink()
        (self.source / "keep.py").symlink_to(self.root / "private")
        with self.assertRaisesRegex(ValueError, "regular frozen"):
            apply_overlay(self.root, self.source, descriptor)

    def test_paths_reject_traversal_hidden_state_and_private_key(self):
        for name in ["../outside", "/outside", "x\\file", "C:/file", "x/.git/config", "data/user/settings.json", "signing-private.pem", "x//file"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_name(name)

    def test_runtime_inventory_carries_new_package_data_and_cjs(self):
        names = ["deeptutor/new.py", "deeptutor/services/student_learning/reference.cjs", "deeptutor/services/student_learning/textbook-models/model.onnx", "deeptutor/services/student_learning/textbook-defaults/reference.sqlite3", "scripts/new.py", "assets/brand/logo.png", "assets/figs/system/diagram.png", "tests/test_new.py", "web/app/page.tsx"]
        selected = {row["file"] for row in runtime_rows([{"file": name} for name in names])}
        self.assertEqual(selected, set(names[:6]))


if __name__ == "__main__":
    unittest.main()
