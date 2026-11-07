"""Verify the approved source snapshot before unpacking it on a disposable runner."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--with-updates", action="store_true", help="Apply the latest developer fixes after verifying the installer baseline.")
options = parser.parse_args()
root = Path.cwd()
manifest = json.loads((root / "source-manifest.json").read_text())
destination = root / "student-source"
archive = root / "frozen-source.tar.gz"
digest = hashlib.sha256()
with archive.open("wb") as output:
    for part in manifest["parts"]:
        name = part["file"]
        assert Path(name).name == name and name.startswith("frozen-source.")
        data = (root / name).read_bytes()
        assert len(data) == part["bytes"] and hashlib.sha256(data).hexdigest() == part["sha256"]
        digest.update(data)
        output.write(data)
assert digest.hexdigest() == manifest["archiveSHA256"]
destination.mkdir()
with tarfile.open(archive) as package:
    package.extractall(destination, filter="data")
assert not (destination / "data/user").exists()
assert not (destination / "apps/desktop/.local").exists()
(destination / "SOURCE_FREEZE.json").write_text(json.dumps(manifest, indent=2))
for arguments in (["init"], ["config", "user.name", "Kaixin Student Builder"],
                  ["config", "user.email", "build@users.noreply.github.com"],
                  ["add", "--force", "."], ["commit", "-m", "Frozen student source " + manifest["commit"]]):
    subprocess.run(["git", "-C", str(destination), *arguments], check=True)
print("Verified credential-free source snapshot", manifest["commit"])

if options.with_updates:
    update = manifest["sourceUpdate"]
    patch = root / update["file"]
    if hashlib.sha256(patch.read_bytes()).hexdigest() != update["sha256"]:
        raise ValueError("Student source update checksum mismatch")
    for arguments in (["apply", "--index", str(patch)], ["commit", "-m", update["description"]]):
        subprocess.run(["git", "-C", str(destination), *arguments], check=True)
    print("Applied student source update", update["sha256"])
