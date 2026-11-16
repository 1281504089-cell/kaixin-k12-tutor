"""Exercise the release smoke itself with tiny synthetic localhost replies only."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Thread
import unittest
from urllib.parse import parse_qs, quote, urlparse

spec = importlib.util.spec_from_file_location("native_k12_smoke", Path(__file__).with_name("native-k12-api-smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class NativeApiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.core = Path(self.temp.name)
        pack = self.core / "deeptutor/services/student_learning/question_bank_data"
        pack.mkdir(parents=True)
        revision = "a" * 64
        self.corrupt_image = False
        self.corrupt_html = False
        image = b"synthetic fixture image bytes"
        image_id = hashlib.sha256(image).hexdigest()
        payloads = {}
        with sqlite3.connect(pack / "index.sqlite3") as conn:
            conn.executescript("CREATE TABLE questions(qualified_id TEXT,payload_sha TEXT);CREATE TABLE documents(payload_sha TEXT,body_json TEXT);CREATE TABLE assets(asset_id TEXT,bytes INTEGER,sha256 TEXT);")
            conn.execute("INSERT INTO assets VALUES(?,?,?)", (image_id, len(image), image_id))
            for number in range(18):
                identity = "source:q" + str(number)
                assets = [] if number == 0 else [{"id": image_id, "media_type": "image/png"}]
                row = {"qualified_id": identity, "title": "合成题源", "subject": "math" if number == 0 else "physics", "can_select_original": number >= 1, "quality_flags": [] if number >= 1 else ["source_unit_only"], "question": "完整条件与唯一问题：一共有多少人？", "question_html": '<p>完整条件与唯一问题</p>' + (f'<img src="bank-asset:{image_id}">' if assets else ''), "options": [], "subquestions": [], "assets": assets}
                payloads[identity] = row
                raw = json.dumps(row)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                conn.execute("INSERT INTO questions VALUES(?,?)", (identity, digest))
                conn.execute("INSERT INTO documents VALUES(?,?)", (digest, raw))
        manifest = {"bank_revision": revision, "teacher_evidence_included": False, "question_count": 18, "exercise_candidate_count": 17, "index_sha256": hashlib.sha256((pack / "index.sqlite3").read_bytes()).hexdigest()}
        (pack / "manifest.json").write_text(json.dumps(manifest))
        (pack.parent / "question_source_exclusions.json").write_text(json.dumps({"schema_version":1,"exclusions":{f"source:q{number}":{"bad_asset_sha256":image_id,"reason":"synthetic conservative image isolation"} for number in range(2,18)}}))
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                url = urlparse(self.path)
                params = parse_qs(url.query)
                if url.path.endswith('/catalog'):
                    result = {"bank_revision": revision, "content_read": False, "total": 1, "physical_readable_count":18,"effective_readable_count":2,"runtime_isolated_count":16,"effective_exercise_candidate_count":1,"subjects": [{"id": "math", "count": 1}, {"id": "physics", "count": 1}]}
                elif url.path.endswith('/questions'):
                    rows = [{"qualified_id": key, "subject": value["subject"], "can_select_original": value["can_select_original"], "quality_flags": value["quality_flags"]} for key, value in payloads.items() if key in {'source:q0','source:q1'}]
                    if params.get('subject'): rows = [row for row in rows if row['subject'] == params['subject'][0]]
                    if params.get('query', [''])[0].startswith('qaemptyfts'): rows = []
                    offset = int(params.get('offset', ['0'])[0])
                    result = {"bank_revision": revision, "content_read": False, "total": len(rows), "questions": rows[offset:offset + 2]}
                elif '/assets/' in url.path:
                    if params.get('question_id', [''])[0] not in {'source:q0','source:q1'}:
                        self.send_response(404); self.end_headers(); return
                    self.send_response(200); self.end_headers(); self.wfile.write(image + (b'tamper' if owner.corrupt_image else b'')); return
                else:
                    from urllib.parse import unquote
                    identity = unquote(url.path.rsplit('/', 1)[-1])
                    if identity not in {'source:q0','source:q1'} or params.get('revision') != [revision]:
                        self.send_response(404); self.end_headers(); return
                    result = {**payloads[identity], "bank_revision": revision, "content_read": True, "source": {"url": '#dt-question-' + revision + '-' + quote(identity, safe='')}}
                    result['assets'] = [{**asset, "url": '/api/student/question-bank/assets/' + asset['id'] + '?question_id=' + quote(identity, safe='') + '&revision=' + revision} for asset in result['assets']]
                    for asset in result['assets']:
                        result['question_html'] = result['question_html'].replace('bank-asset:' + asset['id'], asset['url'].replace('&', '&amp;'))
                    if owner.corrupt_html:
                        result['question_html'] += '<p>unverified extra teacher text</p>'
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def test_complete_original_and_image_roundtrip(self):
        report = smoke.run(self.url, self.core)
        self.assertTrue(report['passed'] and report['image_question_checked'])
        self.assertEqual(report['model_calls'], 0)

    def test_changed_image_is_rejected(self):
        self.corrupt_image = True
        with self.assertRaises(AssertionError):
            smoke.run(self.url, self.core)

    def test_extra_html_not_in_student_pack_is_rejected(self):
        self.corrupt_html = True
        with self.assertRaises(AssertionError):
            smoke.run(self.url, self.core)


if __name__ == '__main__':
    unittest.main()
