"""Student notebook and read-only default-library endpoints."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response, UploadFile
from pydantic import Field

from deeptutor.services.student_learning import mistakes, reports, textbooks

router = APIRouter()


@router.post("/attachments/prepare")
async def prepare_temporary_attachment(file: UploadFile, background: BackgroundTasks):
    """Warm the same parser cache used by chat; never add uploads to the library."""
    import asyncio
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from deeptutor.modules.catalog import require_module
    from deeptutor.services.config.runtime_settings import get_chat_attachment_limits
    from deeptutor.services.parsing import get_parse_service
    from deeptutor.utils.document_extractor import is_document_extension

    name = Path((file.filename or "file").replace("\\", "/")).name
    if not is_document_extension(name):
        raise HTTPException(415, detail="Unsupported document type")
    temporary = TemporaryDirectory(prefix="student-attachment-")
    queued = False
    try:
        source = Path(temporary.name) / name
        size = 0
        limit = get_chat_attachment_limits().max_file_bytes
        with source.open("wb") as output:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, detail="Attachment too large")
                output.write(chunk)
        if source.suffix.lower() == ".pdf":
            from deeptutor.services.session.pdf_pages import parse_in_background, prepare_pdf_pages

            try:
                pages = await prepare_pdf_pages(source)
            except Exception:
                pages = {"images": []}
            if pages["images"]:
                background.add_task(parse_in_background, source, temporary)
                queued = True
                return {
                    "status": "ready",
                    "strategy": "vision",
                    "page_count": pages["page_count"],
                    "background_parsing": True,
                }
        require_module("parsing")
        parsed = await asyncio.to_thread(get_parse_service().parse, source)
        return {"status": "ready", "strategy": "document", "extracted_chars": len(parsed.markdown)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            422, detail="Document preparation failed; chat can retry with its normal fallback"
        ) from None
    finally:
        if not queued:
            temporary.cleanup()
        await file.close()


@router.get("/reports")
async def learning_reports(
    from_date: str,
    to_date: str,
    subject: reports.ReportSubject | None = None,
    extra_session: Annotated[list[str] | None, Query(max_length=reports.MAX_EXTRA_SESSIONS)] = None,
    textbook_id: Annotated[str, Query(pattern=r"^(?:[0-9a-f]{8,64})?$")] = "",
):
    try:
        extras = []
        for reference in extra_session or []:
            workspace, session = reference.split(":", 1)
            extras.append(reports.ReportSession(workspace_id=workspace, session_id=session))
    except ValueError:
        raise HTTPException(422, detail="补充对话格式不正确。") from None
    try:
        period = reports.ReportRange(from_date=from_date, to_date=to_date, subject=subject, extra_sessions=extras, textbook_id=textbook_id)
    except ValueError:
        raise HTTPException(422, detail="请选择截至今天的连续1至28天。") from None
    try:
        return await reports.overview(period)
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


@router.post("/reports")
async def generate_learning_report(body: reports.ReportRange, background: BackgroundTasks):
    try:
        result, task = await reports.begin(body)
        if task:
            background.add_task(reports.generate, *task)
        return result
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


@router.get("/reports/history")
async def learning_report_history():
    return [reports.public(row) for row, _ in (await reports.checked_rows())[:100]]


@router.get("/reports/sessions")
async def list_report_sessions(subject: reports.ReportSubject, offset: Annotated[int, Query(ge=0)] = 0):
    return await reports.available_sessions(subject, offset)


@router.get("/reports/{report_id}")
async def learning_report(report_id: str):
    try:
        return await reports.detail(report_id)
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


@router.get("/reports/{report_id}/word")
async def download_learning_report(report_id: str):
    try:
        content = await reports.export_word(report_id)
        return Response(content, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="learning-review.docx"'})
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from exc


@router.put("/reports/reflection")
def save_report_reflection(body: reports.Reflection):
    try:
        return reports.save_reflection(body)
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


@router.delete("/reports/{report_id}")
def remove_learning_report(report_id: str):
    try:
        reports.remove(report_id)
        return {"removed": True}
    except reports.ReportError as exc:
        raise HTTPException(exc.status, detail=str(exc)) from None


def _error(exc):
    return HTTPException(status_code=404 if isinstance(exc, LookupError) else 409, detail=str(exc))


class Capture(mistakes.StrictModel):
    session_id: str = Field(default="", max_length=128)
    message_id: str = Field(default="", max_length=128, pattern=r"^\d*$")
    excerpt: str = Field(default="", max_length=6000)
    image: str = Field(default="", max_length=12_000_000)
    title: str = Field(default="", max_length=100)


class Revision(mistakes.StrictModel):
    revision: int = Field(ge=1)


@router.get("/mistakes")
async def list_mistakes(practice: str = ""):
    if practice:
        try:
            return await mistakes.practice_source(practice)
        except (ValueError, LookupError) as exc:
            raise _error(exc) from None
    return {"records": mistakes.list_records(), "subjects": mistakes.SUBJECTS}


def _queue_mistake_analysis(record: dict, tasks: BackgroundTasks) -> dict:
    if record["status"] != "saved" or record.get("job"):
        return record
    if not (record["question"] or record["student_work"] or record["source"].get("images")):
        return record
    try:
        manager, notebook, pending = mistakes.begin(record["id"], record["revision"])
    except ValueError:
        return record
    tasks.add_task(mistakes.analyze, manager, notebook, pending)
    return pending


@router.post("/mistakes")
def create_mistake(body: mistakes.Amendment, tasks: BackgroundTasks):
    if not (body.title or body.question or body.student_work):
        raise HTTPException(422, detail="请至少填写一点题目信息")
    messages = [{"id": "manual-question", "role": "user", "content": body.question}]
    if body.student_work:
        messages.append({"id": "manual-work", "role": "user", "content": body.student_work})
    try:
        record = mistakes.create_record(
            {"messages": messages, "manual": True}, subject=body.subject, title=body.title or "手动记录"
        )
        if body.knowledge_point and not record["knowledge_point"]:
            body.revision = record["revision"]
            record = mistakes.amend(record["id"], body)
        return _queue_mistake_analysis(record, tasks)
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/mistakes/capture")
async def capture_mistake(body: Capture, tasks: BackgroundTasks):
    try:
        if body.session_id and body.message_id and not body.image:
            record = await mistakes.capture(body.session_id, body.message_id, body.excerpt)
        elif not body.session_id and not body.message_id:
            record = await mistakes.capture_reader_excerpt(body.excerpt, body.image, body.title)
        else:
            raise ValueError("缺少片段来源")
        return _queue_mistake_analysis(record, tasks)
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.put("/mistakes/{record_id}")
def amend_mistake(record_id: str, body: mistakes.Amendment):
    try:
        return mistakes.amend(record_id, body)
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.delete("/mistakes/{record_id}")
async def remove_mistake(record_id: str, body: Revision):
    try:
        await mistakes.remove(record_id, body.revision)
        return {"deleted": True}
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/mistakes/{record_id}/analyze")
def analyze_mistake(record_id: str, body: Revision, tasks: BackgroundTasks):
    try:
        manager, notebook, record = mistakes.begin(record_id, body.revision)
        tasks.add_task(mistakes.analyze, manager, notebook, record)
        return record
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.post("/mistakes/{record_id}/confirm")
def confirm_mistake(record_id: str, body: Revision):
    try:
        return mistakes.confirm(record_id, body.revision)
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None


@router.get("/textbooks")
def list_textbooks():
    return textbooks.catalog()


@router.post("/textbooks/{book_id}/open")
def open_textbook(book_id: str):
    try:
        return {"url": textbooks.reading_link(book_id)}
    except (ValueError, LookupError) as exc:
        raise _error(exc) from None
