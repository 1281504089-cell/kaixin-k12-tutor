"""Offline spoken-audio probe; only public pinned models and a synthetic fixture."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request


async def probe():
    from deeptutor.services.local_ai import close_stt_worker, run_worker

    results = {}
    try:
        started = time.monotonic()
        await run_worker("stt", b"")
        results["warmup_seconds"] = time.monotonic() - started
        for name in ("first", "second"):
            started = time.monotonic()
            result = await run_worker("stt", Path(sys.argv[2]).read_bytes())
            text = result["text"]
            assert "数学题" in text and "分之" in text, text
            results[name] = {"seconds": time.monotonic() - started, "text": text}
        print(json.dumps(results, ensure_ascii=False), flush=True)
    finally:
        await close_stt_worker()


def main():
    source = Path.cwd()
    output = source.parent / "stt-evidence"
    output.mkdir(exist_ok=True)
    worker = source / "deeptutor/services/local_ai/worker.py"
    candidate = worker.read_bytes()
    baseline = (source.parent / "baseline-stt-worker.py").read_bytes()
    manifest = json.loads((source / "apps/desktop/student-models.json").read_text())
    with tempfile.TemporaryDirectory(prefix="kaixin-stt-") as temporary:
        root = Path(temporary)
        ascii_models = root / "ascii-models"
        chinese_models = root / "开心动力超级学霸/support/local-ai"
        for item in manifest["files"]:
            if not item["path"].startswith("sensevoice/"):
                continue
            target = ascii_models / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(item["url"], timeout=90) as response, target.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            with target.open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"]
            linked = chinese_models / item["path"]
            linked.parent.mkdir(parents=True, exist_ok=True)
            os.link(target, linked)

        import imageio_ffmpeg
        wav = root / "fixture.wav"
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-i", str(source / "scripts/fixtures/student-stt-cn.webm"),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(wav),
        ], check=True)
        cases = [
            ("baseline_ascii", baseline, ascii_models),
            ("baseline_chinese", baseline, chinese_models),
            ("candidate_chinese", candidate, chinese_models),
        ]
        results = {"platform": sys.platform, "python": sys.version, "cases": {}}
        try:
            for name, content, models in cases:
                worker.write_bytes(content)
                env = {**os.environ, "DEEPTUTOR_LOCAL_AI": str(models),
                       "DEEPTUTOR_HOME": str(root / "isolated-home"),
                       "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
                started = time.monotonic()
                completed = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--probe", str(wav)],
                    capture_output=True, env=env, timeout=180,
                )
                stdout = completed.stdout.decode("utf-8", errors="replace")
                stderr = completed.stderr.decode("utf-8", errors="replace")
                (output / f"{name}.stderr.txt").write_text(stderr, encoding="utf-8")
                row = {"ok": completed.returncode == 0, "returncode": completed.returncode,
                       "seconds": time.monotonic() - started}
                if row["ok"]:
                    row["result"] = json.loads(stdout)
                else:
                    row["stderr_tail"] = stderr[-4000:]
                results["cases"][name] = row
                (output / "spoken-stt.json").write_text(
                    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
                )
                print(name, json.dumps(row, ensure_ascii=False), flush=True)
        finally:
            worker.write_bytes(candidate)
        assert results["cases"]["baseline_ascii"]["ok"], "Baseline decoder itself failed"
        assert results["cases"]["candidate_chinese"]["ok"], "Candidate failed spoken Chinese-path probe"


if __name__ == "__main__":
    asyncio.run(probe()) if "--probe" in sys.argv else main()
