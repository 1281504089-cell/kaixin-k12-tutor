"""Run fresh install and the remaining upgrade path on the existing Intel k12-11 assets."""
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    subprocess.run([sys.executable, str(Path(__file__).with_name('ci-mac-reuse.py')),
                    '--target', 'macos-x64', '--release-tag', 'student-20261117-k12-11'], check=True)
