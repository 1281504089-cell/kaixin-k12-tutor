"""Embed literal PowerShell commands in a one-click CMD; no execution-policy changes."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent
source = root / 'Collect-WindowsUpdateDiagnostic.ps1'
script = source.read_text(encoding='utf-8-sig')
source.write_text(script, encoding='utf-8-sig')
lines = script.splitlines()
assert all('"' not in line and '%' not in line for line in lines)
command = '; '.join(lines)
assert len(command.encode('utf-8')) < 7800, 'Keep below the Windows CMD command-line limit'
launcher = root / '双击检查Windows更新.cmd'
launcher.write_bytes(('\r\n'.join([
    '@echo off',
    'chcp 65001 >nul',
    'setlocal DisableDelayedExpansion',
    'set "KX_DIAGNOSTIC_OUTPUT=%~dp0"',
    '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command ^',
    *[' "' + line + ';"' + (' ^' if i < len(lines) - 1 else '') for i, line in enumerate(lines)],
    'set "KX_DIAGNOSTIC_EXIT=%ERRORLEVEL%"',
    'if not "%KX_DIAGNOSTIC_EXIT%"=="0" echo 诊断未完成，请把此窗口截图发来。',
    'if not defined KX_DIAGNOSTIC_TEST_ROOT pause',
    'exit /b %KX_DIAGNOSTIC_EXIT%',
    '',
])).encode('utf-8'))
assert '-ExecutionPolicy' not in launcher.read_text(encoding='utf-8')
with zipfile.ZipFile(root / 'Windows只读更新诊断.zip', 'w', zipfile.ZIP_DEFLATED) as package:
    package.write(launcher, launcher.name)
print(root / 'Windows只读更新诊断.zip')
