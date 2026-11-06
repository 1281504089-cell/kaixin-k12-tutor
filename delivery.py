"""Assemble private, credential-free native deliveries on disposable GitHub runners."""
import argparse, hashlib, json, os, shutil, subprocess, tarfile, time
from pathlib import Path

args = argparse.ArgumentParser(); args.add_argument('--target', required=True); args.add_argument('--stage', choices=['payload','package'], required=True); args.add_argument('--payload-run'); a=args.parse_args()
checkout=Path.cwd(); root=checkout/'student-source'; desktop=root/'apps/desktop'; local=desktop/'.local'/a.target; runtime=local/'runtime'; seed=local/'seed'; inputs=checkout/'delivery-inputs'; inputs.mkdir(exist_ok=True); local.mkdir(parents=True, exist_ok=True)
repo=os.environ['GITHUB_REPOSITORY']; run_id=os.environ['GITHUB_RUN_ID']
def run(command, cwd=root, env=None): subprocess.run([str(x) for x in command], cwd=cwd, env=env, check=True)
def digest(file):
    with file.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
def download(tag, pattern, folder=inputs):
    folder.mkdir(parents=True, exist_ok=True)
    command=['gh','release','download',tag,'--repo',repo,'--pattern',pattern,'--dir',str(folder),'--clobber']
    for attempt in range(4):
        result=subprocess.run(command,cwd=checkout,capture_output=True,text=True)
        if result.returncode==0: return
        error=result.stderr+result.stdout
        if attempt==3 or not any(token in error.lower() for token in ['http 500','http 502','http 503','http 504','http 429','timed out','connection reset','unexpected eof']):
            raise RuntimeError(error[-2000:])
        print(f'Transient download failure for {pattern}; retry {attempt+1}/3',flush=True)
        time.sleep(2**(attempt+1))
def extract(file,destination):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(file) as archive: archive.extractall(destination,filter='data')
def publish(tag, title, files, note):
    run(['gh','release','create',tag,'--repo',repo,'--prerelease','--title',title,'--notes',note], checkout)
    run(['gh','release','upload',tag,'--repo',repo,*files], checkout)
freeze=json.loads((root/'SOURCE_FREEZE.json').read_text())
if a.stage=='payload':
    if a.target=='macos-x64':
        download('delivery-resources-20261107','intel-native-base.tar.gz'); download('delivery-resources-20261107','base-manifest.json')
        base=json.loads((inputs/'base-manifest.json').read_text()); archive=inputs/base['archive']; assert digest(archive)==base['sha256']; extract(archive,runtime)
    else:
        native='42246334349' if a.target=='macos-arm64' else '42271997691'
        tag=f'native-{native}-{a.target}'
        download(tag,'*.tar.gz'); download(tag,'runtime.json'); download(tag,'runtime-public.pem')
        base=json.loads((inputs/'runtime.json').read_text()); archive=inputs/base['archive']; assert digest(archive)==base['sha256']
        run(['node','--input-type=module','-e',"import {readFile} from 'node:fs/promises'; import {verifyManifest} from './apps/desktop/src/bundles.mjs'; verifyManifest(JSON.parse(await readFile(process.argv[1])),await readFile(process.argv[2]),process.argv[3],process.argv[4]);",inputs/'runtime.json',inputs/'runtime-public.pem','arm64' if a.target=='macos-arm64' else 'x64','win32' if a.target.startswith('windows') else 'darwin'])
        extract(archive,runtime)
    archive.unlink()
    run(['node','apps/desktop/scripts/refresh-runtime.mjs','--target',a.target])
    run(['node',root/'web/node_modules/vitest/vitest.mjs','run','tests/mermaid-error-recovery.spec.tsx','tests/markdown-math-renderer.spec.tsx','tests/visualize/VisualizationViewer.spec.tsx','--maxWorkers=2'],root/'web')
    shutil.rmtree(root/'web/node_modules', ignore_errors=True); shutil.rmtree(root/'web/.next',ignore_errors=True)
    download('delivery-resources-20261107','textbooks-manifest.json'); download('delivery-resources-20261107','textbook-metadata.tar.gz'); download('delivery-resources-20261107','book-*.pdf')
    books=json.loads((inputs/'textbooks-manifest.json').read_text()); assert books['count']==136
    metadata=inputs/books['metadata']['file']; assert digest(metadata)==books['metadata']['sha256']
    shutil.rmtree(runtime/'student-seed',ignore_errors=True); extract(metadata,runtime/'student-seed'); metadata.unlink()
    for book in books['books']:
        file=inputs/book['file']; assert file.stat().st_size==book['bytes'] and digest(file)==book['sha256']
        relative=Path(book['relative']); assert relative.parts[0]=='reading' and relative.parts[1]==book['sha256'] and relative.parts[2]=='raw' and len(relative.parts)==4 and relative.suffix=='.pdf'
        dest=runtime/'student-seed'/relative; dest.parent.mkdir(parents=True,exist_ok=True); file.replace(dest)
    python=runtime/('python/python.exe' if a.target.startswith('windows') else 'python/bin/python3')
    run([python,root/'scripts/audit-student-bundle.py',runtime])
    run(['node','scripts/seal-runtime.mjs','--target',a.target,'--new-key'],desktop)
    run(['node',checkout/'verify_native.mjs','--target',a.target])
    run(['node','scripts/smoke.mjs','--target',a.target],desktop)
    manifest=json.loads((seed/'runtime.json').read_text()); assert manifest['commit']==freeze['commit']
    code="import {splitPayload} from './apps/desktop/scripts/lib/split-payload.mjs';import{writeFile}from'node:fs/promises';const parts=await splitPayload(process.argv[1],process.argv[1]);await writeFile(process.argv[2],JSON.stringify({parts}));"
    archive=seed/manifest['archive']; run(['node','--input-type=module','-e',code,archive,seed/'parts.json']); archive.unlink()
    tag=f'payload-{run_id}-{a.target}'
    evidence=list((local/'native-evidence').glob('*.json'))
    publish(tag,f'Validated full student runtime / {a.target}',[*seed.iterdir(),local/'smoke-result.json',*evidence],'Internal full runtime, pending local maintainer signature and installer packaging. No API keys or student records. Textbooks included.')
    print('DELIVERY_UNSIGNED_MANIFEST='+json.dumps({'payloadTag':tag,'manifest':manifest},separators=(',',':')))
