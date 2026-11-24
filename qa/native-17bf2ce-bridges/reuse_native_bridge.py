"""Keep the verified native gzip members and append the newer frozen core."""
from collections import deque
from hashlib import file_digest, sha256
from pathlib import Path
import gzip
import json
import shutil
import sys
import tarfile
import zlib


class NativePrefix:
    def __init__(self, source, destination, boundary_member=None):
        self.source = source
        self.destination = destination
        self.boundary_member = boundary_member
        self.digest = sha256()
        self.source_bytes = 0
        self.raw_offset = 0
        self.tail = b""
        self.frames = deque()
        self.frame = memoryview(b"")

    def _read_source(self, size):
        piece = self.source.read(size)
        self.digest.update(piece)
        self.source_bytes += len(piece)
        return piece

    def _inflate_frame(self):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        pieces = []
        compressed = []
        while not decoder.eof:
            block = self.tail or self._read_source(1 << 20)
            assert block, "Gzip stream ended before native archive boundary"
            pieces.append(decoder.decompress(block))
            self.tail = decoder.unused_data
            compressed.append(block[:-len(self.tail)] if self.tail else block)
        raw = b"".join(pieces)
        if len(self.frames) == 3:
            self.destination.write(self.frames.popleft()[1])
        self.frames.append((self.raw_offset, b"".join(compressed), raw))
        self.raw_offset += len(raw)
        self.frame = memoryview(raw)

    def read(self, size):
        chunks = []
        while size:
            if not self.frame:
                self._inflate_frame()
            chunk = self.frame[:size]
            chunks.append(chunk)
            self.frame = self.frame[len(chunk):]
            size -= len(chunk)
        return b"".join(chunks)

    def cut(self, raw_boundary, expected):
        for raw_start, compressed, raw in self.frames:
            if raw_start + len(raw) < raw_boundary:
                self.destination.write(compressed)
                continue
            if raw_start <= raw_boundary <= raw_start + len(raw):
                remaining = raw[:raw_boundary - raw_start]
                if remaining:
                    if self.boundary_member is None:
                        compressed = gzip.compress(remaining, compresslevel=6, mtime=0)
                        # The frozen bridge was assembled with Darwin gzip OS byte 19.
                        compressed = compressed[:9] + bytes([19]) + compressed[10:]
                    else:
                        compressed = self.boundary_member
                        stream = zlib.decompressobj(16 + zlib.MAX_WBITS)
                        assert stream.decompress(compressed, len(remaining) + 1) == remaining
                        assert stream.eof and not stream.unused_data and not stream.unconsumed_tail
                    self.destination.write(compressed)
                break
        else:
            raise AssertionError("Native tar boundary outside the last decoded gzip frames")
        while self._read_source(4 << 20):
            pass
        assert self.source_bytes == expected["bytes"] and self.digest.hexdigest() == expected["sha256"]


def reuse(prior_path, prior, core_path, core, output, native_count, boundary_member=None):
    assert output.name != prior_path.name and not output.exists()
    temporary = output.with_suffix(output.suffix + ".partial")
    with gzip.open(core_path, "rb") as decoded, tarfile.open(fileobj=decoded, mode="r|") as tar:
        first_core_name = next(iter(tar)).name.removeprefix("./")
        assert first_core_name.startswith(("core/", "web/", "launcher/")) or first_core_name == "BUILD_COMMIT"
    with prior_path.open("rb") as source, temporary.open("xb") as destination:
        prefix = NativePrefix(source, destination, boundary_member)
        with tarfile.open(fileobj=prefix, mode="r|") as tar:
            for offset, member in enumerate(tar):
                if offset == native_count:
                    assert member.name.removeprefix("./") == first_core_name
                    prefix.cut(member.offset, prior)
                    break
                name = member.name.removeprefix("./")
                assert not name.startswith(("core/", "launcher/")) and name != "BUILD_COMMIT", name
            else:
                raise AssertionError("No verified native/core boundary")
        with core_path.open("rb") as archive:
            digest = sha256()
            written = 0
            while chunk := archive.read(4 << 20):
                digest.update(chunk)
                written += len(chunk)
                destination.write(chunk)
            assert written == core["bytes"] and digest.hexdigest() == core["sha256"]
    output_len = temporary.stat().st_size
    assert 0 < output_len < 2 * 1024**3
    with temporary.open("rb") as stream:
        output_digest = file_digest(stream, "sha256").hexdigest()
    temporary.rename(output)
    return {"name":output.name,"bytes":output_len,"sha256":output_digest}


def main(root, previous, target):
    def read(folder, name):
        return json.loads((folder / name).read_text())

    previous_proof = read(previous, f"bridge-{target}.json")
    new_core = read(root, "core-receipt.json")
    prior_core = read(previous, "core-receipt.json")
    assert prior_core["core"] == previous_proof["core"]
    plan = read(root, "release-lock.json")
    prior = previous_proof["bridge"]
    core = new_core["core"]
    new = root / "versioned" / f"kaixin-bridge-{plan['version']}-{target}.tar.gz"
    count = previous_proof["unchanged_native_entries"]
    bridge = reuse(previous / "versioned" / prior["name"],prior,root / "versioned" / core["name"],core,new,count)
    receipt = {**new_core, "bridge":bridge, "unchanged_native_entries":count,
               "web_dependencies":previous_proof["web_dependencies"],"native_prefix_reused":True}
    (root / f"bridge-{target}.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt),flush=True)


if __name__ == "__main__":
    main(Path.cwd(),Path(sys.argv[1]),sys.argv[2])
