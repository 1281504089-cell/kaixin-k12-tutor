"""Owner-frozen Intel7 recheck: exact existing bytes and fresh complete evidence only."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

TAG = 'student-20261117-k12-7'
SOURCE = 'fbb301fd21cf2169f834e0b548d56d201cc98365'
LOCK_FILE = 'intel-k12-7-reuse-lock.json'
STAGE = {'bytes':43033,'sha256':'10b18b0ea3d584feb4b8362e47bf590adaa06db054fe2513ebec89719b21871b','manifests':45}
REQUIRED_INPUTS = {
    'batch7_recheck.py','ci-mac-reuse.py','test_intel7_reuse.py',
    'attachment-batch.json','attachment-release.json','attachment-final-manifests.json',
    'ci_update_probe.py','ci-update-flow.cjs','ci-k12-library-ui.cjs','ci-k12-driver-selfcheck.cjs',
    'ci-materials-ui.cjs','native-materials-fixture.py','ci_picture_fresh.py','ci-picture-fresh.cjs',
    'native-k12-fixture.py','ci-fresh-smoke.mjs','ci-proxy-smoke.cjs','ci-chat-audio-ui.cjs',
    'audio-card-probe.cjs','native-audio-fixture.py','native-html-speech-diagnostic.cjs',
    'science-ui.cjs','science_seed.py','ci-turn-preview.cjs','source-manifest.json',
    'source-inventory-20261116.json','bootstrap_source.py','release_source.py',
    'launcher-manifest.json','materials-upgrade-lock.json','oldest-launcher-fingerprint.json',
    'fetchfix-tests/main-lifecycle.test.mjs','math-baseline-selfcheck.cjs','progress-read-selfcheck.cjs',
    'native-response-followup-selfcheck.cjs','native-visibility-selfcheck.cjs','native-click-followup-selfcheck.cjs',
    'update-flow-selfcheck.cjs','update-flow-disposal-selfcheck.cjs','update-flow-backup-selfcheck.cjs',
    'ci-k12-session-diagnostics-selfcheck.cjs',
}
ANCHORS = {
    'candidate_files':'59d1b1bbcbe9d3a944d77283faca574118d92b4dbb67c16453ce5385ba5afe33',
    'immutable_existing_assets':'d66e36d02b44a27204fd96569a5c06fa3fb81ccf27671f9bc3f65444e774b367',
    'prior_manifest':'2dfea7107c3e206f85f6fcd148834eb1d028409add2fa85fd090fba3ce12e5fa',
    'prior_manifest_asset':'90729ab75bfefd79f02ead9a3e1a906d79e4cec0356dc0c2eb699d66d72c084c',
    'prior_core_asset':'206b7d4543633c0937028bcbe63b4c05da5ebf8e132b110cd6fb2633a2cec272',
    'baseline_feeds':'46c637d6a2c397c56c0267a5795258f086e49f87f4577f270065bab141d1d5f8',
    'native_pages':'de5098675fbb005ff4d3207a4a7da9b218819f894bb9329e10ddaf085267f884',
}


def validate_intel7_lock(lock, frozen_raw):
    if sys.flags.optimize:
        raise RuntimeError('Intel7 QA assertions must remain enabled')
    assert lock.get('execution_frozen') is True, 'Intel7 QA recipe not yet owner-frozen; do not execute'
    expected = dict(target='macos-x64',candidate_tag=TAG,candidate_release_id=449471487,
                    source_commit=SOURCE,launcher_build='20261118-updater-4',
                    baseline_latest_id=448283800,baseline_latest_tag='student-20261117-k12-4',
                    original_native_run=44230306905,original_native_workflow_commit='0738e1ac8cfbfddb9123d097bc90598abf5827fb',
                    original_failed_job=134553415977,stage_delivery_commit='2abc0b1b1c0573a46fe5b3eb9c8d0836327e1953')
    for key,value in expected.items():
        assert lock[key] == value, 'Intel7 identity changed: '+key
    assert not any(k in lock for k in ['resume_artifact','reused_complete_entries','reused_fresh_picture_ui']), 'Intel7 reruns fresh and all four complete paths'
    assert lock['frozen_stage'] == STAGE and len(frozen_raw) == STAGE['bytes'] and hashlib.sha256(frozen_raw).hexdigest() == STAGE['sha256']
    frozen = json.loads(frozen_raw)
    assert frozen['core_commit'] == SOURCE and len(frozen['manifests']) == 45
    for key,expected in ANCHORS.items():
        value = sorted(lock[key],key=lambda r:r['name']) if key in {'candidate_files','immutable_existing_assets'} else lock[key]
        assert hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest() == expected, 'Intel7 immutable identity changed: '+key
    immutable = {r['name']:r for r in lock['immutable_existing_assets']}
    assert len(immutable) == lock['locked_existing_assets_count'] == 76 and len({r['id'] for r in immutable.values()}) == 76
    assert len(lock['candidate_files']) == 5 and len(lock['signed_runtime_assets']) == 45
    assert len({r['id'] for r in lock['signed_runtime_assets']}) == 45 and {r['name'] for r in lock['signed_runtime_assets']} == set(frozen['manifests'])
    for row in [*lock['candidate_files'],lock['core_asset'],lock['bridge'],*lock['signed_runtime_assets']]:
        assert row == immutable[row['name']] and Path(row['name']).name == row['name']
        assert row['url'] == 'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/'+TAG+'/'+row['name']
    assert lock['core_asset']['id'] == 761660480 and lock['core_asset']['bytes'] == 837565146 and lock['core_asset']['sha256'] == '4c37b944c868861ebaee446d86c94d7d045c3d81224dcee5eeb3b8876deff892'
    assert lock['bridge']['id'] == 761835544 and lock['bridge']['bytes'] == 2046865823 and lock['bridge']['sha256'] == 'a065a723b236a2548844e0d968ba27351d666857f14ce6d073a597286182e3cc'
    assert all(m['commit'] == SOURCE and m['builtAt'] == 1794971456319 and m['corePayloadSha256'] == lock['core_asset']['sha256'] for m in frozen['manifests'].values())
    included = frozen['manifests']['runtime-macos-x64-20261117-k12-7-20261112.json']
    assert lock['included_manifest'] == included and included['platform'] == 'darwin' and included['arch'] == 'x64'
    assert included['baseRuntimeId'] == lock['prior_manifest']['baseRuntimeId'] == '1.7.1-04276f68a-x64'
    assert included['archive'] == lock['core_asset']['name'] and included['sha256'] == lock['core_asset']['sha256']
    bridge = frozen['manifests']['runtime-macos-x64.json']
    assert not bridge.get('baseRuntimeId') and bridge['archive'] == lock['bridge']['name'] and bridge['sha256'] == lock['bridge']['sha256']
    assert lock['public_key_sha256'] == 'aed6f122112b2dcd78e98e9811c48dcaa779d0ab7a9150acadca36255603e062'
    assert lock['picture_count'] == 294 and lock['picture_manifest_sha256'] == '3983e0c365daef3e15e3352323e1b5ec19d7be42de924744094c20567477cd10'
    assert lock['runtime_exclusion_count'] == 17 and lock['runtime_exclusion_kinds'] == {'bad_asset_sha256':16,'bad_payload_sha256':1}
    assert lock['runtime_exclusion_ledger_sha256'] == 'd83de01f607be564213c007a6613ca81b3adea2821ef1de83147a298d3f71522'
    assert lock['bank_revision'] == '26065ed727a40eab0e29711fd52c00233848e5cd2dd0baabd7f20fff2700c4ee'
    assert lock['launcher_tests'] == {'tests':83,'pass':83,'fail':0,'skipped':0}
    assert REQUIRED_INPUTS <= set(lock['recipe_inputs_sha256'])
    for name,digest in lock['recipe_inputs_sha256'].items():
        assert not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name
        assert isinstance(digest,str) and re.fullmatch(r'[a-f0-9]{64}',digest), 'Owner must freeze final QA input: '+name
    return frozen


def validate_intel7_execution(root, lock_raw, env=None):
    if sys.flags.optimize:
        raise RuntimeError('Intel7 QA assertions must remain enabled')
    env = os.environ if env is None else env
    lock = json.loads(lock_raw)
    assert lock.get('execution_frozen') is True, 'Intel7 QA recipe not yet owner-frozen; do not execute'
    assert re.fullmatch(r'[a-f0-9]{64}',env.get('KX_REUSE_LOCK_SHA256','')) and hashlib.sha256(lock_raw).hexdigest() == env['KX_REUSE_LOCK_SHA256'], 'Owner-frozen raw lock SHA required'
    assert env.get('GITHUB_REF_NAME','').startswith('codex/k12-intel7-reverify-20261118-')
    assert int(env['GITHUB_RUN_ID']) != 44230306905 and re.fullmatch(r'[a-f0-9]{40}',env['GITHUB_SHA'])
    assert not any((root/name).exists() for name in ['macos-x64-reuse-work','prior-update','materials-baseline','student-source','launcher-tests-macos-x64']), 'Use a new disposable directory; never resume accepted requests'
