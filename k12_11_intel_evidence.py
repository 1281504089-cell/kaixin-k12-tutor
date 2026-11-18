"""Recover completed Intel k12-11 scenes from their exact GitHub Actions artifact."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from ci_picture_fresh import validate_native_page_views

REPO = '1281504089-cell/kaixin-k12-tutor'
ARTIFACT = dict(id=14467292941, bytes=12230539, sha256='cf36699f14ac38d1bc6567ffbc37737c5fc6940874a95526391da780a8076085',
                run_id=44362174807, job_id=135006233250, workflow_commit='a7dadd1f1c9e803ab1aa7a6f3a111a60c63fdd30')
COMPLETED = {'update_entry': 'update-entry.json', 'oldest_launcher_entry': 'oldest-update-entry.json',
             'materials_launcher_entry': 'materials-update-entry.json'}
FRESH = 'picture-fresh-ui.json'


def read_completed(lock, archive_bytes):
    assert lock['candidate_tag'] == 'student-20261117-k12-11' and lock['target'] == 'macos-x64'
    assert lock['resume_artifact'] == ARTIFACT
    assert set(lock['reused_complete_entries']) == set(COMPLETED)
    assert len(archive_bytes) == ARTIFACT['bytes'] and sha256(archive_bytes).hexdigest() == ARTIFACT['sha256']
    records, files = {}, {}
    with ZipFile(BytesIO(archive_bytes)) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert 'materials-oldest-update-entry.json' not in archive.namelist()
        for key, name in {**COMPLETED, 'fresh_picture_ui': FRESH}.items():
            binding = lock['reused_fresh_picture_ui'] if key == 'fresh_picture_ui' else lock['reused_complete_entries'][key]
            assert binding['file'] == name and 0 < binding['bytes'] < 2_000_000
            raw = archive.read(name)
            assert len(raw) == binding['bytes'] and sha256(raw).hexdigest() == binding['sha256']
            record = json.loads(raw)
            files[name] = raw
            records[key] = record
            ui = record['k12_library']
            assert ui['passed'] and ui['actualNativeRenderer'] and ui['bank_revision'] == lock['bank_revision']
            assert ui['model_calls'] == 0 and len(ui['views']) == 4
            validate_native_page_views(ui, lock['native_pages']['ui_fixture'])
            for view in ui['views']:
                assert all(view['preparedPicture'][prop] is True for prop in
                           ('native_http_image_sha_verified', 'body_dom_before_image_response', 'second_history_restore'))
    fresh = records.pop('fresh_picture_ui')
    assert fresh['passed'] and fresh['production_launcher_source_byte_identical'] and fresh['qa_code_only_in_disposable_copy']
    assert fresh['active_runtime_id'] == lock['included_manifest']['runtimeId']
    for key, value in records.items():
        assert value['actual_download_install_backup_restart'] == 'passed' and value['check_again_current']
        assert value['native_arch'] == 'x64' and value['native_platform'] == 'darwin'
        assert all(value[prop] for prop in ('chat_preserved','task_preserved','saved_key_preserved','production_main_unchanged'))
        assert '20261117-k12-11-macos-x64-' in value['to_runtime'] and value['to_launcher'] == lock['launcher_build']
        resumed_materials = key == 'materials_launcher_entry'
        assert value['from_runtime'] == ('1.7.1-kaixin-20261114-materials-macos-x64-universal' if resumed_materials
                                         else lock['prior_manifest']['runtimeId'])
        bridged = key == 'oldest_launcher_entry'
        assert value['selected_archive'] == (lock['bridge']['name'] if bridged else lock['core_asset']['name'])
        if bridged or resumed_materials:
            assert value['signed_launcher_restarted'] and value['old_pid'] != value['restarted_pid']
    return dict(entries=records, fresh_picture_ui=fresh, files=files)


def fetch_partial_archive(lock, api, gh):
    meta = api('actions/artifacts/' + str(ARTIFACT['id']))
    assert meta['name'] == 'attachments-macos-x64' and not meta['expired']
    assert meta['size_in_bytes'] == ARTIFACT['bytes'] and meta['digest'] == 'sha256:' + ARTIFACT['sha256']
    job = api('actions/jobs/' + str(ARTIFACT['job_id']))
    assert job['status'] == 'completed' and job['conclusion'] == 'cancelled'
    assert job['run_id'] == ARTIFACT['run_id'] and job['head_sha'] == ARTIFACT['workflow_commit']
    assert job['name'] == 'native (macos-x64, macos-15-intel)'
    return read_completed(lock, gh('api', 'repos/' + REPO + '/actions/artifacts/' + str(ARTIFACT['id']) + '/zip'))
