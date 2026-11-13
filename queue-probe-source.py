"""Bounded local uploads. Original bytes are usable before parsing/indexing."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import errno
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import unquote, urlsplit
import uuid

from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.storage import LocalDiskAttachmentStore, get_attachment_store
from deeptutor.utils.document_extractor import is_document_extension
from deeptutor.utils.document_images import SUPPORTED_IMAGE_EXTENSIONS

CHUNK_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024 * 1024
MAX_PARTS = 64
PENDING = "_pending"
_ID = re.compile(r"^[0-9a-f]{32}$")
_TEXT = {".txt", ".md", ".markdown", ".log"}


def store() -> LocalDiskAttachmentStore:
    value = get_attachment_store()
    if not isinstance(value, LocalDiskAttachmentStore):
        raise ValueError("当前附件存储不支持本机分段上传。")
    return value


def directory(upload_id: str) -> Path:
    if not _ID.fullmatch(upload_id):
        raise ValueError("上传编号不正确。")
    root = store().root / ".uploads"
    target = root / upload_id
    if root.is_symlink() or target.is_symlink():
        raise ValueError("上传目录不正确。")
    return target


def read(upload_id: str, name="upload.json") -> dict:
    try:
        return json.loads((directory(upload_id) / name).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise LookupError("上传记录不存在，请重新选择文件。") from None


def begin(filename: str, size: int, retention: str) -> dict:
    from deeptutor.utils.filenames import safe_filename
    filename = safe_filename(Path(filename.replace("\\", "/")).name)
    if not filename or not (is_document_extension(filename) or Path(filename).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS):
        raise ValueError("不支持这种文件类型。")
    if not 0 < size <= MAX_SOURCE_BYTES:
        raise ValueError("文件为空或超过单份原件 1 GB 上限。")
    limits = get_chat_attachment_limits()
    limit = min(limits.max_file_bytes, limits.max_total_bytes, 200 * 1024 * 1024)
    suffix = Path(filename).suffix.lower()
    if size > limit and suffix not in _TEXT | {".pdf"}:
        raise ValueError("这种格式暂不能无损自动拆分；请导出为 PDF 或文本后再上传。")
    if retention not in {"temporary", "library"}:
        raise ValueError("附件保存方式不正确。")
    cleanup_expired()
    upload_id = uuid.uuid4().hex
    target = directory(upload_id)
    target.mkdir(parents=True, mode=0o700)
    chunk_bytes = min(CHUNK_BYTES, limit)
    result = {"upload_id": upload_id, "filename": filename, "size": size, "retention": retention,
              "chunk_bytes": chunk_bytes, "chunks": math.ceil(size / chunk_bytes), "part_limit": limit,
              "created_at": time.time()}
    atomic_write_json(target / "upload.json", result)
    return result


def pdf_counts(paths: list[Path]) -> list[int | None]:
    import pymupdf
    counts = []
    for path in paths:
        if path.suffix.lower() != ".pdf":
            counts.append(None)
            continue
        with pymupdf.open(path) as doc:
            if doc.needs_pass or not doc.page_count:
                raise ValueError("PDF 已加密或没有可读页面。")
            counts.append(doc.page_count)
    return counts


def expected_chunk(meta: dict, index: int) -> int:
    if not 0 <= index < meta["chunks"]:
        raise ValueError("分段编号超出范围。")
    return min(meta["chunk_bytes"], meta["size"] - index * meta["chunk_bytes"])


def _pdf_parts(source: Path, filename: str, limit: int, destination: Path) -> list[Path]:
    import pymupdf
    with pymupdf.open(source) as doc:
        if doc.needs_pass or not doc.page_count:
            raise ValueError("PDF 已加密或没有可读页面。")
        pages = max(1, int(doc.page_count * limit / max(source.stat().st_size, 1) * .85))
        output = []

        def emit(first, last):
            if len(output) >= MAX_PARTS:
                raise ValueError("拆分部分过多，请按章节分批选择。")
            target = destination / f"{Path(filename).stem}-第{first + 1:04d}-{last:04d}页.pdf"
            with pymupdf.open() as part:
                part.insert_pdf(doc, from_page=first, to_page=last - 1)
                part.set_metadata(doc.metadata)
                part.save(target, garbage=3, deflate=True)
            if target.stat().st_size <= limit:
                output.append(target)
            else:
                target.unlink()
                if last - first == 1:
                    raise ValueError(f"第 {first + 1} 页本身已超限，无法在不降低清晰度的情况下继续拆分。")
                middle = (first + last) // 2
                emit(first, middle)
                emit(middle, last)

        for first in range(0, doc.page_count, pages):
            emit(first, min(doc.page_count, first + pages))
        return output


def split_source(source: Path, filename: str, limit: int, destination: Path) -> list[Path]:
    """PDFs split at page boundaries; text splits at UTF-8 code-point boundaries."""
    if source.stat().st_size <= limit:
        return [source]
    if source.suffix.lower() == ".pdf":
        return _pdf_parts(source, filename, limit, destination)
    if source.suffix.lower() not in _TEXT:
        raise ValueError("文件超过上限，无法无损拆分这种格式。")
    # Strict UTF-8 avoids silently corrupting non-UTF-8 source documents.
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    output = []
    carry = b""
    with source.open("rb") as stream:
        while data := stream.read(min(limit, 1024 * 1024)):
            carry += decoder.decode(data).encode("utf-8")
            while len(carry) >= limit:
                end = limit
                while end and end < len(carry) and carry[end] & 0xC0 == 0x80:
                    end -= 1
                if not end:
                    raise ValueError("单个字符超过当前分段上限。")
                target = destination / f"{Path(filename).stem}-第{len(output) + 1:03d}部分{source.suffix}"
                target.write_bytes(carry[:end]); output.append(target); carry = carry[end:]
                if len(output) > MAX_PARTS:
                    raise ValueError("拆分部分过多，请分批上传。")
        carry += decoder.decode(b"", final=True).encode("utf-8")
    if carry:
        if len(output) >= MAX_PARTS:
            raise ValueError("拆分部分过多，请分批上传。")
        target = destination / f"{Path(filename).stem}-第{len(output) + 1:03d}部分{source.suffix}"
        target.write_bytes(carry); output.append(target)
    return output


async def finish(upload_id: str) -> dict:
    target = directory(upload_id)
    if (target / "result.json").is_file():
        return read(upload_id, "result.json")
    meta = read(upload_id)
    lock = target / "finishing"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("文件正在完成上传，请稍后重试。") from None
    os.close(fd)
    source = target / f"source{Path(meta['filename']).suffix.lower()}"
    try:
        def assemble():
            with source.open("wb") as output:
                for index in range(meta["chunks"]):
                    chunk = target / f"{index}.chunk"
                    if not chunk.is_file() or chunk.stat().st_size != expected_chunk(meta, index):
                        raise ValueError("上传分段不完整，请重试。")
                    with chunk.open("rb") as handle:
                        shutil.copyfileobj(handle, output, 1024 * 1024)
            limits = get_chat_attachment_limits()
            return min(meta["part_limit"], limits.max_file_bytes, limits.max_total_bytes)

        limit = await asyncio.to_thread(assemble)
        if source.suffix == '.pdf' and source.stat().st_size > limit:
            from deeptutor.runtime.isolated_worker import IsolatedWorkerError, run_in_isolated_process
            try:
                paths = await run_in_isolated_process(
                    "deeptutor.services.student_learning.uploads:split_source", source, meta["filename"], limit, target
                )
            except IsolatedWorkerError as exc:
                raise ValueError(str(exc)) from None
        else:
            paths = await asyncio.to_thread(split_source, source, meta["filename"], limit, target)
        if (target / "cancelled").exists():
            raise ValueError("已取消上传。")
        from deeptutor.runtime.isolated_worker import run_in_isolated_process
        from deeptutor.runtime.isolated_worker import IsolatedWorkerError
        try:
            counts = await run_in_isolated_process("deeptutor.services.student_learning.uploads:pdf_counts", paths) if source.suffix == ".pdf" else [None] * len(paths)
        except IsolatedWorkerError as exc:
            raise ValueError(str(exc)) from None
        records = []
        for path, count in zip(paths, counts):
            filename = meta["filename"] if path == source else path.name
            attachment_id = uuid.uuid4().hex
            url = await store().import_file(session_id=PENDING, attachment_id=attachment_id, filename=filename, source=path)
            records.append({"id": attachment_id, "filename": filename, "url": url, "type": "file",
                            "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream", "size": path.stat().st_size,
                            **({"page_count": count} if count is not None else {})})
        result = {**meta, "records": records, "library_status": "saving" if meta["retention"] == "library" else "temporary"}
        atomic_write_json(target / "result.json", result)
        # The immutable pending store now owns the bytes; discard transfer copies.
        for file in target.iterdir():
            if file.is_file() and file.name not in {"upload.json", "result.json", "finishing"}:
                file.unlink()
        return result
    finally:
        lock.unlink(missing_ok=True)
        if (target / "cancelled").exists():
            for row in locals().get("records", []):
                await store().delete_attachment(PENDING, row["id"])
            shutil.rmtree(target, ignore_errors=True)


def cancel(upload_id: str) -> None:
    target = directory(upload_id)
    if not target.exists() or (target / "result.json").exists():
        return
    if (target / "finishing").exists():
        (target / "cancelled").touch()
    else:
        shutil.rmtree(target)


def file_for(record: dict) -> Path:
    target = store().resolve_path(session_id=PENDING, attachment_id=record["id"], filename=record["filename"])
    if target is None:
        raise LookupError("原件暂时不可用，请重新上传。")
    return target


async def process(result: dict) -> None:
    """Called only after the upload response; never run OCR inside admission."""
    from deeptutor.services.session.pdf_pages import parse_in_background
    if result["retention"] == "library":
        await _save_library(result)
    else:
        for row in result["records"]:
            await parse_in_background(file_for(row))


@asynccontextmanager
async def library_queue():
    # One native index per workspace; concurrent uploads keep their originals usable.
    path = store().root / ".library-upload.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+b") as handle:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                await asyncio.sleep(.2)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def _save_library(result: dict) -> None:
    from fastapi import BackgroundTasks, UploadFile
    from deeptutor.api.routers.student_learning import save_library_attachments
    from deeptutor.services.session.pdf_pages import background_parse_slot
    files = []
    try:
        async with library_queue(), background_parse_slot:
            files = [UploadFile(file=file_for(row).open("rb"), filename=row["filename"]) for row in result["records"]]
            tasks = BackgroundTasks()
            response = await save_library_attachments(tasks, files)
            payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else response
            result["library_result"] = {key: payload[key] for key in ("kb_name", "name", "task_id") if key in payload}
            atomic_write_json(directory(result["upload_id"]) / "result.json", result)
            await tasks()
            from deeptutor.multi_user.knowledge_access import current_kb_base_dir
            from deeptutor.knowledge.progress_tracker import ProgressTracker
            progress = ProgressTracker("我的上传资料", current_kb_base_dir()).get_progress() or {}
            if progress.get("task_id") != payload.get("task_id") or progress.get("stage") != "completed":
                raise ValueError("Library indexing did not complete")
            result["library_status"] = "saved"
            result.pop("library_error", None)
            atomic_write_json(directory(result["upload_id"]) / "result.json", result)
    except Exception as error:
        result["library_status"] = "failed"
        result["library_error"] = "长期资料已保留原件，但检索准备未完成，请稍后重试。"
        atomic_write_json(directory(result["upload_id"]) / "result.json", result)
        import logging
        logging.getLogger(__name__).warning("Library preparation failed (%s)", type(error).__name__)
    finally:
        for file in files:
            await file.close()


async def adopt(records: list[dict], session_id: str, attachment_store) -> dict[str, Path]:
    """Resolve references only inside this request's authorized content workspace."""
    if not isinstance(attachment_store, LocalDiskAttachmentStore):
        return {}
    paths = {}
    for record in records:
        parsed = urlsplit(str(record.get("url") or ""))
        pieces = [unquote(part) for part in parsed.path.split("/")]
        if len(pieces) == 6 and pieces[1:4] == ["files", "attachments", PENDING]:
            if parsed.scheme or parsed.netloc or pieces[4] != record["id"] or not _ID.fullmatch(pieces[4]):
                raise ValueError("附件引用不正确。")
            source = attachment_store.resolve_path(session_id=PENDING, attachment_id=record["id"], filename=record["filename"])
            if source is None or pieces[5] != record["filename"]:
                raise ValueError("附件尚未上传完成或已失效，请重新上传。")
            record["url"] = await attachment_store.import_file(session_id=session_id, attachment_id=record["id"], filename=record["filename"], source=source)
        path = attachment_store.resolve_path(session_id=session_id, attachment_id=record["id"], filename=record["filename"])
        if path is not None:
            paths[record["id"]] = path
    return paths


