"""Run only QA code in a disposable native copy against the fresh candidate home."""
import json
import os
from pathlib import Path
import shutil
import subprocess


NATIVE_PAGE_CHECKS = ("body_dom_before_pdf_response", "canvas_pixels_verified", "page_range_verified", "selected_page_verified", "native_http_pdf_sha_verified", "private_headers_verified", "correct_source_opened", "dialog_within_viewport", "second_history_restore")


def validate_native_page_views(ui, fixture):
    assert ui['passed'] is True and ui['actualNativeRenderer'] is True and ui['schema_version'] == 2
    assert ui['bank_revision'] == fixture['bank_revision'] and len(ui['views']) == 4
    for view in ui['views']:
        assert all(view['preparedPicture'][key] is True for key in ('native_http_image_sha_verified', 'body_dom_before_image_response', 'second_history_restore'))
        pages = view['nativePages']
        assert pages['renderer'] == 'native-pages'
        assert pages['response_capture'] == 'Fetch.getResponseBody' and isinstance(pages['original_request_id'],str) and pages['original_request_id']
        assert pages['inline_probe']['ready'] is True and pages['modal_probe']['ready'] is True
        assert pages['qualified_id'] == fixture['qualified_id'] and pages['bank_revision'] == fixture['bank_revision']
        for key in ('sha256', 'bytes', 'page_count', 'start_page', 'end_page'):
            assert pages[key] == fixture['native'][key], key
        assert 1 <= pages['start_page'] <= pages['end_page'] <= pages['page_count']
        assert all(pages[key] is True for key in NATIVE_PAGE_CHECKS)


def validate_native_page_api(api, expected):
    proof = api['native_pages']
    assert proof['passed'] is True and proof['model_calls'] == 0 and proof['wrong_sha_and_revision_rejected'] is True
    for key in ('manifest_sha256', 'records', 'pdfs', 'total_bytes'):
        assert proof[key] == expected[key], key
    assert len(proof['samples']) == 4 and {row['subject'] for row in proof['samples']} == {'math', 'physics', 'chemistry', 'biology'}
    assert len({row['qualified_id'] for row in proof['samples']}) == 4
    assert all(row['frozen_payload_and_assets_bound'] is True and row['private_pdf_http_sha_verified'] is True for row in proof['samples'])


def verify_picture_fresh(root, target, install, resources, home, evidence):
    active = json.loads((home / 'active.json').read_text())
    base = json.loads((resources / 'seed/runtime.json').read_text())
    core = home / 'runtimes' / active['runtimeId'] / 'core'
    python = home / 'runtimes' / base['runtimeId'] / ('python/python.exe' if target.startswith('windows') else 'python/bin/python3')
    qa_home = home / 'workspace'
    (qa_home / '.k12-release-qa-allowed').touch()
    fixture = evidence / 'k12-fresh-seed.json'
    environment = {**os.environ, 'PYTHONPATH': str(core), 'DEEPTUTOR_HOME': str(qa_home),
        'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}
    subprocess.run([str(python), str(root / 'native-k12-fixture.py'), '--core', str(core), '--home', str(qa_home), '--out', str(fixture)], env=environment, check=True, timeout=120)
    source = resources.parent.parent if target.startswith('macos') else install
    probe = root / ('picture-fresh-' + target + ('.app' if target.startswith('macos') else ''))
    shutil.copytree(source, probe, symlinks=True, ignore=lambda directory, names:
        [name for name in names if name in {'seed', 'update'}] if Path(directory) == resources else [])
    copied = probe / 'Contents/Resources' if target.startswith('macos') else probe / 'resources'
    (copied / 'seed').mkdir()
    shutil.copyfile(resources / 'seed/runtime.json', copied / 'seed/runtime.json')
    package = copied / 'app/package.json'
    value = json.loads(package.read_text()); value['main'] = 'qa/picture-fresh.cjs'
    package.write_text(json.dumps(value, ensure_ascii=False))
    (copied / 'app/qa').mkdir()
    shutil.copyfile(root / 'ci-picture-fresh.cjs', copied / 'app/qa/picture-fresh.cjs')
    shutil.copyfile(root / 'ci-k12-library-ui.cjs', copied / 'app/qa/ci-k12-library-ui.cjs')
    expected = resources / 'app/src'
    assert {p.name for p in expected.iterdir()} == {p.name for p in (copied / 'app/src').iterdir()}
    for file in expected.iterdir():
        assert file.is_file() and (copied / 'app/src' / file.name).read_bytes() == file.read_bytes(), 'Production launcher source changed in the QA copy'
    output = evidence / 'picture-fresh-ui.json'
    if target.startswith('macos'):
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(probe)], check=True)
        executable = probe / 'Contents/MacOS/开心动力超级学霸'
    else:
        executable = probe / '开心动力超级学霸.exe'
    completed = False
    try:
        subprocess.run([str(executable)], env={**os.environ, 'OPEN_DEEPTUTOR_TEST_HOME': str(home),
            'KX_PICTURE_FIXTURE': str(fixture), 'KX_PICTURE_FRESH_OUTPUT': str(output)}, check=True, timeout=720)
        result = json.loads(output.read_text())
        assert result['passed'] and result['active_runtime_id'] == active['runtimeId']
        assert result['k12_library']['passed'] and result['k12_library']['diagnostic_entry'] == 'fresh'
        validate_native_page_views(result['k12_library'], json.loads(fixture.read_text())['native_fixture'])
        assert json.loads((home / 'active.json').read_text()) == active, 'Fresh display QA unexpectedly changed the installed runtime'
        result['production_launcher_source_byte_identical'] = True
        result['qa_code_only_in_disposable_copy'] = True
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        completed = True
        return result
    finally:
        if completed:
            shutil.rmtree(probe)
