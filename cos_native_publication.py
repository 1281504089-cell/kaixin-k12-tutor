"""Confirm native route reports exercise the release's signed installer and core."""
import json


def validate_cos_native(evidence, batch, target, installers, cos_objects):
    report = json.loads((evidence / 'COS-NATIVE-VERIFICATION.json').read_bytes())
    run = batch['cos_native_run']
    assert report['target'] == target and report['source_commit'] == batch['core_commit']
    assert report['tag'] == batch['tag'] and report['launcher'] == batch['launcher_build']
    assert report['native_run'] == run['run_id'] and report['workflow_commit'] == run['workflow_commit']
    assert report['tested_candidate_installer']
    downloaded = report['installer_downloads']
    assert all(row['anonymous_download'] and row['sha256_verified'] for row in downloaded)
    assert {(row['name'],row['bytes'],row['sha256']) for row in downloaded} == {
        (row['file'],row['bytes'],row['sha256']) for row in installers}
    setup = json.loads((evidence / 'actual-candidate-install/app.json').read_bytes())
    native = {'windows-x64':('win32','x64'), 'macos-x64':('darwin','x64'), 'macos-arm64':('darwin','arm64')}[target]
    assert (setup['native_platform'], setup['native_arch']) == native
    assert setup['fresh_profile'] and setup['current_core_included'] and setup['core_commit'] == batch['core_commit']
    assert not setup['real_keys_used']
    alias = f"runtime-{target}-{batch['tag'].removeprefix('student-')}-20261112.json"
    signed = batch['manifests'][alias]
    mirror = cos_objects['cos_mirror'].split('/', 3)[2]
    cos_digest = next(row['sha256'] for row in cos_objects['manifests'] if row['name'] == alias)
    assert set(report['scenarios']) == {'migration','cos','fallback'}
    for scenario, result in report['scenarios'].items():
        assert result == json.loads((evidence / scenario / f'cos-{scenario}.json').read_bytes())
        assert (result['native_platform'],result['native_arch']) == native
        assert result['entry'] == 'renderer IPC desktop:check-release'
        assert result['actual_download_install_backup_restart'] == 'passed' and result['transaction'] == 'complete'
        assert all(result[key] for key in ['production_main_unchanged','check_again_current','chat_preserved','task_preserved','saved_key_preserved'])
        assert result['to_runtime'] == signed['runtimeId'] and result['selected_base_runtime'] == signed['baseRuntimeId']
        assert result['selected_archive'] == signed['archive'] and result['to_launcher'] == batch['launcher_build']
        assert result['old_pid'] != result['restarted_pid']
        receipt = result['cos_native']
        assert receipt['scenario'] == scenario and receipt['after_reopen_archive_requests'] == 0
        assert receipt['launcher_and_runtime_signatures_verified'] and receipt['started_launcher'] == result['from_launcher']
        assert result['from_launcher'] == ('20261118-updater-5' if scenario=='migration' else batch['launcher_build'])
        assert bool(result['signed_launcher_restarted']) == (scenario=='migration')
        assert receipt['precheck_tag'] == (None if scenario=='cos' else batch['tag'])
        archive = receipt['archive']
        assert archive in receipt['events'] and archive['asset'] == signed['archive'] and archive['sha256'] == signed['sha256']
        assert archive['status'] == 200 and not archive['cache'] and archive['bytes'] == batch['archives'][signed['archive']]['bytes']
        if scenario == 'cos':
            assert archive['route'] == 'cos' and archive['host'] == mirror
            assert not any(row['kind']=='archive-request' and row['route']=='github' for row in receipt['events'])
        else:
            assert archive['route'] == 'github' and archive['host'] in {'github.com','api.github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}
        if scenario != 'migration':
            before = receipt['events'][:receipt['events'].index(archive)]
            assert any(row['kind']=='manifest-body' and row['asset']==alias and row['host']==mirror and row['sha256']==cos_digest for row in before)
            assert any(row['kind']=='forced-cos-archive-failure' for row in before) == (scenario=='fallback')
    return {'native_run':run['run_id'], 'workflow_commit':run['workflow_commit'],
            'scenarios':{name:row['cos_native']['archive'] for name,row in report['scenarios'].items()},
            'exact_candidate_install':True}