def select_requested_pages(records: list[dict], content: str) -> None:
    requested = re.findall(r"第\s*(\d{1,5})\s*页|\bp\.?\s*(\d{1,5})\b", content, re.IGNORECASE)
    pages = list(dict.fromkeys(int(a or b) for a, b in requested if int(a or b) > 0))[:2]
    for record in records:
        if not str(record.get('filename', '')).lower().endswith('.pdf'):
            continue
        if pages:
            part = re.search(r'-第(\d+)-(\d+)页\.pdf$', record['filename'], re.IGNORECASE)
            record['page_numbers'] = [p - int(part[1]) + 1 for p in pages if int(part[1]) <= p <= int(part[2])] if part else pages
        if record.get('page_numbers') == []:
            record['_defer_pdf'] = True


def library_uploads() -> list[dict]:
    root = store().root / ".uploads"
    rows = []
    if root.is_dir():
        for target in root.iterdir():
            if not target.is_symlink() and _ID.fullmatch(target.name) and (target / "result.json").is_file():
                row = read(target.name, "result.json")
                if row["retention"] == "library":
                    rows.append(row)
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


def cleanup_expired() -> None:
    root = store().root / ".uploads"
    if not root.is_dir():
        return
    for target in root.iterdir():
        if target.is_symlink() or not _ID.fullmatch(target.name):
            continue
        try:
            meta = read(target.name)
            if time.time() - meta["created_at"] < 7 * 86400:
                continue
            result = read(target.name, "result.json") if (target / "result.json").exists() else {}
            if result and meta["retention"] == "library":
                continue
            for row in result.get("records", []):
                file_for(row).unlink(missing_ok=True)
            shutil.rmtree(target)
        except (OSError, ValueError, LookupError):
            continue
