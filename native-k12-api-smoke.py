"""Installed candidate API checks against its own immutable student pack; no model."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen


def run(frontend, core):
    assert urlparse(frontend).hostname in {"127.0.0.1", "localhost", "::1"}
    pack = core / "deeptutor/services/student_learning/question_bank_data"
    manifest = json.loads((pack / "manifest.json").read_text())
    revision = manifest["bank_revision"]
    assert manifest["teacher_evidence_included"] is False
    with (pack / "index.sqlite3").open("rb") as file:
        assert hashlib.file_digest(file, "sha256").hexdigest() == manifest["index_sha256"]

    def get(path, expected=200, raw=False):
        assert path.startswith("/") and not path.startswith("//")
        try:
            with urlopen(urljoin(frontend, path), timeout=30) as response:
                assert response.status == expected
                body = response.read()
                return body if raw else json.loads(body)
        except HTTPError as error:
            assert error.code == expected, (path, error.code, expected)
            return None

    catalog = get("/api/student/question-bank/catalog?limit=2")
    assert catalog["bank_revision"] == revision and catalog["content_read"] is False and catalog["total"] > 0
    first = get("/api/student/question-bank/questions?limit=2")
    second = get("/api/student/question-bank/questions?limit=2&offset=2")
    assert first["bank_revision"] == second["bank_revision"] == revision
    assert first["total"] == manifest["question_count"] and first["content_read"] is False
    assert set(row["qualified_id"] for row in first["questions"]).isdisjoint(row["qualified_id"] for row in second["questions"])
    for subject in catalog["subjects"]:
        scoped = get("/api/student/question-bank/questions?limit=2&subject=" + quote(subject["id"]))
        assert all(row["subject"] == subject["id"] for row in scoped["questions"])
    database = sqlite3.connect((pack / "index.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    database.execute("PRAGMA query_only=ON")
    try:
        image = database.execute("SELECT q.qualified_id,d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE json_array_length(d.body_json,'$.assets')>0 ORDER BY q.qualified_id LIMIT 1").fetchone()
        ids = [row["qualified_id"] for row in first["questions"]]
        if image:
            ids.append(image[0])
        for identity in dict.fromkeys(ids):
            path = "/api/student/question-bank/questions/" + quote(identity, safe="") + "?revision=" + revision
            detail = get(path)
            expected = json.loads(database.execute("SELECT d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.qualified_id=?", (identity,)).fetchone()[0])
            assert detail["qualified_id"] == identity and detail["bank_revision"] == revision and detail["content_read"] is True
            assert detail["question"] == expected["question"] and detail["options"] == expected["options"] and detail["subquestions"] == expected["subquestions"]
            assert not {"answer", "analysis", "teacher_evidence", "teacher_snapshot"}.intersection(detail)
            assert detail["source"]["url"] == "#dt-question-" + revision + "-" + quote(identity, safe="")
            for asset in detail["assets"]:
                row = database.execute("SELECT bytes,sha256 FROM assets WHERE asset_id=?", (asset["id"],)).fetchone()
                raw = get(asset["url"], raw=True)
                assert len(raw) == row[0] and hashlib.sha256(raw).hexdigest() == row[1]
        get("/api/student/question-bank/questions/qa-no-such-question?revision=" + revision, 404)
        get("/api/student/question-bank/questions/" + quote(ids[0], safe="") + "?revision=" + "0" * 64, 404)
    finally:
        database.close()
    return {"passed": True, "bank_revision": revision, "question_count": manifest["question_count"], "source_count": catalog["total"], "complete_question_compared_to_pack": True, "image_question_checked": bool(image), "pagination_disjoint": True, "subject_filters": True, "wrong_revision_rejected": True, "unknown_question_rejected": True, "teacher_fields_absent": True, "model_calls": 0, "formal_data_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.frontend, args.core)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result))
