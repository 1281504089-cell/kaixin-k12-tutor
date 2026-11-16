"""Tiny synthetic bank bytes only; no teacher/originals, model or network."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from release_bank import PREFIX, prepare_bank_payload
from release_source import sha


class ReleaseBankTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bank, self.out = self.root / "bank", self.root / "recipe"
        (self.bank / "student-assets").mkdir(parents=True)
        self.out.mkdir()
        (self.bank / "index.sqlite3").write_bytes(b"tiny synthetic index")
        (self.bank / "student-assets/a.png").write_bytes(b"tiny synthetic image")
        (self.bank / "isolation-report.json").write_text("PRIVATE-SYNTHETIC-ISOLATED-IDS")
        manifest = {"schema_version": 1, "bank_revision": "b" * 64, "teacher_evidence_included": False, "raw_snapshots_included": False,
                    "index_bytes": 20, "index_sha256": sha(self.bank / "index.sqlite3"), "asset_count": 1, "asset_bytes": 20,
                    "isolation_report_sha256": sha(self.bank / "isolation-report.json")}
        (self.bank / "manifest.json").write_text(json.dumps(manifest))
        self.freeze = sha(self.bank / "manifest.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_same_shared_function_reuses_identical_parts_and_excludes_isolated_ids(self):
        first = prepare_bank_payload(self.bank, self.freeze, self.out)
        raw = b"".join((self.out / row["file"]).read_bytes() for row in first["parts"])
        with tarfile.open(fileobj=io.BytesIO(raw)) as package:
            names = package.getnames()
            self.assertEqual(set(names), {PREFIX + "/manifest.json", PREFIX + "/index.sqlite3", PREFIX + "/student-assets/a.png"})
            self.assertNotIn(b"PRIVATE-SYNTHETIC", b"".join(package.extractfile(item).read() for item in package))
        second = prepare_bank_payload(self.bank, self.freeze, self.out)
        self.assertEqual(first, second)
        state = json.loads((self.out / "BANK-PAYLOAD-STATE.json").read_text())
        self.assertEqual(state["status"], "bank-only-frozen")
        self.assertTrue(state["source_pending"])
        self.assertFalse(state["source_prepared"])

    def test_reuse_rejects_changed_transport_bytes(self):
        first = prepare_bank_payload(self.bank, self.freeze, self.out)
        with (self.out / first["parts"][0]["file"]).open("ab") as file:
            file.write(b"changed")
        with self.assertRaises(AssertionError):
            prepare_bank_payload(self.bank, self.freeze, self.out)

    def test_new_freeze_cannot_silently_overwrite_existing_parts(self):
        prepare_bank_payload(self.bank, self.freeze, self.out)
        data = json.loads((self.bank / "manifest.json").read_text());data["bank_revision"] = "c" * 64
        (self.bank / "manifest.json").write_text(json.dumps(data))
        with self.assertRaises(AssertionError):
            prepare_bank_payload(self.bank, sha(self.bank / "manifest.json"), self.out)

    def test_unapproved_teacher_file_is_rejected(self):
        (self.bank / "teacher.txt").write_text("synthetic forbidden teacher evidence")
        with self.assertRaises(AssertionError):
            prepare_bank_payload(self.bank, self.freeze, self.out)


if __name__ == "__main__":
    unittest.main()
