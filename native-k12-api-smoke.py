"""Installed candidate API checks against its own immutable student pack; no model."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen


NATIVE_EXPECTED = {"manifest_sha256": "91631719fe6e228a0b580d469a15943bb5ba80828f5114ea10e731dcd598da0a",
    "records": 6915, "pdfs": 698, "total_bytes": 295359867,
    "samples": {"math:q_e9dd00ffa1178d29b41fadb4_2": "math", "new-five:q_0264cefbf2bc2978e20b01f3_b00012_3": "physics",
        "five-subject:src_04fccdbddbb0696b58cc5678_b00001_full": "biology", "five-subject:q_075b4515a0802954bc5c6a4f": "chemistry"}}


def verify_native_pages(get, core, revision, database, expected):
    root = core / "deeptutor/services/student_learning/question_native_data"
    raw_manifest = (root / "manifest.json").read_bytes()
    assert hashlib.sha256(raw_manifest).hexdigest() == expected["manifest_sha256"]
    manifest = json.loads(raw_manifest)
    assert manifest["bank_revision"] == revision and len(manifest["items"]) == expected["records"]
    files = {item["file"] for item in manifest["items"].values()}
    assert files == {p.relative_to(root).as_posix() for p in (root / "documents").glob("*.pdf")}
    assert len(files) == expected["pdfs"] and sum((root / name).stat().st_size for name in files) + len(raw_manifest) == expected["total_bytes"]
    checks = []
    for identity, subject in expected["samples"].items():
        item = manifest["items"][identity]
        row = database.execute("SELECT q.payload_sha,d.body_json FROM questions q JOIN documents d USING(payload_sha) WHERE q.qualified_id=?", (identity,)).fetchone()
        assert row and row[0] == item["source_payload_sha256"] == hashlib.sha256(row[1].encode()).hexdigest()
        payload = json.loads(row[1])
        assert payload["subject"] == subject and payload["source_hash"] == item["source_hash"]
        assert [asset["id"] for asset in payload["assets"]] == item["asset_sha256"]
        detail = get("/api/student/question-bank/questions/" + quote(identity, safe="") + "?revision=" + revision)
        url = "/api/student/question-bank/native/" + quote(identity, safe="") + "?revision=" + revision + "&sha256=" + item["sha256"]
        descriptor = {"url": url, **{key: item[key] for key in ("sha256", "bytes", "page_count", "start_page", "end_page", "kind")}}
        assert detail["source"]["native_required"] is True and detail["source"]["native"] == descriptor
        raw, headers = get(url, raw=True, headers=True)
        assert headers["Content-Type"] == "application/pdf" and headers["Cache-Control"] == "private, no-store"
        assert headers["X-Content-Type-Options"] == "nosniff" and headers["Content-Security-Policy"] == "default-src 'none'; sandbox"
        assert len(raw) == item["bytes"] and raw.startswith(b"%PDF-") and hashlib.sha256(raw).hexdigest() == item["sha256"]
        get(url.replace(revision, "0" * 64), 404)
        get(url.replace(item["sha256"], "0" * 64), 404)
        checks.append({"qualified_id": identity, "subject": subject, "sha256": item["sha256"], "bytes": len(raw),
            "pages": [item["start_page"], item["end_page"]], "frozen_payload_and_assets_bound": True, "private_pdf_http_sha_verified": True})
    return {"passed": True, "manifest_sha256": expected["manifest_sha256"], "records": len(manifest["items"]), "pdfs": len(files),
        "total_bytes": expected["total_bytes"], "samples": checks, "wrong_sha_and_revision_rejected": True, "model_calls": 0}


def run(frontend, core, native_expected=None):
    assert urlparse(frontend).hostname in {"127.0.0.1", "localhost", "::1"}
    pack = core / "deeptutor/services/student_learning/question_bank_data"
    manifest = json.loads((pack / "manifest.json").read_text())
    revision = manifest["bank_revision"]
    assert manifest["teacher_evidence_included"] is False
    with (pack / "index.sqlite3").open("rb") as file:
        assert hashlib.file_digest(file, "sha256").hexdigest() == manifest["index_sha256"]

    def get(path, expected=200, raw=False, headers=False):
        assert path.startswith("/") and not path.startswith("//")
        try:
            with urlopen(urljoin(frontend, path), timeout=30) as response:
                assert urlparse(response.geturl()).hostname in {"127.0.0.1", "localhost", "::1"}
                assert response.status == expected
                body = response.read()
                result = body if raw else json.loads(body)
                return (result, response.headers) if headers else result
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
    assert catalog["physical_readable_count"] - catalog["effective_readable_count"] == catalog["runtime_isolated_count"]
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
        excluded_kinds = {"bad_asset_sha256": 0, "bad_payload_sha256": 0}
        removed_readable = removed_exercise = 0
        for identity, rule in ledger["exclusions"].items():
            row = database.execute("SELECT d.body_json,q.payload_sha,q.usable,q.exercise FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.qualified_id=?", (identity,)).fetchone()
            if row is None:
                continue
            assert hashlib.sha256(row[0].encode()).hexdigest() == row[1]
            body = json.loads(row[0])
            asset_bad = rule.get("bad_asset_sha256") in {asset["id"] for asset in body["assets"]}
            payload_bad = rule.get("bad_payload_sha256") == row[1]
            if asset_bad or payload_bad:
                excluded[identity] = {"assets": body["assets"], "kind": "bad_asset_sha256" if asset_bad else "bad_payload_sha256"}
                excluded_kinds[excluded[identity]["kind"]] += 1
                removed_readable += int(bool(row[2]))
                removed_exercise += int(bool(row[3]))
        assert len(excluded) == catalog["runtime_isolated_count"]
        assert catalog["effective_readable_count"] == manifest["question_count"] - removed_readable
        assert catalog["effective_exercise_candidate_count"] == manifest["exercise_candidate_count"] - removed_exercise
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
        picture_root = core / "deeptutor/services/student_learning/question_picture_data"
        pictures = json.loads((picture_root / "manifest.json").read_text())
        assert pictures["schema_version"] == 1 and pictures["bank_revision"] == revision
        assert pictures["teacher_evidence_included"] is False and pictures["items"], "Required prepared question display pack is absent"
        bindings = []
        for identity, item in pictures["items"].items():
            row = database.execute("SELECT q.payload_sha,d.body_json FROM questions q JOIN documents d USING(payload_sha) WHERE q.qualified_id=?", (identity,)).fetchone()
            assert row and hashlib.sha256(row[1].encode()).hexdigest() == row[0] == item["source_payload_sha256"]
            expected = json.loads(row[1])
            assert identity not in excluded and expected["source_hash"] == item["source_hash"]
            assert item["asset_sha256"] == [asset["id"] for asset in expected["assets"]]
            assert item["file"] == "images/" + item["sha256"] + ".webp"
            file = picture_root / item["file"]
            assert not file.is_symlink() and not (picture_root / "images").is_symlink()
            assert file.resolve().is_relative_to(picture_root.resolve())
            raw = file.read_bytes()
            assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
            bindings.append(identity)
        selections = list(dict.fromkeys([bindings[0], bindings[len(bindings) // 2], bindings[-1], max(bindings, key=lambda identity: len(pictures["items"][identity]["asset_sha256"]))]))
        picture_checks = []
        from PIL import Image
        for identity in selections:
            item = pictures["items"][identity]
            detail = get("/api/student/question-bank/questions/" + quote(identity, safe="") + "?revision=" + revision)
            expected_picture = {"url": "/api/student/question-bank/pictures/" + quote(identity, safe="") + "?revision=" + revision,
                **{key: item[key] for key in ("sha256", "bytes", "width", "height")}}
            assert detail["source"]["picture"] == expected_picture
            raw, headers = get(expected_picture["url"], raw=True, headers=True)
            assert headers["Cache-Control"] == "private, no-store" and headers["Content-Type"] == "image/webp"
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
            with Image.open(BytesIO(raw)) as image:
                image.load()
                assert image.format == "WEBP" and image.size == (item["width"], item["height"])
            get(expected_picture["url"].replace(revision, "0" * 64), 404)
            picture_checks.append({"qualified_id": identity, "sha256": item["sha256"], "bytes": len(raw), "width": item["width"], "height": item["height"], "source_payload_bound": True, "all_original_assets_bound": True, "decoded_native_webp": True, "private_no_store": True})
        get("/api/student/question-bank/pictures/" + quote(selections[0], safe="") + "?revision=", 422)
        get("/api/student/question-bank/pictures/qa-no-such-question?revision=" + revision, 404)
        get("/api/student/question-bank/questions/qa-no-such-question?revision=" + revision, 404)
        get("/api/student/question-bank/questions/" + quote(ids[0], safe="") + "?revision=" + "0" * 64, 404)
        for kind in [key for key, count in excluded_kinds.items() if count]:
            blocked_id, blocked = next((identity, item) for identity, item in excluded.items() if item["kind"] == kind)
            get("/api/student/question-bank/questions/" + quote(blocked_id, safe="") + "?revision=" + revision, 404)
            get("/api/student/question-bank/pictures/" + quote(blocked_id, safe="") + "?revision=" + revision, 404)
            for asset in blocked["assets"]:
                get("/api/student/question-bank/assets/" + asset["id"] + "?question_id=" + quote(blocked_id, safe="") + "&revision=" + revision, 404)
        native_pages = verify_native_pages(get, core, revision, database, native_expected or NATIVE_EXPECTED)
    finally:
        database.close()
    return {"passed": True, "bank_revision": revision, "native_pages": native_pages, "prepared_picture_bindings": len(bindings), "prepared_picture_manifest_sha256": hashlib.sha256((picture_root / "manifest.json").read_bytes()).hexdigest(), "prepared_picture_api": picture_checks, "physical_readable_count": manifest["question_count"], "effective_readable_count": catalog["effective_readable_count"], "runtime_isolated_count": catalog["runtime_isolated_count"], "runtime_exclusion_kinds": excluded_kinds, "runtime_exclusion_ledger_sha256": hashlib.sha256((core / "deeptutor/services/student_learning/question_source_exclusions.json").read_bytes()).hexdigest(), "effective_exercise_candidate_count": catalog["effective_exercise_candidate_count"], "source_count": catalog["total"], "complete_source_unit_compared_to_pack": True, "image_question_checked": bool(image), "pagination_disjoint": True, "subject_filters": True, "fts_search_passed": True, "fts_empty_query_passed": True, "item_quality_metadata_matched": True, "wrong_revision_rejected": True, "unknown_question_rejected": True, "teacher_fields_absent": True, "teacher_fields_check_scope": "JSON sidecar fields only; body compared to frozen student pack, not an exhaustive embedded-answer review", "model_calls": 0, "formal_data_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.frontend, args.core)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result))
