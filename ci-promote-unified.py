#!/usr/bin/env python3
"""Promote one approved Resource-5 GitHub prerelease using independently checked evidence."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import gzip
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REPO = '1281504089-cell/kaixin-k12-tutor'
TAG = 'student-20261121-resource-5'
COS_PRIOR = '7bcb3359941fa09dd944d25b70a45bef6ee5ceee'
GITHUB_PRIOR = '64ec3957abd504086777df87becf3851f5908aed'
PRIOR_TAG = 'student-20261121-diagram-1'
NATIVE_BRANCH = 'codex/k12-native-reverify-20261117-resource-5'
TARGETS = ('macos-x64', 'macos-arm64', 'windows-x64')
DEFAULTS = {f'runtime-{target}.json': target for target in TARGETS}
COS = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
DOWNLOAD = f'https://github.com/{REPO}/releases/download/'
RAW = f'https://raw.githubusercontent.com/{REPO}/'
API = f'https://api.github.com/repos/{REPO}/'
HISTORY = 'core-updates-history-20261121-resource-5'
CORE = 'kaixin-core-20261121-resource-5.tar.gz'
DELTA = 'kaixin-core-delta-resource-4-to-resource-5.tar.gz'
PATCH = 'source-from-diagram-1.patch'
PUBLIC_RECEIPT = 'PUBLICATION-RECEIPT.json'
WINDOWS_STEM = 'Kaixin-Super-Scholar-Windows-v1.7.1-'
WINDOWS_SETUP = WINDOWS_STEM + 'Setup.exe'
# Immutable Windows inputs from diagram-1's verified native installer plan.
WINDOWS_BASELINE = {
    WINDOWS_STEM + 'Runtime.001': {'bytes': 1992294400, 'sha256': '529ab17c901fd0efc15cd10cbdd7530e3356423cfbd0eae92859d226607501c6'},
    WINDOWS_STEM + 'Runtime.002': {'bytes': 1992294400, 'sha256': '8ea3c897e0401228b517755c1e39dcc4071e38585eeed08aecd880ec5dea0142'},
    WINDOWS_STEM + 'Runtime.003': {'bytes': 1992294400, 'sha256': '8ac6f062f60c88945cca94040b0ed085c18a6b4d62c9c5b7b21697b360ddf13d'},
    WINDOWS_STEM + 'Runtime.004': {'bytes': 1005564586, 'sha256': '8fd3f08fc3cccc5f751d508bb197de53cd24bbc2f03561171416cf186c6c1034'},
    WINDOWS_SETUP: {'bytes': 1064178950, 'sha256': '803428b285222064c9ac2922bdd1236bd929bf8a53b757726b9002c6671316cb'},
}
LOCAL_CHECKS = {'drag_dynamic', 'dynamic_layout', 'textbook_jump', 'single_verified_question',
                'history_reopen', 'alternate_phrasing_and_topic', 'non_gallery_diagram', 'fast_new_chat_completion'}
HOSTS = {urlparse(COS).hostname, 'raw.githubusercontent.com', 'github.com', 'api.github.com',
         'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}
SIGNATURE_CHECK = '''
const fs = require('node:fs');
const {verify} = require('node:crypto');
const key = `-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA8QpxFW2KekaGdPipMxCi9UgADS4GG+/4T6BDxcyVa38=
-----END PUBLIC KEY-----`;
for (const doc of JSON.parse(fs.readFileSync(0,'utf8'))) {
  const {signature, ...signed} = doc;
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(signed).sort(([a],[b]) => a.localeCompare(b))));
  if (!verify(null, Buffer.from(canonical), key, Buffer.from(signature ?? '', 'base64'))) {
    throw new Error(`Invalid desktop update signature for ${doc.runtimeId}`);
  }
}
'''


def digest(raw):
    return sha256(raw).hexdigest()


def size_hash(raw):
    return {'bytes': len(raw), 'sha256': digest(raw)}


def expect_hash(value, length=64):
    assert re.fullmatch(fr'[a-f0-9]{{{length}}}', value), value


def expect_file(name):
    assert re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]*', name), name


def shape(row):
    assert type(row['bytes']) is int and row['bytes'] > 0, row
    expect_hash(row['sha256'])
    return {key: row[key] for key in ('bytes', 'sha256')}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def gh(*args, timeout=120):
    return subprocess.check_output(['gh', *map(str, args)], timeout=timeout, env={**os.environ, 'GH_REPO': REPO})


def api(route):
    return json.loads(gh('api', f'repos/{REPO}/{route}'))


def open_public(url, *, timeout=35, headers=None):
    parsed = urlparse(url)
    assert parsed.scheme == 'https' and parsed.netloc in HOSTS, url
    headers = {'User-Agent': 'Kaixin-Resource-5-verification', 'Accept-Encoding': 'identity', **(headers or {})}
    response = urlopen(Request(url, headers=headers), timeout=timeout)
    final = urlparse(response.geturl())
    if final.scheme != 'https' or final.netloc not in HOSTS:
        response.close()
        raise ValueError('Unexpected download host: ' + final.netloc)
    return response


def get(url, limit=250_000):
    for attempt in range(3):
        try:
            with open_public(url) as response:
                raw = response.read(limit + 1)
            assert len(raw) <= limit, url
            return raw
        except (TimeoutError, ConnectionError, URLError, http.client.HTTPException) as error:
            if attempt == 2 or (isinstance(error, HTTPError) and error.code < 500 and error.code != 429):
                raise
            time.sleep(attempt + 1)
    raise RuntimeError('Readback retries exhausted')


def acquire_pinned(url, expected, suffix):
    expect_hash(expected)
    assert re.fullmatch(re.escape(RAW) + '[a-f0-9]{40}/releases/' + re.escape(suffix), url), url
    raw = get(url)
    assert digest(raw) == expected, url
    return json.loads(raw)


def inventory(release):
    result = {row['name']: row for row in release['assets']}
    assert len(result) == len(release['assets'])
    return result


def asset_matches(remote, expected):
    return remote['state'] == 'uploaded' and remote['size'] == expected['bytes'] and remote['digest'] == 'sha256:' + expected['sha256']


def require_assets(rows, expected):
    for name, row in expected.items():
        assert name in rows and asset_matches(rows[name], row), name


def read_asset(tag, name, row, limit=250_000):
    expect_file(name)
    assert row['name'] == name and row['state'] == 'uploaded', name
    content = get(f'{DOWNLOAD}{tag}/{quote(name)}?resource5_readback={time.time_ns()}', limit)
    assert asset_matches(row, size_hash(content)), name
    return content


def tag_commit(tag, read=api):
    obj = read('git/ref/tags/' + tag)['object']
    for _ in range(3):
        if obj['type'] == 'commit':
            expect_hash(obj['sha'], 40)
            return obj['sha']
        assert obj['type'] == 'tag', obj
        obj = read('git/tags/' + obj['sha'])['object']
    raise ValueError('Unable to resolve release tag ' + tag)


def signed_target(doc, target):
    os_name, arch = target.split('-')
    assert doc['formatVersion'] == doc['protocolVersion'] == 1
    assert (doc['platform'], doc['arch']) == (('darwin' if os_name == 'macos' else 'win32'), arch)
    assert re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}', doc['runtimeId'])
    assert type(doc['builtAt']) is int and doc['builtAt'] > 0
    expect_file(doc['archive'])
    expect_hash(doc['sha256'])


def verify_signatures(documents):
    subprocess.run(['node', '-e', SIGNATURE_CHECK], input=json.dumps(list(documents)).encode(), check=True, timeout=25)


def validate_stage(lock):
    assert lock['tag'] == TAG and lock['source_commit'] not in {GITHUB_PRIOR, COS_PRIOR}
    expect_hash(lock['source_commit'], 40)
    expect_hash(lock['source_carrier'], 40)
    expect_hash(lock['core_sha256'])
    assert set(lock['prior']) == set(TARGETS)
    assert set(lock['archives']) == {CORE, DELTA, *(f'kaixin-bridge-20261121-resource-5-{target}.tar.gz' for target in TARGETS)}
    assert lock['archives'][CORE]['sha256'] == lock['core_sha256']
    for target, doc in lock['prior'].items():
        assert doc['commit'] == COS_PRIOR
        signed_target(doc, target)
        expect_hash(doc['corePayloadSha256'])
    for name, row in (lock['feeds'] | lock['archives']).items():
        expect_file(name)
        shape(row)
    verify_signatures(lock['prior'].values())


def validate_manifests(lock, bodies):
    documents = {name: json.loads(raw) for name, raw in bodies.items()}
    assert set(documents) == set(lock['feeds'])
    used_feeds = set(DEFAULTS)
    for name, target in DEFAULTS.items():
        root = documents[name]
        signed_target(root, target)
        assert root['commit'] == lock['source_commit'] and root['corePayloadSha256'] == lock['core_sha256']
        assert root['builtAt'] > lock['prior'][target]['builtAt'] and 'baseRuntimeId' not in root
        assert root['archive'] == f'kaixin-bridge-20261121-resource-5-{target}.tar.gz'
        assert root['sha256'] == lock['archives'][root['archive']]['sha256']
        alias = lock['feeds'][name]['cos_name']
        assert alias == f'runtime-{target}-20261121-resource-5-candidate.json' and bodies[alias] == bodies[name]
        used_feeds.add(alias)
        bases = set()
        for entry in root['compatibleBaseManifests']:
            base, file = entry['baseRuntimeId'], entry['file']
            assert re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.+_-]{0,100}', base) and base not in bases
            assert file == f'runtime-{target}-20261121-resource-5-base-{digest(base.encode())[:12]}.json'
            assert file not in used_feeds, file
            child = documents[file]
            signed_target(child, target)
            assert child['baseRuntimeId'] == base and child['runtimeId'] != base
            for field in ('commit', 'builtAt', 'corePayloadSha256', 'coreVersion'):
                assert child[field] == root[field], (file, field)
            assert child['archive'] == CORE and child['sha256'] == lock['core_sha256']
            delta = child['coreDelta']
            assert delta['formatVersion'] == 1 and delta['archive'] == DELTA
            assert delta['fromCoreSha256'] == lock['prior'][target]['corePayloadSha256']
            assert delta['toCoreSha256'] == child['sha256'] and shape(delta) == shape(lock['archives'][DELTA])
            bases.add(base)
            used_feeds.add(file)
        prior = lock['prior'][target]
        assert {prior['runtimeId'], *(row['baseRuntimeId'] for row in prior['compatibleBaseManifests'])} <= bases
    assert used_feeds == set(documents), used_feeds ^ set(documents)
    verify_signatures(documents.values())
    return documents


def read_stable_cos(lock, rows):
    def read_feed(item):
        name, wanted = item
        raw = get(COS + name)
        assert size_hash(raw) == shape(wanted), name
        assert read_asset(TAG, name, rows[name]) == raw, name
        return name, raw

    def anchor(item):
        name, wanted = item
        receipt_name = name + '.cos-receipt.json'
        proof = json.loads(read_asset(TAG, receipt_name, rows[receipt_name]))
        url = COS + name
        anchor_url = proof['url']
        parsed = urlparse(anchor_url)
        assert anchor_url.split('?', 1)[0] == url and not parsed.fragment, name
        assert shape(proof) == shape(wanted), name
        assert proof.get('verified') is True or isinstance(proof.get('full_verified_at'), str), name
        expected = {'version': proof.get('version') or proof.get('version_id'), 'etag': proof.get('etag'),
                    'last_modified': proof.get('last_modified'), 'crc64': proof.get('crc64')}
        version = expected['version']
        if version and version.lower() == 'null':
            version = expected['version'] = None
        assert version or (expected['etag'] and expected['last_modified']), name
        headers = {'Range': 'bytes=0-0'}
        if expected['etag']:
            headers['If-Match'] = expected['etag']
        with open_public(url, headers=headers) as response:
            assert response.status == 206 and response.headers.get('Content-Range') == f'bytes 0-0/{wanted["bytes"]}', name
            assert response.read(2).hex() == proof['first_byte'] and len(proof['first_byte']) == 2, name
            actual = {'version': response.headers.get('x-cos-version-id'), 'etag': response.headers.get('etag'),
                      'last_modified': response.headers.get('last-modified'), 'crc64': response.headers.get('x-cos-hash-crc64ecma')}
            if actual['version'] and actual['version'].lower() == 'null':
                actual['version'] = None
            assert all(not expected[key] or actual[key] == expected[key] for key in ('version', 'etag', 'last_modified')), name
        return name, {'receipt': receipt_name, 'receipt_sha256': rows[receipt_name]['digest'].removeprefix('sha256:'),
                      'verified_range_bytes': 1, **expected}

    with ThreadPoolExecutor(max_workers=6) as pool:
        bodies = dict(pool.map(read_feed, lock['feeds'].items()))
        anchors = dict(pool.map(anchor, lock['archives'].items()))
    return validate_manifests(lock, bodies), anchors, bodies


def check_local_proof(approval, lock, documents, stage_hash, release_id):
    assert approval['approved'] is True
    assert approval['tag'] == TAG and approval['source_commit'] == lock['source_commit']
    assert approval['core_sha256'] == lock['core_sha256'] and approval['stage_sha256'] == stage_hash
    assert approval['stage_release_id'] == release_id
    local = approval['local_intel']
    assert local['source_commit'] == lock['source_commit'] and local['target'] == 'macos-x64'
    for field in ('passed', 'signed_restart', 'application_ipc_update', 'check_again_current', 'isolated_profile'):
        assert local[field] is True, field
    assert local['transaction_phase'] == 'complete' and local['transfer_origin'] == 'loopback-of-staged-artifacts'
    prior = lock['prior']['macos-x64']
    expect_hash(local['learning_memory_sha256'])
    matching = [name for name, row in documents.items() if row['runtimeId'] == local['to'] and row.get('baseRuntimeId')]
    assert len(matching) == 1 and shape(local['signed_manifest']) == shape(lock['feeds'][matching[0]])
    base = documents[matching[0]]['baseRuntimeId']
    if base == prior['runtimeId']:
        assert local['from'] == base
    else:
        old_ref, = (r for r in prior['compatibleBaseManifests'] if r['baseRuntimeId'] == base)
        old_name = old_ref['file'].removesuffix('.json')
        _, suffix = old_name.rsplit('-base-', 1)
        assert suffix == digest(base.encode())[:12]
        assert prior['runtimeId'].endswith('-universal')
        assert local['from'] == prior['runtimeId'].removesuffix('-universal') + '-base-' + suffix
    assert shape(local['network']) == shape(lock['archives'][DELTA])
    workflow = approval['local_workflow']
    assert workflow['passed'] is True and workflow['source_commit'] == lock['source_commit']
    assert LOCAL_CHECKS <= workflow['checks'].keys() and all(workflow['checks'][name] is True for name in LOCAL_CHECKS)
    expect_hash(workflow['receipt_sha256'])


def evidence_names(target):
    names = [f'verification-{target}.json', 'fallback.json', 'online-cos.json']
    if target == 'macos-x64':
        names.append('online-github.json')
    return names


def evidence_asset_name(target, name):
    return name if name == f'verification-{target}.json' else f'{target}-{name}'


def native_evidence(lock, documents, target, run, payload):
    installed = payload[f'verification-{target}.json']
    assert installed['target'] == target and installed['native_install'] == 'passed'
    assert installed['core_commit'] == lock['source_commit'] and installed['core_sha256'] == lock['core_sha256']
    assert installed['run_id'] == run['id'] and installed['workflow_commit'] == run['sha']
    drawing = installed['drawing_catalog']
    assert drawing['passed'] is True and len(drawing['feedback']) == 6
    files = {row['file']: shape(row) for row in installed['full_files']}
    assert 4 <= len(files) <= 5 and len(files) == len(installed['full_files']), target
    for name in files:
        expect_file(name)
    if target == 'windows-x64':
        assert files.keys() == WINDOWS_BASELINE.keys(), 'Unexpected Windows installer file names'
        assert installed['release'] == lock['tag'] and installed['input_release'] == PRIOR_TAG
        downloads = installed['download_files']
        assert len(downloads) == len(WINDOWS_BASELINE)
        assert all(row['sha256_verified'] is True and row['anonymous_download'] is True for row in downloads)
        assert {row['name']: shape(row) for row in downloads} == WINDOWS_BASELINE
        assert all(installed['installer_reuse'][name] is True for name in (
            'existing_installers_repackaged', 'native_seed_unchanged', 'windows_runtime_parts_reused',
        ))
        assert all(files[name] == baseline for name, baseline in WINDOWS_BASELINE.items() if name != WINDOWS_SETUP)
        assert files[WINDOWS_SETUP]['sha256'] != WINDOWS_BASELINE[WINDOWS_SETUP]['sha256'], 'Windows Setup was not rebuilt'
        smoke = installed['native_smoke']
        assert (smoke['native_platform'], smoke['native_arch'], smoke['core_commit']) == ('win32', 'x64', lock['source_commit'])
        assert smoke['fresh_profile'] is True and smoke['current_core_included'] is True
    else:
        brand = 'Apple-Silicon' if target == 'macos-arm64' else 'Intel'
        prefix = f'Kaixin-Super-Scholar-MacOS-{brand}-'
        assert all(name.startswith(prefix) and '20261121-resource-5' in name for name in files)
        assert sum(name.endswith('-part.dmg') for name in files) == 1
    fallback = payload['fallback.json']
    root = documents[f'runtime-{target}.json']
    assert fallback['passed'] is True and fallback['target'] == target and fallback['commit'] == lock['source_commit']
    assert fallback['core_sha256'] == lock['core_sha256'] and fallback['runtime'] == root['runtimeId']
    assert (fallback['archive'], fallback['archive_sha256']) == (root['archive'], root['sha256'])
    for channel in (('cos', 'github') if target == 'macos-x64' else ('cos',)):
        online = payload[f'online-{channel}.json']
        assert (online['target'], online['channel'], online['commit']) == (target, channel, lock['source_commit'])
        assert online['passed'] is online['restarted'] is online['checked_again'] is True
        assert online['memory'] == digest(b'signed update synthetic memory')
        assert online['delta']['name'] == DELTA and shape(online['delta']) == shape(lock['archives'][DELTA])
        name = online['manifest']['name']
        assert name in {row['file'] for row in root['compatibleBaseManifests']}
        assert shape(online['manifest']) == shape(lock['feeds'][name])
        cos_attempts = [row for row in online['attempts'] if row['origin'] == 'https://' + urlparse(COS).netloc]
        assert cos_attempts, (target, channel)
    return files


def read_native(work, approval, lock, documents, staged):
    runs = approval['native_runs']
    assert set(runs) == set(TARGETS)
    all_files = {}
    reports = {}
    for target, expected in runs.items():
        run_id = expected['id']
        assert type(run_id) is int and run_id > 0
        expect_hash(expected['sha'], 40)
        assert re.fullmatch(r'\.github/workflows/[a-zA-Z0-9._-]+\.ya?ml', expected['workflow_path'])
        run = api(f'actions/runs/{run_id}')
        assert run['head_sha'] == expected['sha'] and run['head_branch'] == NATIVE_BRANCH
        assert run['path'].split('@', 1)[0] == expected['workflow_path'] and run['head_repository']['full_name'] == REPO
        assert run['status'] == 'completed'
        jobs = api(f'actions/runs/{run_id}/attempts/{run["run_attempt"]}/jobs?per_page=100')['jobs']
        job, = (row for row in jobs if f'({target},' in row['name'])
        assert job['status'] == 'completed' and job['conclusion'] == 'success', target
        folder = work / f'evidence-{target}'
        gh('run', 'download', run_id, '--name', 'attachments-' + target, '--dir', folder, timeout=180)
        raw_reports = {name: (folder / name).read_bytes() for name in evidence_names(target)}
        payload = {name: json.loads(raw) for name, raw in raw_reports.items()}
        installers = native_evidence(lock, documents, target, expected, payload)
        assert not (set(all_files) & set(installers))
        require_assets(staged, installers)
        all_files.update(installers)
        reports.update({evidence_asset_name(target, name): raw for name, raw in raw_reports.items()})
    return all_files, reports


def ensure_asset(tag, work, name, body):
    expect_file(name)
    wanted = size_hash(body)
    rows = inventory(api('releases/tags/' + tag))
    if name not in rows:
        path = work / name
        path.write_bytes(body)
        gh('release', 'upload', tag, path)
        rows = inventory(api('releases/tags/' + tag))
    require_assets(rows, {name: wanted})
    assert read_asset(tag, name, rows[name], max(250_000, wanted['bytes'])) == body
    return wanted


def previous_defaults(lock, documents, staged, live):
    """Identify exact old descriptors even during retry after an interrupted default switch."""
    saved = {}
    protected = set(DEFAULTS)
    old_docs = []
    for name, target in DEFAULTS.items():
        backup = 'previous-' + name
        current_raw = read_asset('core-updates', name, live[name])
        current = json.loads(current_raw)
        if current['commit'] == lock['source_commit']:
            assert current == documents[name], name
            raw = read_asset(TAG, backup, staged[backup])
        else:
            assert current['commit'] == GITHUB_PRIOR, name
            raw = current_raw
            if backup in staged:
                assert read_asset(TAG, backup, staged[backup]) == raw, name
        doc = json.loads(raw)
        assert doc['commit'] == GITHUB_PRIOR and documents[name]['builtAt'] > doc['builtAt'], name
        signed_target(doc, target)
        saved[name] = raw
        old_docs.append(doc)
        protected.add(doc['archive'])
        assert live[doc['archive']]['digest'] == 'sha256:' + doc['sha256'], name
        for ref in doc['compatibleBaseManifests']:
            file = ref['file']
            expect_file(file)
            child = json.loads(read_asset('core-updates', file, live[file]))
            signed_target(child, target)
            assert child['commit'] == GITHUB_PRIOR and child['baseRuntimeId'] == ref['baseRuntimeId'], file
            assert child['sha256'] == live[child['archive']]['digest'].removeprefix('sha256:'), file
            old_docs.append(child)
            protected.update((file, child['archive']))
            if 'coreDelta' in child:
                delta = child['coreDelta']
                assert asset_matches(live[delta['archive']], shape(delta)), file
                protected.add(delta['archive'])
        assert {doc['runtimeId'], *(r['baseRuntimeId'] for r in doc['compatibleBaseManifests'])} <= {
            r['baseRuntimeId'] for r in documents[name]['compatibleBaseManifests']}, target
    verify_signatures(old_docs)
    return saved, protected


def build_history_plan(source_commit, live, pending, protected):
    """Use exact signed, superseded compatibility descriptors to make room when needed."""
    excess = len(set(live) | set(pending)) - 1000
    if excess <= 0:
        return {}
    count = excess + 8
    assert count <= 100, count
    eligible = re.compile(r'runtime-(macos-x64|macos-arm64|windows-x64)-20261117-k12-(?:1|2|4|7|8)-base-[a-f0-9]{12}\.json')
    names = sorted(name for name in live if name not in protected and name not in pending and eligible.fullmatch(name))
    assert len(names) >= count, 'Insufficient safe inactive compatibility manifests to archive'
    selection = {}
    docs = []
    for name in names[:count]:
        body = read_asset('core-updates', name, live[name])
        doc = json.loads(body)
        signed_target(doc, eligible.fullmatch(name)[1])
        assert doc['commit'] not in {source_commit, GITHUB_PRIOR, COS_PRIOR}
        assert 'baseRuntimeId' in doc and not doc.get('compatibleBaseManifests')
        docs.append(doc)
        selection[name] = body
    verify_signatures(docs)
    return selection


def ensure_history(work, lock, live, selection):
    old_record = work / 'resource5-history.json'
    if not selection:
        try:
            history = inventory(api('releases/tags/' + HISTORY))
        except subprocess.CalledProcessError:
            return {}
        if old_record.name in history:
            return json.loads(read_asset(HISTORY, old_record.name, history[old_record.name]))
        return {}
    try:
        history = inventory(api('releases/tags/' + HISTORY))
    except subprocess.CalledProcessError:
        gh('release', 'create', HISTORY, '--target', lock['source_carrier'], '--latest=false',
           '--title', 'Historical desktop update descriptors',
           '--notes', 'Byte-identical signed compatibility descriptors relocated from the stable update release.')
        history = {}
    manifest = {}
    if old_record.name in history:
        manifest = json.loads(read_asset(HISTORY, old_record.name, history[old_record.name]))
    new_entries = {name: {'previous_id': live[name]['id'], **size_hash(body)} for name, body in selection.items()}
    for name, row in new_entries.items():
        assert name not in manifest or manifest[name] == row, name
        ensure_asset(HISTORY, work, name, selection[name])
    manifest.update(new_entries)
    write(old_record, manifest)
    gh('release', 'upload', HISTORY, old_record, '--clobber')
    archived = inventory(api('releases/tags/' + HISTORY))
    assert read_asset(HISTORY, old_record.name, archived[old_record.name]) == old_record.read_bytes()
    require_assets(archived, manifest)
    for name, row in new_entries.items():
        current = api(f'releases/assets/{row["previous_id"]}')
        assert current['name'] == name and asset_matches(current, row), name
        assert read_asset(HISTORY, name, archived[name]) == selection[name], name
        gh('api', '--method', 'DELETE', f'repos/{REPO}/releases/assets/{current["id"]}')
    return manifest


def copy_archive(work, name, wanted):
    assert wanted['bytes'] < 2 * 1024 ** 3, 'GitHub single-asset size limit'
    path = work / name
    count = 0
    hash_stream = sha256()
    with open_public(f'{DOWNLOAD}{TAG}/{name}', timeout=100) as response, path.open('xb') as output:
        while block := response.read(8 << 20):
            count += len(block)
            assert count <= wanted['bytes'], name
            hash_stream.update(block)
            output.write(block)
    assert (count, hash_stream.hexdigest()) == (wanted['bytes'], wanted['sha256']), name
    gh('release', 'upload', 'core-updates', path, timeout=1250)
    path.unlink()


def promote(config_url, stage_hash, approval_url, approval_hash, *, verify_only=True):
    lock = acquire_pinned(config_url, stage_hash, f'{TAG}-stage.json')
    approval = acquire_pinned(approval_url, approval_hash, f'{TAG}-activation.json')
    validate_stage(lock)
    latest = api('releases/latest')
    assert latest['tag_name'] == PRIOR_TAG and latest['id'] == 453559695
    candidate = api('releases/tags/' + TAG)
    assert candidate['target_commitish'] == lock['source_carrier'] == tag_commit(TAG)
    assert candidate['prerelease'] and not candidate['draft']
    staged = inventory(candidate)
    require_assets(staged, lock['archives'] | lock['feeds'])
    documents, anchors, bodies = read_stable_cos(lock, staged)
    check_local_proof(approval, lock, documents, stage_hash, candidate['id'])
    source = json.loads(get(RAW + lock['source_carrier'] + f'/releases/{TAG}.json', 12_000_000))
    assert source['source_commit'] == lock['source_commit'] and source['base_commit'] == GITHUB_PRIOR and source['base_tag'] == PRIOR_TAG
    assert source['predecessor'] == COS_PRIOR and shape(source['cos_core']) == shape(lock['archives'][CORE])
    expect_hash(source['source_tree'], 40)
    patch = source['patch']
    assert patch['file'] == PATCH and patch['encoding'] == 'gzip+base64'
    patch_bytes = gzip.decompress(base64.b64decode(patch['payload'], validate=True))
    assert digest(patch_bytes) == patch['sha256'] and patch_bytes.startswith(b'diff --git ')
    active = inventory(api('releases/tags/core-updates'))
    previous, protected = previous_defaults(lock, documents, staged, active)
    pending = {name: item for name, item in (lock['archives'] | lock['feeds']).items()
               if name not in DEFAULTS and not name.endswith('-candidate.json')}
    require_assets(active, {name: item for name, item in pending.items() if name in active})
    with TemporaryDirectory(prefix='kaixin-resource5-') as folder:
        work = Path(folder)
        installers, reports = read_native(work, approval, lock, documents, staged)
        history = build_history_plan(lock['source_commit'], active, pending, protected | set(pending))
        print('Resource-5 gates passed:', len(installers), 'installer assets,', len(bodies), 'signed COS feeds,',
              len(anchors), 'anchored COS archives,', len(history), 'history entries to relocate', flush=True)
        if verify_only:
            return
        assert api('releases/latest')['id'] == latest['id']
        patch_asset = ensure_asset(TAG, work, PATCH, patch_bytes)
        report_assets = {name: ensure_asset(TAG, work, name, raw) for name, raw in reports.items()}
        backup_assets = {name: ensure_asset(TAG, work, 'previous-' + name, raw) for name, raw in previous.items()}
        saved_history = ensure_history(work, lock, active, history)
        active = inventory(api('releases/tags/core-updates'))
        assert len(set(active) | set(pending)) <= 1000
        for name in pending.keys() - active.keys() - lock['archives'].keys():
            path = work / name
            path.write_bytes(bodies[name])
            gh('release', 'upload', 'core-updates', path)
        missing_archives = [(name, row) for name, row in lock['archives'].items() if name not in active]
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda item: copy_archive(work, *item), missing_archives))
        require_assets(inventory(api('releases/tags/core-updates')), pending)
        assert api('releases/latest')['id'] == latest['id']

        try:
            for name in DEFAULTS:
                active = inventory(api('releases/tags/core-updates'))
                if not asset_matches(active[name], lock['feeds'][name]):
                    assert asset_matches(active[name], size_hash(previous[name])), name
                    path = work / name
                    path.write_bytes(bodies[name])
                    gh('release', 'upload', 'core-updates', path, '--clobber')
                    active = inventory(api('releases/tags/core-updates'))
                assert read_asset('core-updates', name, active[name]) == bodies[name], name
            proof = {'published': True, 'tag': TAG, 'release_id': candidate['id'], 'source_commit': lock['source_commit'],
                     'release_repository_commit': lock['source_carrier'], 'core_sha256': lock['core_sha256'],
                     'stage_sha256': stage_hash, 'approval_sha256': approval_hash, 'source_tree': source['source_tree'],
                     'installers': installers, 'reports': report_assets, 'native_runs': approval['native_runs'],
                     'local_workflow': approval['local_workflow'], 'cos_anchors': anchors,
                     'previous_defaults': backup_assets, 'stable_assets': len(pending) + len(DEFAULTS),
                     'preserved_history': saved_history, 'patch': patch_asset}
            public_receipt = work / PUBLIC_RECEIPT
            write(public_receipt, proof)
            ensure_asset(TAG, work, PUBLIC_RECEIPT, public_receipt.read_bytes())
            notes = work / 'release-notes.md'
            notes.write_text('## 桌面更新\n\n'
                             '- 静态图、交互图、对话参考图和主动配图统一先查已核对图库。补充小学到高中的图例和交互模板，包括空间向量、角、函数和运动。未命中时保留题设，通过本机构图或结构化绘图，并核对实际输出。\n'
                             '- 动态图适配聊天、右栏和全屏，完整显示表达式。滑块在画布上方，保留范围、步长和初值。完全给定的参数函数可在本机生成。新对话的快图完成后直接显示，无需刷新。\n'
                             '- 教材蓝色引用打开实际 PDF 页。重开历史可以继续查看教材、配图、原题和答题记录。\n'
                             '- 学生开口要题时承接当前知识点，按授权长期资料、题库、教材顺序查找。普通共享 1 秒，明确查找最长 30 秒。各题型都参与检索，合适的非选择题可改编选择题并标出原出处。保留原题及手写要求，查完无匹配才原创。\n'
                             '- Intel Mac、Apple 芯片 Mac 和 Windows 已安装用户在应用内点「检查更新」。默认 COS，旧核心匹配时用签名增量，并提供签名完整包回退。升级保留学习记录。\n'
                             '- 首次安装从 GitHub 下载对应平台的全部分卷，放入同一目录。Mac 打开以 -part.dmg 结尾的首卷，Windows 运行 Setup.exe。若所在网络无法访问 GitHub，需要开 VPN。\n\n'
                             f"冻结学习核心 {lock['source_commit']}\n", encoding='utf-8')
            gh('release', 'edit', TAG, '--notes-file', notes, '--prerelease=false', '--latest')
        except BaseException:
            final = api('releases/latest')
            if final['id'] != candidate['id']:
                restore_paths = []
                for name, raw in previous.items():
                    path = work / name
                    path.write_bytes(raw)
                    restore_paths.append(path)
                gh('release', 'upload', 'core-updates', *restore_paths, '--clobber')
                restored = inventory(api('releases/tags/core-updates'))
                for name, raw in previous.items():
                    assert read_asset('core-updates', name, restored[name]) == raw, name
            raise
        final = api('releases/latest')
        assert final['id'] == candidate['id'] and final['tag_name'] == TAG
        assert not final['prerelease'] and not final['draft'] and final['target_commitish'] == lock['source_carrier']
        expected = public_receipt.read_bytes()
        assert read_asset(TAG, PUBLIC_RECEIPT, inventory(final)[PUBLIC_RECEIPT]) == expected
        Path(PUBLIC_RECEIPT).write_bytes(expected)


def main():
    if sys.flags.optimize:
        raise RuntimeError('Release gates must run with Python assertions enabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage-url', required=True)
    parser.add_argument('--stage-sha256', required=True)
    parser.add_argument('--approval-url', required=True)
    parser.add_argument('--approval-sha256', required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--verify-only', action='store_true', help='Read all gates without changing remote state (default)')
    action.add_argument('--publish', action='store_true', help='Run the gates and publish the approved prerelease')
    args = parser.parse_args()
    promote(args.stage_url, args.stage_sha256, args.approval_url, args.approval_sha256, verify_only=not args.publish)


if __name__ == '__main__':
    sys.argv.extend(["--stage-url","https://raw.githubusercontent.com/1281504089-cell/kaixin-k12-tutor/79a0f43907a335e50f67d438c1b19dce0b88eead/releases/student-20261121-resource-5-stage.json","--stage-sha256","356e6c3f890530060341436cc77c4ee12b020f5a6bc8c3086e7e03b0ce99eb90","--approval-url","https://raw.githubusercontent.com/1281504089-cell/kaixin-k12-tutor/9b4c1b43399e1ed8df092ce788389df901776f00/releases/student-20261121-resource-5-activation.json","--approval-sha256","90f2af21f848ebcd9ab062fd77596d57a1a09f1fd4cbb0adcd01e85a3b36fc04","--publish"])
    main()
