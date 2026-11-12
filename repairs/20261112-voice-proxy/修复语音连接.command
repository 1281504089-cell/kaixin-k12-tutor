#!/bin/zsh
set -euo pipefail
repair_dir="${0:A:h}"
student_dir="$HOME/Library/Application Support/开心动力超级学霸"
if [[ ! -f "$student_dir/active.json" ]]; then
  print '没有找到已运行过的开心动力超级学霸，请先打开客户端一次，再运行此修复。'
  exit 1
fi
runtime_id=$(/usr/bin/plutil -extract baseRuntimeId raw -o - "$student_dir/active.json" 2>/dev/null || /usr/bin/plutil -extract runtimeId raw -o - "$student_dir/active.json")
if [[ ! "$runtime_id" =~ '^[A-Za-z0-9][A-Za-z0-9._-]*$' ]]; then
  print '运行环境标识异常，未作任何修改。'
  exit 1
fi
runtime_python="$student_dir/runtimes/$runtime_id/python/bin/python3"
if [[ ! -x "$runtime_python" ]]; then
  print '没有找到客户端自带的 Python，未作任何修改。'
  exit 1
fi
"$runtime_python" -I - "$repair_dir" <<'PY'
from pathlib import Path
import hashlib
import subprocess
import sys

wheel = Path(sys.argv[1]) / 'python_socks-3.2.1-py3-none-any.whl'
expected = 'db2c37d4f7aeebfbba91d2d7670718b2d516061b34296fa8498c6f671e87c504'
if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
    raise SystemExit('语音组件校验失败，未作任何修改。请重新复制完整修复文件夹。')
subprocess.run([sys.executable, '-I', '-m', 'pip', 'install', '--break-system-packages', '--no-index', '--no-deps',
                '--no-cache-dir', '--disable-pip-version-check', str(wheel)], check=True)
subprocess.run([sys.executable, '-I', '-c',
                'from python_socks.async_.asyncio import Proxy; import python_socks; '
                'assert python_socks.__version__ == "3.2.1"; assert callable(Proxy.from_url)'], check=True)
print('\n语音代理组件已补齐。请完全退出客户端后重新打开，再点击「开始通话」。')
print('本次离线修复只安装语音连接依赖，没有修改学习记录、教材或已保存的 Key。')
PY
