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
                assert urlparse(response.geturl()).hostname in {"127.0.0.1", "localhost", "::1"}
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
    assert catalog["physical_readable_count"] == manifest["question_count"]
    assert first["total"] == catalog["effective_readable_count"] and first["content_read"] is False
    assert catalog["physical_readable_count"] - catalog["effective_readable_count"] == catalog["runtime_isolated_count"] == 16
    assert catalog["effective_exercise_candidate_count"] == manifest["exercise_candidate_count"] - 16
    assert set(row["qualified_id"] for row in first["questions"]).isdisjoint(row["qualified_id"] for row in second["questions"])
    for subject in catalog["subjects"]:
        if not subject["id"]:
            continue
        scoped = get("/api/student/question-bank/questions?limit=2&subject=" + quote(subject["id"]))
        assert all(row["subject"] == subject["id"] for row in scoped["questions"])
    fts = get("/api/student/question-bank/questions?subject=physics&query=" + quote("浮力") + "&limit=2")
    assert fts["questions"] and fts["total"] > 0 and all(row["subject"] == "physics" for row in fts["questions"])
    nohit = get("/api/student/question-bank/questions?query=qaemptyfts9bd2e81a5dc74c22b2a8f75c6908c7b1&limit=2")
    assert nohit["total"] == 0 and nohit["questions"] == []
    database = sqlite3.connect((pack / "index.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    database.execute("PRAGMA query_only=ON")
    try:
        ledger = json.loads((core / "deeptutor/services/student_learning/question_source_exclusions.json").read_text())
        excluded = {}
        for identity, rule in ledger["exclusions"].items():
            row = database.execute("SELECT d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.qualified_id=?", (identity,)).fetchone()
            if row and rule["bad_asset_sha256"] in {asset["id"] for asset in json.loads(row[0])["assets"]}:
                excluded[identity] = rule["bad_asset_sha256"]
        assert len(excluded) == catalog["runtime_isolated_count"] == 16
        for listed in [*first["questions"], *second["questions"], *fts["questions"]]:
            packed = json.loads(database.execute("SELECT d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.qualified_id=?", (listed["qualified_id"],)).fetchone()[0])
            assert type(listed["can_select_original"]) is bool and listed["can_select_original"] is packed["can_select_original"]
            assert listed["quality_flags"] == packed["quality_flags"]
        image = next((row for row in database.execute("SELECT q.qualified_id,d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE json_array_length(d.body_json,'$.assets')>0 ORDER BY q.qualified_id") if row[0] not in excluded), None)
        ids = [row["qualified_id"] for row in first["questions"]]
        if image:
            ids.append(image[0])
        for identity in dict.fromkeys(ids):
            path = "/api/student/question-bank/questions/" + quote(identity, safe="") + "?revision=" + revision
            detail = get(path)
            expected = json.loads(database.execute("SELECT d.body_json FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.qualified_id=?", (identity,)).fetchone()[0])
            assert detail["qualified_id"] == identity and detail["bank_revision"] == revision and detail["content_read"] is True
            assert detail["question"] == expected["question"] and detail["options"] == expected["options"] and detail["subquestions"] == expected["subquestions"]
            expected_html = expected["question_html"]
            for asset in detail["assets"]:
                expected_html = expected_html.replace("bank-asset:" + asset["id"], asset["url"].replace("&", "&amp;"))
            assert detail["question_html"] == expected_html
            assert not {"answer", "analysis", "teacher_evidence", "teacher_snapshot"}.intersection(detail)
            assert detail["source"]["url"] == "#dt-question-" + revision + "-" + quote(identity, safe="")
            for asset in detail["assets"]:
                row = database.execute("SELECT bytes,sha256 FROM assets WHERE asset_id=?", (asset["id"],)).fetchone()
                raw = get(asset["url"], raw=True)
                assert len(raw) == row[0] and hashlib.sha256(raw).hexdigest() == row[1]
        get("/api/student/question-bank/questions/qa-no-such-question?revision=" + revision, 404)
        get("/api/student/question-bank/questions/" + quote(ids[0], safe="") + "?revision=" + "0" * 64, 404)
        blocked_id, blocked_sha = next(iter(excluded.items()))
        get("/api/student/question-bank/questions/" + quote(blocked_id, safe="") + "?revision=" + revision, 404)
        get("/api/student/question-bank/assets/" + blocked_sha + "?question_id=" + quote(blocked_id, safe="") + "&revision=" + revision, 404)
    finally:
        database.close()
    return {"passed": True, "bank_revision": revision, "physical_readable_count": manifest["question_count"], "effective_readable_count": catalog["effective_readable_count"], "runtime_isolated_count": catalog["runtime_isolated_count"], "effective_exercise_candidate_count": catalog["effective_exercise_candidate_count"], "source_count": catalog["total"], "complete_source_unit_compared_to_pack": True, "image_question_checked": bool(image), "pagination_disjoint": True, "subject_filters": True, "fts_search_passed": True, "fts_empty_query_passed": True, "item_quality_metadata_matched": True, "wrong_revision_rejected": True, "unknown_question_rejected": True, "teacher_fields_absent": True, "teacher_fields_check_scope": "JSON sidecar fields only; body compared to frozen student pack, not an exhaustive embedded-answer review", "model_calls": 0, "formal_data_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.frontend, args.core)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result))
