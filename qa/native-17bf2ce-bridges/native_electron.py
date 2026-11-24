"""Reuse the verified native Electron shell and exact signed recovery asset."""
import gzip, os, platform, plistlib, tarfile
from ci_repackage import run, APP
from ci_fresh_install import digest as sha

PUBLIC_KEY='-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA8QpxFW2KekaGdPipMxCi9UgADS4GG+/4T6BDxcyVa38=\n-----END PUBLIC KEY-----\n'
PACKAGE='{"name":"kaixin-super-scholar","productName":"开心动力超级学霸","version":"1.7.1","type":"module","main":"diagram-fallback-probe.cjs"}'

def setup(work,target):
    mac=target.startswith('macos')
    arch=target.split('-')[1]
    assert platform.machine()=={'macos-arm64':'arm64','macos-x64':'x86_64','windows-x64':'AMD64'}[target]
    version='45.1.0'
    origin=f'https://github.com/electron/electron/releases/download/v{version}/'
    bundle=work/f'electron-v{version}-{"darwin" if mac else "win32"}-{arch}.zip'
    checks=work/'SHA256SUMS'
    for name,dest in [('SHASUMS256.txt',checks),(bundle.name,bundle)]:
        run('curl','-fLsS','--retry','2','--connect-timeout','12','--max-time','420',origin+name,'-o',dest,timeout=480)
    know={line.split()[1].lstrip('*'):line.split()[0] for line in checks.read_text().splitlines() if line.strip()}
    assert sha(bundle)==know[bundle.name]
    if mac:
        run('/usr/bin/ditto','-x','-k',bundle,work,timeout=180)
        app=work/'Electron.app'
        resources=app/'Contents/Resources'
        exe=app/'Contents/MacOS'/APP
        exe.with_name('Electron').rename(exe)
        info=resources.parent/'Info.plist'
        config=plistlib.loads(info.read_bytes())
        config.update(CFBundleExecutable=APP,CFBundleIdentifier='org.kaixindongli.super-scholar',CFBundleName=APP,CFBundleDisplayName=APP)
        info.write_bytes(plistlib.dumps(config,sort_keys=False))
    else:
        tar=os.path.join(os.environ['SystemRoot'],'System32','tar.exe')
        run(tar,'-xf',bundle,'-C',work,timeout=180)
        app=work
        resources=app/'resources'
        exe=app/(APP+'.exe')
        exe.with_name('electron.exe').rename(exe)
    bundle.unlink()
    (resources/'default_app.asar').unlink(missing_ok=True)
    return app,resources,exe

def launcher_files(archive,destination):
    dst=destination/'src'
    dst.mkdir(parents=True)
    with gzip.open(archive,'rb') as data, tarfile.open(fileobj=data,mode='r|') as source:
        for member in source:
            name=member.name.removeprefix('./')
            if name=='launcher/manifest.json':
                (destination/'manifest.json').write_bytes(source.extractfile(member).read())
            if name.startswith('launcher/src/'):
                assert member.isfile() and '/' not in name.removeprefix('launcher/src/')
                (dst/name.split('/')[-1]).write_bytes(source.extractfile(member).read())
    assert (destination/'manifest.json').is_file()
    (destination/'assets').mkdir()
    (destination/'assets/runtime-public.pem').write_text(PUBLIC_KEY)