else:
    if a.payload_run:
        assert a.payload_run.isdigit(); tag=f'payload-{a.payload_run}-{a.target}'
    else:
        tag=json.loads((checkout/'delivery-payloads.json').read_text())[a.target]
        assert tag.startswith('payload-') and tag.endswith('-'+a.target)
    download(tag,'parts.json'); download(tag,'*.tar.gz.*')
    manifest=json.loads((checkout/f'delivery-signed-{a.target}.json').read_text()); assert manifest['commit']==freeze['commit']
    seed.mkdir(parents=True,exist_ok=True); archive=seed/manifest['archive']; parts=json.loads((inputs/'parts.json').read_text())['parts']
    with archive.open('wb') as output:
        for part in parts:
            file=inputs/part['file']; assert file.stat().st_size==part['bytes'] and digest(file)==part['sha256']
            with file.open('rb') as stream: shutil.copyfileobj(stream,output)
            file.unlink()
    assert digest(archive)==manifest['sha256']; (seed/'runtime.json').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copy2(checkout/'delivery-runtime-public.pem',desktop/'assets/runtime-public.pem')
    env={**os.environ,'KX_CONSUME_CI_INPUTS':'1'}; run(['node','scripts/package.mjs','--target',a.target],desktop,env)
    if a.target.startswith('windows'):
        run(['powershell','-NoProfile','-File',desktop/'platforms/windows-x64/smoke-installer.ps1'],desktop)
    else:
        run(['node',checkout/'smoke_mac.mjs','--target',a.target],root)
    for name in ['components.json','smoke-result.json']:
        download(tag,name); shutil.copy2(inputs/name,desktop/'out'/name)
    shutil.copy2(checkout/'delivery-notes.md',desktop/'out/接口与授权说明.md')
    files=[p for p in (desktop/'out').iterdir() if p.is_file()]
    assert files and all(p.stat().st_size<2*1024**3 for p in files)
    checksums=''.join(f'{digest(p)}  {p.name}\n' for p in files); sums=desktop/'out/SHA256SUMS.txt'; sums.write_text(checksums)
    report={'target':a.target,'approvedSource':freeze['commit'],'runtime':manifest['runtimeId'],'apiKeysIncluded':False,'studentRecordsIncluded':False,'installerSmoke':'passed','runner':os.environ.get('ImageOS'),'platformSigning':'ad-hoc' if not a.target.startswith('windows') else 'unsigned'}
    receipt=desktop/'out/validation.json'; receipt.write_text(json.dumps(report,indent=2)+'\n')
    guide=desktop/'out/安装说明.txt'; guide.write_text('同一平台的全部分卷请放在同一文件夹。Mac 打开第一个 .dmg，再拖入 Applications；Windows 双击 Setup.exe，资源分卷自动校验合并。首次启动解压本机运行环境，建议预留至少 30GB 可用空间。安装包不含 API Key，请在设置中填写个人接口。教材、错题本、笔记和学习记录保存在本机。此体验版没有购买系统开发者签名。\n',encoding='utf-8')
    publish(f'student-{freeze["commit"][:9]}-{a.target}',f'开心动力超级学霸体验版 · {a.target}',[*files,sums,receipt,guide],'Student installer. Download all files for this platform into one folder. No API keys or personal learning records. Native install/startup checks passed on a fresh CI profile; consumer hardware testing remains separate.')
