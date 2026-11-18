"""Run fresh install and four upgrade checks on the existing Intel k12-10 assets."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    subprocess.run([sys.executable, str(Path(__file__).with_name('ci-mac-reuse.py')),
                    '--target', 'macos-x64', '--release-tag', 'student-20261117-k12-10'], check=True)
