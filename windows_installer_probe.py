"""Reproduce the exact NSIS resource validation with tiny, disposable inputs."""
from pathlib import Path
import hashlib,json,os,subprocess
root=Path.cwd(); work=root/'installer-probe'; work.mkdir(); source=work/'source'; (source/'resources/seed').mkdir(parents=True)
(source/'开心动力超级学霸.exe').write_bytes(b'fixture')
(source/'resources/seed/runtime.json').write_text('{}')
icon=root/'probe.ico'
# NSIS accepts its own installed icon; no third-party or app resources required.
nsis=Path(os.environ['ProgramFiles(x86)'])/'NSIS'; icon=nsis/'Contrib/Graphics/Icons/modern-install.ico'
data=b'verified runtime fixture'*1024
parts=[]
for i,part in enumerate((data[:10000],data[10000:]),1):
 file=work/f'Runtime.{i:03d}';file.write_bytes(part);parts.append({'file':file.name,'bytes':len(part),'sha256':hashlib.sha256(part).hexdigest()})
manifest=work/'parts.json';manifest.write_text(json.dumps({'sha256':hashlib.sha256(data).hexdigest(),'parts':parts}))
exe=work/'Setup.exe'
subprocess.run([nsis/'makensis.exe',f'/DSOURCE={source}',f'/DOUTFILE={exe}',f'/DICON={icon}','/DVERSION=1.7.1','/DFILEVERSION=1.7.1.0',f'/DPARTS_MANIFEST={manifest}','/DARCHIVE_NAME=runtime.tar.gz',root/'installer-probe.nsi'],check=True)
script=work/'probe.ps1'
script.write_text("""$ErrorActionPreference='Stop'
$root=Join-Path $env:TEMP ('KX 安装 probe '+[guid]::NewGuid())
$install=Join-Path $root 'installed app'
New-Item -ItemType Directory -Path $install -Force | Out-Null
Set-Content (Join-Path $install 'keep-user-file.dll') 'unrelated file'
$result=Start-Process $env:KX_PROBE_EXE -ArgumentList @('/S', "/D=$install") -Wait -PassThru
Write-Host ('INSTALL_EXIT='+$result.ExitCode)
if (Test-Path $env:KX_PROBE_LOG) {Get-Content $env:KX_PROBE_LOG -Raw | Write-Host}
Write-Host ('INSTALLED='+[bool](Test-Path (Join-Path $install '开心动力超级学霸.exe')))
if ($result.ExitCode -ne 0) {throw 'Small valid installer failed'}
""",encoding='utf-8-sig')
env={**os.environ,'KX_PROBE_EXE':str(exe),'KX_PROBE_LOG':str(work/'installer-probe.log')}
results=[]
for shell in ['powershell','pwsh']:
    result=subprocess.run([shell,'-NoProfile','-File',script],env=env,capture_output=True,text=True,errors='replace')
    print('PARENT_SHELL='+shell+' EXIT='+str(result.returncode),flush=True)
    print(result.stdout+result.stderr,flush=True)
    results.append({'parent':shell,'exit':result.returncode})
print('INSTALLER_PARENT_RESULTS='+json.dumps(results),flush=True)


assert all(row['exit']==0 for row in results), results

import shutil
validation=root/'student-source/apps/desktop/platforms/windows-x64'
validation.mkdir(parents=True,exist_ok=True)
shutil.copy2(root/'join-payload.ps1',validation/'join-payload.ps1')
subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',root/'test-payload.ps1'],check=True)
