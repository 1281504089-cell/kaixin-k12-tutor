"""Build small offline update ZIPs. Does not change any installed app or GitHub release."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
META = json.loads((ROOT / 'ci-core-release.json').read_text())['core']
OUT = ROOT / '本地更新包'
OUT.mkdir(exist_ok=True)
TARGETS = {'windows-x64': 'Windows', 'macos-x64': 'Mac-Intel', 'macos-arm64': 'Mac-Apple芯片'}
CMD = '''@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
set "SCHOLAR_UPDATE_HOME=%LOCALAPPDATA%\\开心动力超级学霸"
if defined OPEN_DEEPTUTOR_TEST_HOME set "SCHOLAR_UPDATE_HOME=%OPEN_DEEPTUTOR_TEST_HOME%"
set "SCHOLAR_UPDATE_NODE="
for /d %%D in ("%SCHOLAR_UPDATE_HOME%\\runtimes\\*") do if exist "%%~fD\\node\\node.exe" set "SCHOLAR_UPDATE_NODE=%%~fD\\node\\node.exe"
if not defined SCHOLAR_UPDATE_NODE (
  echo 未找到已安装软件的运行环境。请先打开已安装的超级学霸一次，再运行本文件。
  pause
  exit /b 1
)
"%SCHOLAR_UPDATE_NODE%" "%~dp0tools\\scripts\\select-offline-update.mjs" "%~dp0."
pause
'''
COMMAND = '''#!/bin/zsh
set -eu
setopt null_glob
scholar_update_dir=${0:A:h}
scholar_update_home=${OPEN_DEEPTUTOR_TEST_HOME:-"$HOME/Library/Application Support/开心动力超级学霸"}
scholar_update_nodes=("$scholar_update_home"/runtimes/*/node/bin/node)
if (( ${#scholar_update_nodes} == 0 )); then
  print "未找到已安装的运行环境。请先打开已安装的软件一次。"
  read "?按回车关闭。"
  exit 1
fi
"${scholar_update_nodes[1]}" "$scholar_update_dir/tools/scripts/select-offline-update.mjs" "$scholar_update_dir" || { read "?按回车关闭。"; exit 1; }
read "?按回车关闭。"
'''
NOTE = '''开心动力超级学霸 · 三端原地核心更新 · 2026-11-13

适用于已经安装完整版的电脑；不是安装器，不需要卸载、删除原程序或重新填写 Key。
本包继续使用现有的 Python、Node、离线模型、教材和学习工作区。

更新步骤
1. 把整个 ZIP 完整解压到电脑上的普通文件夹。不要在 ZIP 内直接运行，不要拆开核心 tar.gz。
2. Windows 双击“00-匹配现有版本.cmd”；Mac 双击“00-匹配现有版本.command”。
   工具只读取安装版本编号并校验签名和核心包，不修改已安装程序、Key或学习记录。
3. 工具匹配成功后，回到已经安装的超级学霸，停止正在进行的生成或通话。
4. 点击窗口顶部菜单“核心 → 安装核心更新”，选择本文件夹中生成的“选这个文件更新.json”。
5. 确认更新，等待软件自动备份工作区、切换核心并重新打开学习页面。
6. 更新后在顶部菜单“开心动力超级学霸 → 关于”核对运行核心编号，应含 20261113-sync2。
   产品主版本仍显示 1.7.1；本次以运行核心编号区分构建。

如果此前出现“这份更新需要当前完整版的运行环境”，本包会按本机已有编号选清单，
兼容 20261112 U 盘完整版（04276f68a）和早期完整版（77f2ba387），无需重装。
不知道版本时不要手动猜两份清单；先运行匹配工具。
若工具显示没有匹配批次，不会修改原程序，请保留提示文字以便补齐对应清单。

版本与验证范围
三端使用同一冻结源码 a47b05f9136ca6fb72d2f1f8a04eeb425298f358，同一前端构建。
包括该源码中已经整合的阅读、附件、语音、任务/历史操作、科目入口和更新提示。
不包含尚待用户指示合并的后续 personal agent 独立分支。
三端签名、架构与新旧批次匹配已经自动校验。配套“验证结果.json”记录原生运行验证范围。
本文件夹用于离线更新；联网更新入口发布后，也可以直接在原软件点击“检查更新”。
'''
receipts = []
for target, label in TARGETS.items():
    directory = OUT / label
    directory.mkdir(exist_ok=True)
    for name in (META['archive'], f'runtime-{target}.json', f'runtime-{target}-early.json'):
        shutil.copyfile(ROOT / 'release-r2' / name, directory / name)
    tools = directory / 'tools'
    for folder in ('scripts', 'src', 'assets'):
        (tools / folder).mkdir(parents=True, exist_ok=True)
    desktop = ROOT / ('source' if (ROOT / 'source').exists() else 'student-source') / 'apps/desktop'
    for name in ('scripts/select-offline-update.mjs', 'src/bundles.mjs', 'src/platform.mjs', 'assets/runtime-public.pem'):
        shutil.copyfile(desktop / name, tools / name)
    (directory / '先看更新步骤.txt').write_text(NOTE, encoding='utf-8-sig')
    report_file = ROOT / 'native-results' / f'verification-{target}.json'
    report = json.loads(report_file.read_text()) if report_file.exists() else {'target': target, 'native_validation': 'pending'}
    (directory / '验证结果.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    start = directory / ('00-匹配现有版本.cmd' if target == 'windows-x64' else '00-匹配现有版本.command')
    start.write_bytes(CMD.replace('\n', '\r\n').encode('utf-8') if target == 'windows-x64' else COMMAND.encode('utf-8'))
    start.chmod(0o755)
    entries = [p for p in directory.rglob('*') if p.is_file()]
    checksums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(directory).as_posix() + '\n' for p in sorted(entries))
    (directory / 'SHA256SUMS.txt').write_text(checksums)
    archive = OUT / f'超级学霸-{label}-原地更新-20261113.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
        for file in sorted(directory.rglob('*')):
            if file.is_file():
                bundle.write(file, file.relative_to(directory))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert hashlib.sha256(bundle.read(META['archive'])).hexdigest() == META['sha256']
    receipts.append({'target': target, 'path': str(archive), 'bytes': archive.stat().st_size,
                     'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'zip_readback': True})
(ROOT / 'OFFLINE_PACKAGES.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2) + '\n')
(OUT / '先看更新步骤.txt').write_text(NOTE, encoding='utf-8-sig')
print(json.dumps(receipts, ensure_ascii=False))
