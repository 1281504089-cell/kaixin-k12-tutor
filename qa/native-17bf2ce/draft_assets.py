"""Read pinned release bytes from GitHub; draft credentials never follow redirects."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ci_fresh_install import API, REPO, checked_url, download, metadata

CHUNK = 4 * 1024 * 1024


class VerifiedRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, checked_url(newurl))


opener = build_opener(VerifiedRedirects())
def gh(*arguments):
    return json.loads(subprocess.check_output(['gh', 'api', *arguments], stderr=subprocess.PIPE))


def draft(lock):
    pages = gh('--paginate', '--slurp', f'repos/{REPO}/releases?per_page=100')
    found = [r for page in pages for r in page if r['draft'] and r['name'] == lock['draft_title']]
    if len(found) != 1:
        raise ValueError('Expected exactly one matching private QA draft')
    release = found[0]
    assets = gh('--paginate', '--slurp', f'repos/{REPO}/releases/{release["id"]}/assets?per_page=100')
    assets = [row for page in assets for row in page]
    if len({row['name'] for row in assets}) != len(assets):
        raise ValueError('Draft asset name is ambiguous')
    return release, {row['name']: row for row in assets}


def pinned_draft_asset(assets, expected, destination):
    asset = assets.get(expected['name'])
    if not asset or (asset['state'], asset['size'], asset['digest']) != (
            'uploaded', expected['bytes'], 'sha256:' + expected['sha256']):
        raise ValueError('Draft asset missing or awaiting its exact digest: ' + expected['name'])
    url = f'{API}/releases/assets/{asset["id"]}'
    if asset['url'] != url:
        raise ValueError('Unexpected asset API address')
    request = Request(url, headers={'Accept': 'application/octet-stream', 'Accept-Encoding': 'identity',
        'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Scholar-Native-QA',
        'Range': f'bytes=0-{expected["bytes"]-1}'})
    request.add_unredirected_header('Authorization', 'Bearer ' + os.environ['GH_TOKEN'])
    partial = destination.with_name(destination.name + '.partial')
    digest = hashlib.sha256()
    size = 0
    try:
        with opener.open(request, timeout=120) as response, partial.open('xb') as output:
            checked_url(response.url)
            if response.status == 206:
                assert response.headers['Content-Range'] == f'bytes 0-{expected["bytes"]-1}/{expected["bytes"]}'
            else:
                assert response.status == 200
            for chunk in iter(lambda: response.read(CHUNK), b''):
                size += len(chunk)
                assert size <= expected['bytes']
                digest.update(chunk)
                output.write(chunk)
        assert (size, digest.hexdigest()) == (expected['bytes'], expected['sha256'])
        partial.rename(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {**expected, 'github_asset_id': asset['id'], 'verified': True}


def historical_installers(profile, directory):
    releases = {}
    directory.mkdir()
    receipts = []
    for expected in profile['baseline_installers']:
        tag = expected.get('source_tag', profile['baseline_tag'])
        release_id = expected.get('source_release_id', profile['baseline_release_id'])
        if tag not in releases:
            releases[tag] = metadata(tag)
        release = releases[tag]
        assert (release['id'], release['tag_name'], release['draft'], release['prerelease']) == (
            release_id, tag, False, False)
        receipts.append(download(release, expected, directory / expected['name']))
    return receipts
