"""Reproduce one signed delta and optionally retain it in the frozen private draft."""

from argparse import ArgumentParser
import gzip
from hashlib import file_digest, sha256
import http.client
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode,urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

HERE=Path(__file__).resolve().parent
LOCK=json.loads((HERE/'delta-lock.json').read_bytes())
REPO='1281504089-cell/kaixin-k12-tutor'
API='https://api.github.com/repos/'+REPO
BRANCH='refs/heads/codex/desktop-native-qa-17bf2ce'
HOSTS={'api.github.com','github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'}


class GithubRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        url=urlsplit(newurl)
        assert url.scheme=='https' and url.hostname in HOSTS and not (url.username or url.password)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


opener=build_opener(GithubRedirect())


def describe(path):
    with path.open('rb') as stream:
        return {'name':path.name,'bytes':path.stat().st_size,'sha256':file_digest(stream,'sha256').hexdigest()}


def gh(*arguments):
    return json.loads(subprocess.check_output(['gh','api',*arguments],stderr=subprocess.PIPE))


def pinned_draft():
    row=gh(f'repos/{REPO}/releases/{LOCK["draft_id"]}')
    assert row['draft'] is True and row['id']==LOCK['draft_id'] and row['name']==LOCK['draft_title']
    paths=gh('--paginate','--slurp',f'repos/{REPO}/releases/{row["id"]}/assets?per_page=100')
    values=[item for page in paths for item in page]
    unique={item['name']:item for item in values}
    assert len(unique)==len(values)
    assert match(unique[LOCK['core']['name']],LOCK['core'])
    return row,unique


def match(row,expected):
    return row.get('state')=='uploaded' and row.get('size')==expected['bytes'] and row.get('digest')=='sha256:'+expected['sha256']


def download(asset,expected,out):
    assert match(asset,expected)
    address=API+f'/releases/assets/{asset["id"]}'
    assert asset['url']==address
    request=Request(address,headers={'Accept':'application/octet-stream','Accept-Encoding':'identity',
      'User-Agent':'Scholar-Exact-Delta', 'Range':f'bytes=0-{expected["bytes"]-1}'})
    request.add_unredirected_header('Authorization','Bearer '+os.environ['GH_TOKEN'])
    count=0
    digest=sha256()
    with opener.open(request,timeout=120) as response,out.open('xb') as target:
        assert response.status in (200,206)
        if response.status==206:
            assert response.headers['Content-Range']==f'bytes 0-{expected["bytes"]-1}/{expected["bytes"]}'
        while block:=response.read(4*1024**2):
            count+=len(block)
            assert count<=expected['bytes']
            digest.update(block)
            target.write(block)
    assert (count,digest.hexdigest())==(expected['bytes'],expected['sha256'])


def put(draft,file,expected):
    url=urlsplit(draft['upload_url'].removesuffix('{?name,label}'))
    endpoint=f'/repos/{REPO}/releases/{draft["id"]}/assets'
    assert url.scheme=='https' and url.netloc=='uploads.github.com' and url.path==endpoint and not url.query
    connection=http.client.HTTPSConnection('uploads.github.com',timeout=160,blocksize=1024**2)
    try:
        with file.open('rb') as body:
            connection.request('POST',endpoint+'?'+urlencode({'name':file.name}),body=body,headers={
              'Authorization':'Bearer '+os.environ['GH_TOKEN'],'Content-Type':'application/octet-stream',
              'Content-Length':str(expected['bytes']),'Accept':'application/vnd.github+json',
              'User-Agent':'Scholar-Exact-Delta'})
            response=connection.getresponse()
            raw=response.read(65536)
            if response.status!=201:
                raise RuntimeError(f'GitHub returned HTTP {response.status}; inspect draft before retrying.')
    finally:
        connection.close()
    answer=json.loads(raw)
    assert (answer['name'],answer['size'])==(file.name,expected['bytes'])
    for _ in range(5):
        time.sleep(2)
        row,archive=pinned_draft()
        item=archive.get(file.name)
        if row['id']==draft['id'] and item and item['id']==answer['id'] and match(item,expected):
            return item['id']
    raise RuntimeError('Retained delta did not read back with its signed SHA-256')


