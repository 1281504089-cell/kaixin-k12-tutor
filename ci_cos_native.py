"""Verify COS and migration on the exact public candidate installer."""
from hashlib import file_digest, sha256
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ci_update_probe import verify_update_entry


def load(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def verify_candidate_cos(root, target, install, resources, executable, work, evidence, downloads):
    old = load(root / 'cos-baseline-batch.json')
    batch = load(root / 'attachment-batch.json')
    previous = old['manifests'][target]
    selected = batch['manifests'][target]
    descriptor = load(root / 'launcher-manifest.json')
    old_descriptor = load(root / 'cos-k11-launcher-manifest.json')
    release = load(root / 'attachment-release.json')
    mirror = 'https://kaixin-scholar-updates-1492384993.cos.ap-shanghai.myqcloud.com/desktop/'
    assert release['update_mirror_base'] == mirror
    assert load(resources / 'update/runtime.json') == selected
    assert descriptor['coreCommit'] == selected['commit'] == release['source_commit']
    assert old_descriptor['coreCommit'] == previous['commit'] and old['launcher_build'] == old_descriptor['buildId']
    for row in descriptor['files']:
        blob = (resources / 'app' / row['file']).read_bytes()
        assert len(blob) == row['bytes'] and sha256(blob).hexdigest() == row['sha256']

    staging = root / 'cos-k11-prior'
    staging.mkdir()
    archive = staging / previous['archive']
    asset = old['core_asset']
    assert archive.name == asset['name'] and asset['digest'] == 'sha256:' + previous['sha256']
    assert asset['browser_download_url'] == 'https://github.com/1281504089-cell/kaixin-k12-tutor/releases/download/' + old['tag'] + '/' + archive.name
    request = Request(asset['browser_download_url'], headers={'User-Agent':'Kaixin-native-COS-acceptance'})
    with urlopen(request, timeout=90) as response, archive.open('xb') as stream:
        assert response.geturl().startswith(('https://github.com/', 'https://release-assets.githubusercontent.com/', 'https://objects.githubusercontent.com/'))
        shutil.copyfileobj(response, stream, 8 * 1024**2)
    with archive.open('rb') as stream:
        assert archive.stat().st_size == asset['size'] and file_digest(stream, 'sha256').hexdigest() == previous['sha256']
    write(staging / 'runtime.json', previous)
    rows = extract_old_launcher(root, old_descriptor, archive, evidence)
    assert rows == len(old_descriptor['files'])

    default = 'runtime-' + target + '.json'
    print('Waiting for the signed COS release files:', target, flush=True)
    deadline = time.monotonic() + 60 * 60
    while True:
        try:
            with urlopen(mirror + default, timeout=30) as response:
                assert response.geturl() == mirror + default and response.status == 200
                default_manifest = json.loads(response.read(65537))
            break
        except HTTPError as error:
            if error.code not in (403, 404) or time.monotonic() >= deadline:
                raise
            time.sleep(15)
    assert default_manifest['commit'] == selected['commit']
    alias = next(row['file'] for row in default_manifest['compatibleBaseManifests'] if row['baseRuntimeId'] == previous['baseRuntimeId'])
    expected_alias = default.removesuffix('.json') + '-' + batch['tag'].removeprefix('student-') + '-20261112.json'
    assert alias == expected_alias
    cos_manifest = evidence / alias
    with urlopen(mirror + alias, timeout=30) as response:
        assert response.geturl() == mirror + alias and response.status == 200
        cos_manifest.write_bytes(response.read(65537))
    assert load(cos_manifest) == selected

    # The unchanged installer starts itself once. Later profiles share only verified runtime files.
    template = work / '全新学习目录'
    fixture = evidence / 'actual-candidate-install'
    fixture.mkdir()
    os.environ.pop('GH_TOKEN', None)
    env = {**os.environ, 'KX_EXPECTED_PLATFORM':selected['platform'], 'KX_EXPECTED_ARCH':selected['arch']}
    subprocess.run(['node', 'ci-fresh-smoke.mjs', str(executable), str(resources), str(template), str(fixture)],
                   check=True, timeout=1100, env=env)
    assert load(template / 'active.json') == selected
    assert load(fixture / 'app.json')['real_keys_used'] is False
    catalog_path = 'workspace/data/user/settings/model_catalog.json'
    voice = load(template / catalog_path)['services']['tts']
    assert voice['active_profile_id'] and voice['active_model_id']
    scenarios = {}
    for scenario in ('migration', 'cos', 'fallback'):
        print('Starting anonymous native route test:', target, scenario, flush=True)
        profile = work / ('isolated-' + scenario)
        catalog = profile / catalog_path
        catalog.parent.mkdir(parents=True)
        write(catalog, {'services':{'tts':voice}})
        shutil.copytree(template / 'runtimes', profile / 'runtimes', symlinks=True, copy_function=os.link)
        shutil.copyfile(template / 'active.json', profile / 'active.json')
        report_dir = evidence / scenario
        report_dir.mkdir()
        spec = report_dir / 'spec.json'
        switches = []
        if scenario != 'migration':
            switches += ['--cos-manifest', str(cos_manifest)]
        if scenario != 'cos':
            switches += ['--stage-github']
        subprocess.run([sys.executable, 'make-native-spec.py', scenario, target, '--baseline', 'cos-baseline-batch.json',
                        '--candidate', 'attachment-batch.json', '--old-launcher', 'cos-k11-launcher-manifest.json',
                        '--new-launcher', 'launcher-manifest.json', '--out', str(spec), *switches], check=True)
        scenarios[scenario] = verify_update_entry(root, target, install, resources, profile, report_dir, cos_spec=spec)
        shutil.rmtree(profile)
    write(evidence / 'COS-NATIVE-VERIFICATION.json', {
        'target':target, 'source_commit':batch['core_commit'], 'tag':batch['tag'],
        'launcher':batch['launcher_build'], 'native_run':int(os.environ['GITHUB_RUN_ID']),
        'workflow_commit':os.environ['GITHUB_SHA'], 'tested_candidate_installer':True,
        'installer_downloads':downloads, 'scenarios':scenarios,
    })


def extract_old_launcher(root, descriptor, archive, evidence):
    files = {'launcher/' + row['file']:row for row in descriptor['files']}
    base = root / 'cos-k11-launcher-src'
    base.mkdir()
    count = 0
    with tarfile.open(archive, 'r|gz') as bundle:
        for member in bundle:
            name = member.name.removeprefix('./')
            if name == 'launcher/manifest.json':
                assert member.isfile() and member.size < 16384
                staged = bundle.extractfile(member).read()
                assert json.loads(staged) == descriptor
                (evidence / 'published-k11-launcher.json').write_bytes(staged)
            if name in files:
                row = files.pop(name)
                assert member.isfile() and member.size == row['bytes']
                data = bundle.extractfile(member).read()
                assert sha256(data).hexdigest() == row['sha256']
                (base / name.rsplit('/', 1)[1]).write_bytes(data)
                count += 1
    assert not files and (evidence / 'published-k11-launcher.json').is_file()
    return count