def verify_inputs():
    for item in ('builder','signed_alias','public_key'):
        expected=LOCK[item]
        assert describe(HERE/expected['name'])==expected
    alias=json.loads((HERE/LOCK['signed_alias']['name']).read_bytes())
    assert alias['coreDelta']==LOCK['expected_delta']
    assert alias['commit']==LOCK['source_commit']
    assert alias['corePayloadSha256']==alias['sha256']==LOCK['core']['sha256']
    assert alias['archive']==LOCK['core']['name']
    script=r'''
import assert from 'node:assert/strict';
import {verify} from 'node:crypto';
import {readFileSync} from 'node:fs';
const [manifestPath,keyPath]=process.argv.slice(1);
const doc=JSON.parse(readFileSync(manifestPath));
const signature=Buffer.from(doc.signature,'base64');
delete doc.signature;
const data=Object.fromEntries(Object.entries(doc).sort(([a],[b])=>a.localeCompare(b)));
assert(doc.formatVersion===1 && doc.protocolVersion===1 && doc.platform==='win32' && doc.arch==='x64');
assert(verify(null,Buffer.from(JSON.stringify(data)),readFileSync(keyPath),signature));
'''
    subprocess.run(['node','--input-type=module','-e',script,HERE/LOCK['signed_alias']['name'],
                    HERE/LOCK['public_key']['name']],check=True)


def unpack(work,label):
    item=LOCK['inventories'][label]
    packed=HERE/item['packed']['name']
    assert describe(packed)==item['packed']
    raw=gzip.decompress(packed.read_bytes())
    assert (len(raw),sha256(raw).hexdigest())==(item['plain']['bytes'],item['plain']['sha256'])
    destination=work/(label+'.json')
    destination.write_bytes(raw)
    return destination


def main():
    if sys.flags.optimize:
        raise RuntimeError('Signature and byte guards require Python assertions enabled')
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--local-core',type=Path,help='Use already verified local core without any remote calls')
    parser.add_argument('--upload',action='store_true',help='On the dedicated QA branch, retain exact bytes in the pinned private draft')
    parser.add_argument('--receipt',type=Path,required=True)
    args=parser.parse_args()
    if args.upload:
        assert not args.local_core and os.environ.get('GITHUB_REF')==BRANCH
    started=time.monotonic()
    verify_inputs()
    expected=LOCK['expected_delta']
    # Fail closed on an already staged asset with a conflicting digest.
    if not args.local_core:
        row,assets=pinned_draft()
        existing=assets.get(expected['archive'])
        if existing is not None:
            assert match(existing,expected)
            args.receipt.write_text(json.dumps({'verified_existing':True,'draft_id':row['id'],
                'asset_id':existing['id'],'expected':expected},indent=2)+'\n')
            return
    with TemporaryDirectory(prefix='frozen-scholar-delta-',dir=os.environ.get('RUNNER_TEMP')) as folder:
        work=Path(folder)
        assert shutil.disk_usage(work).free>(LOCK['core']['bytes'] if not args.local_core else 0)+64*1024**2
        before=unpack(work,'previous-cos-windows-inventory')
        after=unpack(work,'final-17bf2ce-inventory')
        core=args.local_core.resolve(strict=True) if args.local_core else work/LOCK['core']['name']
        if not args.local_core:
            download(assets[LOCK['core']['name']],LOCK['core'],core)
        assert describe(core)==LOCK['core']
        output=work/expected['archive']
        rebuild_started=time.monotonic()
        env={k:v for k,v in os.environ.items() if k not in ('GH_TOKEN','GITHUB_TOKEN')}
        actual=json.loads(subprocess.check_output([sys.executable,HERE/'build-core-delta.py',before,after,
                          expected['fromCoreSha256'],core,output],env=env))
        rebuild_seconds=round(time.monotonic()-rebuild_started,3)
        assert actual==expected, f'Compression bytes differ (Python {platform.python_version()}, zlib {zlib.ZLIB_RUNTIME_VERSION}); use the existing signed artifact'
        assert describe(output)=={'name':expected['archive'],'bytes':expected['bytes'],'sha256':expected['sha256']}
        proof={'verified_exact':True,'expected':expected,'platform':platform.platform(),'python':platform.python_version(),
               'zlib':zlib.ZLIB_RUNTIME_VERSION,'rebuild_seconds':rebuild_seconds,'uploaded':False}
        if args.upload:
            current,assets=pinned_draft()
            assert current['id']==row['id']
            existing=assets.get(output.name)
            if existing:
                assert match(existing,expected)
                asset_id=existing['id']
            else:
                asset_id=put(current,output,expected)
            proof.update(draft_id=current['id'],asset_id=asset_id,uploaded=existing is None)
        proof['seconds']=round(time.monotonic()-started,3)
        args.receipt.write_text(json.dumps(proof,indent=2)+'\n')
        print(json.dumps(proof))


if __name__=='__main__':
    main()
