"""Evidence-backed daily/period reports over native local learning records."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import shutil
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from deeptutor.multi_user.paths import get_account_path_service
from deeptutor.services.notebook.service import NotebookManager

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).parent
LEASE = 420
BOOT = uuid.uuid4().hex
LOGGER = logging.getLogger(__name__)
ReportSubject = Literal["chinese", "math", "english", "physics", "chemistry", "biology", "history", "geography", "politics"]
REPORT_OUTPUT_TOKENS = 16384
DEEPSEEK_V4_REPORT_OUTPUT_TOKENS = 32768
DEEPSEEK_V4_REPORT_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro"}
MAX_EXTRA_SESSIONS = 20


class ReportError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class ReportSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: str = Field(max_length=128)
    session_id: str = Field(min_length=1, max_length=256)


class ReportRange(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_date: str
    to_date: str
    subject: ReportSubject | None = None
    textbook_id: str = Field(default="", pattern=r"^(?:[0-9a-f]{8,64})?$")
    extra_sessions: list[ReportSession] = Field(default_factory=list, max_length=MAX_EXTRA_SESSIONS)

    @model_validator(mode="after")
    def check_dates(self):
        try:
            start, end = date.fromisoformat(self.from_date), date.fromisoformat(self.to_date)
            if start.isoformat() != self.from_date or end.isoformat() != self.to_date:
                raise ValueError
            if not 1 <= (end - start).days + 1 <= 28 or end > datetime.now(TZ).date():
                raise ValueError
        except ValueError:
            raise ValueError("请选择截至今天的连续1至28天。") from None
        if (self.extra_sessions or self.textbook_id) and not self.subject:
            raise ValueError("请先选择复盘学科，再补充对话或选择教材。")
        self.extra_sessions = sorted(set(self.extra_sessions), key=lambda item: (item.workspace_id, item.session_id))
        return self

    def payload(self):
        return {"from": self.from_date, "to": self.to_date}


REFLECTION_QUESTIONS = {"goal": "目标管理", "state": "状态检查", "process": "过程感知", "adjustment": "及时调节"}


class Reflection(ReportRange):
    revision: int = Field(default=0, ge=0, strict=True)
    goal: str = Field(default="", max_length=1500)
    state: str = Field(default="", max_length=1500)
    process: str = Field(default="", max_length=1500)
    adjustment: str = Field(default="", max_length=1500)


def reflection(period: ReportRange):
    manager, notebook = storage()
    for record in manager.get_records(notebook):
        value = record.get("metadata", {}).get("student_reflection")
        if value and value["range"] == period.payload() and value.get("subject") == period.subject:
            return {"id": record["id"], **value}
    return {"revision": 0, "range": period.payload(), "answers": dict.fromkeys(REFLECTION_QUESTIONS, ""), "saved_at": None}


def save_reflection(body: Reflection):
    manager, notebook = storage()
    with manager._locked(notebook):
        current = reflection(body)
        if current["revision"] != body.revision:
            raise ReportError("这份复盘已在其他页面更新。当前填写已保留，请重新核对后保存。")
        answers = {key: getattr(body, key).strip() for key in REFLECTION_QUESTIONS}
        if answers == current["answers"]:
            return current
        value = {"range": body.payload(), "revision": body.revision + 1, "answers": answers, "saved_at": time.time()}
        if body.subject:
            value["subject"] = body.subject
        if current.get("id"):
            manager.update_record(notebook, current["id"], metadata={"student_reflection": value})
        else:
            manager.add_record([notebook], "chat", "四问复盘 · 学生自报", "", "", metadata={"student_reflection": value})
        return reflection(body)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def policy_version() -> str:
    files = [ROOT / "report-contract.cjs", ROOT / "reports.py", ROOT / "report_textbooks.py", *sorted((ROOT / "miniapp/reports").glob("*"))]
    return digest([hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()])


@lru_cache(maxsize=32)
def _manager(path: str):
    return NotebookManager(base_dir=Path(path))


def storage():
    # shortcut: one local API process, matching the existing student notebook stores.
    manager = _manager(str(get_account_path_service().get_notebook_dir() / "student-reports"))
    notebook = manager.get_or_create_notebook("学习报告", "有原文依据的日报与阶段报告。", "#537B69", "chart-no-axes-combined")
    return manager, notebook["id"]


def unpack(record):
    data = record["metadata"]["student_report"]
    return {"id": record["id"], "created_at": record["created_at"], **data}


def save(manager, notebook, row):
    saved = manager.update_record(notebook, row["id"], title=f"{row['range']['from']} — {row['range']['to']}", output="", metadata={"student_report": {k: v for k, v in row.items() if k not in {"id", "created_at"}}})
    return unpack(saved) if saved else None


def rows(manager, notebook):
    result = []
    with manager._locked(notebook):
        for record in manager.get_records(notebook):
            if "student_report" not in record.get("metadata", {}):
                continue
            row = unpack(record)
            if row["state"] == "pending" and (row["lease_until"] < time.time() or row.get("worker") != BOOT):
                row.update(state="failed", message="上次整理已中断，原记录保留。请手动重试。")
                save(manager, notebook, row)
            if row["state"] != "invalidated":
                result.append(row)
    return sorted(result, key=lambda r: r["created_at"], reverse=True)


def report_workspaces(subject: ReportSubject | None):
    from deeptutor.services.workspace import get_content_workspace_service

    catalog = get_content_workspace_service().describe_catalog()
    names = {"": "未归类对话"}
    defaults = {""} if subject is None else set()
    for row in catalog["workspaces"]:
        if row["kind"] != "workspace" or row["status"] != "ready" or row["archived"]:
            continue
        workspace = row["workspace_id"]
        names[workspace] = row["display_name"]
        if subject is None or Path(row["path"]) == Path(catalog["root"]) / ("student-study-" + subject):
            defaults.add(workspace)
    return names, defaults


def report_session_kind(session: dict) -> str | None:
    from deeptutor.multi_user.learning_access import learning_material_allowed, learning_surface_allowed

    prefs = session.get("preferences") or {}
    if prefs.get("archived"):
        return None
    if "immersive_reading" in (prefs.get("capability"), prefs.get("workspace_mode"), prefs.get("session_kind")):
        material = prefs.get("reading_material_id")
        if learning_surface_allowed("reading") and (not material or learning_material_allowed(material)):
            return "reading"
        return None
    return "chat" if learning_surface_allowed("chat") else None


async def available_sessions(subject: ReportSubject, offset: int):
    from deeptutor.services.workspace.navigation import session_index

    names, defaults = report_workspaces(subject)
    limit = 60
    page = await session_index(limit, offset)
    result = []
    for session in page["sessions"]:
        workspace = session["content_workspace_id"]
        if workspace not in names or workspace in defaults or not session.get("message_count"):
            continue
        kind = report_session_kind(session)
        if kind:
            result.append({
                "workspace_id": workspace, "session_id": session["session_id"],
                "title": session.get("title") or "学习对话", "workspace_name": names[workspace],
                "kind": kind, "updated_at": session["updated_at"],
            })
    return {"sessions": result, "next_offset": offset + limit if len(page["sessions"]) == limit else None}


async def collect(period: ReportRange) -> dict:
    from deeptutor.services.session import get_session_store
    from deeptutor.services.workspace.context import workspace_context

    names, defaults = report_workspaces(period.subject)
    extra_by_workspace: dict[str, list[str]] = {}
    for item in period.extra_sessions:
        extra_by_workspace.setdefault(item.workspace_id, []).append(item.session_id)
    missing = {(item.workspace_id, item.session_id) for item in period.extra_sessions}
    messages, seen, reading_sources = [], set(), {}
    for workspace, name in names.items():
        if workspace not in defaults and workspace not in extra_by_workspace:
            continue
        with workspace_context(workspace):
            store = get_session_store()
            if workspace in defaults:
                sessions = await store.list_sessions(limit=2001)
                if len(sessions) > 2000:
                    if not period.subject:
                        raise ReportError("对话记录较多，请先整理归档后再生成，不会静默遗漏记录。", 413)
                    while len(sessions) % 2001 == 0:
                        batch = await store.list_sessions(limit=2001, offset=len(sessions))
                        sessions.extend(batch)
                        if len(batch) < 2001:
                            break
            else:
                sessions = await store.get_session_summaries(extra_by_workspace[workspace], active_only=True)
            for session in sessions:
                sid = session["session_id"]
                identity = (str(getattr(store, "db_path", workspace)), sid)
                if identity in seen:
                    continue
                seen.add(identity)
                prefs = session.get("preferences", {})
                if not report_session_kind(session):
                    continue
                flat = await store.get_messages(sid)
                if not flat:
                    continue
                selected_ids = await bridge("path", {"messages": [{"id": m["id"], "parentMessageId": m.get("parent_message_id")} for m in flat], "selection": prefs.get("selected_branches", {})})
                by_id = {m["id"]: m for m in flat}
                path = [by_id[mid] for mid in selected_ids]
                turn_day = ""
                for message in path:
                    timestamp = message.get("created_at", 0)
                    day = datetime.fromtimestamp(timestamp, TZ).date().isoformat()
                    if message["role"] == "user":
                        turn_day = day
                    text = message.get("content", "")
                    scope_day = turn_day if period.subject else day
                    if period.subject and message["role"] == "user" and message.get("attachments") and not (isinstance(text, str) and text.strip()):
                        text = "（该条为图片或附件，报告未读取原件。）"
                    if not period.from_date <= scope_day <= period.to_date or message["role"] not in {"user", "assistant"} or not isinstance(text, str) or not text.strip():
                        continue
                    status = "complete"
                    if message["role"] == "assistant":
                        trace = await store.get_message_trace(sid, message["id"])
                        if trace and trace.get("turn_id"):
                            turn = await store.get_turn(trace["turn_id"])
                            if turn and turn["status"] != "completed":
                                status = "incomplete"
                    messages.append({"id": digest([workspace, sid, message["id"]])[:24], "message_id": str(message["id"]), "conversationId": digest([workspace, sid])[:24], "session_id": sid, "workspace_id": workspace, "projectName": name, "title": session.get("title", "学习对话"), "role": message["role"], "content": text, "createdAt": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), "date": day, "status": status, "has_images": bool(message.get("attachments"))})
                    if period.subject:
                        messages[-1]["reviewDate"] = scope_day
                    if message["role"] == "user":
                        missing.discard((workspace, sid))
                        if period.subject:
                            metadata = message.get("metadata") or {}
                            snapshot = metadata.get("request_snapshot") or metadata.get("requestSnapshot") or {}
                            material = snapshot.get("readingMaterialId")
                            if material:
                                reading_sources[messages[-1]["id"]] = (material, (snapshot.get("readingViewport") or {}).get("locator"), snapshot.get("readingMaterialRevision"))
                if not period.subject and (len(messages) > 240 or sum(len(m["content"]) for m in messages) > 100000):
                    raise ReportError("记录较多，请缩小日期范围；不会截掉题干后生成报告。", 413)
    messages.sort(key=lambda m: (m["createdAt"], m["conversationId"], int(m["message_id"])))
    start = date.fromisoformat(period.from_date)
    dates = [(start + timedelta(days=i)).isoformat() for i in range((date.fromisoformat(period.to_date) - start).days + 1)]
    fact_dates = sorted({m.get("reviewDate", m["date"]) for m in messages})
    source = {"range": period.payload(), "messages": messages, "coverage": {"factDates": fact_dates, "missingDates": [d for d in dates if d not in fact_dates], "partialDates": sorted({m.get("reviewDate", m["date"]) for m in messages if m["status"] != "complete" or m["has_images"]})}}
    if period.subject:
        source["subject"] = period.subject
    if reading_sources:
        source["reading_sources"] = reading_sources
    if period.textbook_id:
        source["textbook_id"] = period.textbook_id
    if period.extra_sessions:
        source["missing_extra_sessions"] = len(missing)
        source["extra_sessions"] = [item.model_dump() for item in period.extra_sessions]
    if not period.subject and len(json.dumps(source, ensure_ascii=False)) > 160000:
        raise ReportError("完整原文超出本次整理范围，请缩小日期范围。", 413)
    source["metrics"] = {"message_count": len(messages), "conversation_count": len({m["conversationId"] for m in messages}), "active_days": len({m["date"] for m in messages if m["role"] == "user"}), "minutes": None, "exercise_count": None, "accuracy": None}
    supplement = reflection(period)
    source["reflection"] = supplement
    source["metrics"]["reflection_count"] = int(any(supplement["answers"].values()))
    if source["metrics"]["reflection_count"]:
        # A retrospective statement has a declared scope and save time, not an invented learning date.
        stamp = datetime.fromtimestamp(supplement["saved_at"], timezone.utc).isoformat()
        messages.append({"id": f"reflection:{supplement['id']}:{supplement['revision']}", "role": "user", "content": "\n".join(f"{name}：{supplement['answers'][key]}" for key, name in REFLECTION_QUESTIONS.items() if supplement["answers"][key]), "kind": "student_reflection", "scopeRange": period.payload(), "date": None, "createdAt": stamp, "recordedAt": stamp, "conversationId": "student-reflection", "projectName": "四问复盘 · 学生自报", "title": "针对所选范围的补充，不是已验证的掌握记录", "status": "self_report", "has_images": False})
    if not period.subject and (sum(len(m["content"]) for m in messages) > 100000 or len(json.dumps({k: source[k] for k in ("range", "messages", "coverage")}, ensure_ascii=False)) > 160000):
        raise ReportError("完整原文与复盘补充较多，请缩小日期范围后再生成。", 413)
    source["fingerprint"] = digest({k: v for k, v in source.items() if k != "fingerprint"})
    return source


def report_evidence(messages: list[dict]) -> list[dict]:
    """Keep short records intact and fit a representative sample of long ones."""
    turns = []
    current = {}
    for message in messages:
        key = message["conversationId"]
        if message["role"] == "user" or key not in current:
            current[key] = []
            turns.append(current[key])
        current[key].append(message)

    if not turns:
        return []
    limit = 52000
    size = sum(len(json.dumps(turn, ensure_ascii=False)) for turn in turns)
    if size <= limit and len(messages) <= 180:
        return messages

    selected = {}
    size = 0
    newest = len(turns) - 1
    for index in dict.fromkeys([newest, 0, newest // 2, *range(newest - 1, -1, -1)]):
        turn = turns[index]
        count = len(json.dumps(turn, ensure_ascii=False))
        if count > limit // 3 or len(turn) > 60:
            turn = turn if len(turn) <= 3 else [turn[0], *turn[-2:]]
            compact = []
            for entry in turn:
                content = entry["content"]
                if len(content) > 4000:
                    head = content[:2800]
                    tail = content[-1000:]
                    # Prefer nearby line breaks without losing one-line records.
                    cut = head.rfind("\n", 2000)
                    start = tail.find("\n", 0, 250)
                    if cut >= 0:
                        head = head[:cut]
                    if start >= 0:
                        tail = tail[start + 1:]
                    entry = {**entry, "content": head + "\n\n〔中间原文略，完整内容见原对话〕\n\n" + tail,
                             "content_excerpt": True, "source_digest": digest(entry)}
                compact.append(entry)
            turn = compact
            count = len(json.dumps(turn, ensure_ascii=False))
        if size + count <= limit and len(selected) + len(turn) <= 180:
            size += count
            selected.update((entry["id"], entry) for entry in turn)
    return [selected[message["id"]] for message in messages if message["id"] in selected]


async def valid_sources(row: dict, source: dict) -> bool:
    from deeptutor.multi_user.learning_access import learning_material_allowed, learning_surface_allowed

    if row.get("textbook_scope") and (not learning_surface_allowed("reading") or any(
        not learning_material_allowed(book["material_id"]) for book in row["textbook_scope"]
    )):
        return False
    current = {m["id"]: m for m in source["messages"]}
    def matches(saved):
        original = current.get(saved["id"])
        if original is None:
            return False
        if saved.get("content_excerpt"):
            return saved.get("source_digest") == digest(original)
        return original == saved

    return not source.get("missing_extra_sessions") and all(matches(m) for m in row.get("evidence", []))


def saved_period(row: dict) -> ReportRange:
    return ReportRange(
        from_date=row["range"]["from"],
        to_date=row["range"]["to"],
        subject=row.get("subject"),
        textbook_id=row.get("textbook_id", ""),
        extra_sessions=row.get("extra_sessions", []),
    )


async def checked_rows():
    manager, notebook = storage()
    result, sources = [], {}
    for row in rows(manager, notebook):
        period = saved_period(row)
        key = period.model_dump_json()
        if key not in sources:
            try:
                sources[key] = await collect(period)
            except ReportError:
                sources[key] = None
        source = sources[key]
        if source is not None and not await valid_sources(row, source):
            with manager._locked(notebook):
                current = manager.get_record(notebook, row["id"])
                if current:
                    row.update(state="invalidated", summary=None, subject_review=None, evidence=[], message="原始记录已更改或移除，这份报告已失效。")
                    save(manager, notebook, row)
            continue
        result.append((row, source))
    return result


def public(row, *, stale=False, detail=False):
    result = {k: row[k] for k in ["id", "created_at", "range", "subject", "state", "stage", "message", "metrics", "result_level"] if k in row}
    if row.get("extra_sessions"):
        result["extra_session_count"] = len(row["extra_sessions"])
    result["stale"] = stale
    if detail and row["state"] == "ready":
        result.update(summary=row["summary"], evidence=row["evidence"], coverage=row["coverage"], textbook_scope=row.get("textbook_scope", []))
        if row.get("subject_review"):
            result["subject_review"] = row["subject_review"]
    return result


async def complete_saved_practice(row: dict) -> dict:
    review = row.get("subject_review")
    if row.get("result_level") != "records" or not review or review["exercises"]:
        return row
    source = {"subject": row["subject"], "range": row["range"], "messages": report_evidence(row["evidence"])}
    source["textbook_scope"] = row.get("textbook_scope", [])
    updated = await bridge("records", {"source": source})
    return {**row, "subject_review": updated, "message": "已根据保存的学习记录补齐知识点练习和答案，可下载 Word。"}


async def overview(period: ReportRange):
    source = await collect(period)
    reports = await checked_rows()
    matching = [(r, s) for r, s in reports if saved_period(r) == period]
    latest = matching[0][0] if matching and matching[0][1] is not None else None
    if latest:
        latest = await complete_saved_practice(latest)
    return {"range": period.payload(), "metrics": source["metrics"], "coverage": source["coverage"], "reflection": source["reflection"], "report": public(latest, stale=latest["fingerprint"] != source["fingerprint"] or latest["policy"] != policy_version(), detail=True) if latest else None, "history": [public(r) for r, _ in reports[:100]], "missing_extra_sessions": source.get("missing_extra_sessions", 0)}


async def detail(report_id: str):
    for row, source in await checked_rows():
        if row["id"] == report_id:
            if source is None:
                raise ReportError("当前无法重新核对原文，请缩小范围后再读取。", 413)
            row = await complete_saved_practice(row)
            return public(row, stale=row["fingerprint"] != source["fingerprint"] or row["policy"] != policy_version(), detail=True)
    raise ReportError("这份报告不存在，或原文已更改、移除。", 404)


def report_model_config(subject: ReportSubject | None):
    from deeptutor.services.llm.config import get_llm_config

    config = None
    if subject:
        from deeptutor.services.config.model_catalog import get_model_catalog_service
        from deeptutor.services.model_selection.llm import LLMSelection, list_llm_options
        from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

        options = list_llm_options(get_model_catalog_service().load())["options"]
        candidates = [option for option in options
                      if option["provider"] == "moonshot" and option["model"] == "kimi-k3.1-pro"]
        for option in sorted(candidates, key=lambda option: not option["is_active_default"]):
            try:
                preferred = resolve_llm_config_for_selection(
                    LLMSelection(profile_id=option["profile_id"], model_id=option["model_id"])
                )
            except (ValueError, LookupError):
                continue
            if (
                preferred.provider_name == "moonshot"
                and preferred.model == "kimi-k3.1-pro"
                and preferred.effective_url
                and preferred.get_api_key() not in {"", "no-key", "sk-no-key-required"}
            ):
                config = preferred
                break
    if config is None:
        config = get_llm_config()
    # Both synthesis and verification can use the output budget for reasoning.
    budget = DEEPSEEK_V4_REPORT_OUTPUT_TOKENS if config.model.lower() in DEEPSEEK_V4_REPORT_MODELS else REPORT_OUTPUT_TOKENS
    return config.model_copy(update={"reasoning_effort": "high", "max_tokens": max(config.max_tokens, budget)})


async def begin(period: ReportRange):
    source = await collect(period)
    if source.get("missing_extra_sessions"):
        raise ReportError("部分补充对话在所选日期内没有可用记录，请调整日期或取消勾选。", 422)
    if not period.subject and not any(m["role"] == "user" for m in source["messages"]):
        raise ReportError("这段时间还没有可整理的学习对话。先聊一道题或边读边问，再回来看看。", 422)
    if period.subject:
        total = len(source["messages"])
        source["messages"] = report_evidence(source["messages"])
        selected = len(source["messages"])
        excerpts = sum(bool(message.get("content_excerpt")) for message in source["messages"])
        if selected < total or excerpts:
            note = f"所选时段共有 {total} 条记录，本次参考其中 {selected} 条代表性记录"
            if excerpts:
                note += f"，其中 {excerpts} 条为长记录节选，完整内容保留在原对话"
            source["coverage"]["selectionNote"] = note
    if period.subject:
        from .report_textbooks import report_textbook_scope

        source["textbook_scope"] = await asyncio.to_thread(report_textbook_scope, source)
    manager, notebook = storage()
    version = policy_version()
    try:
        config = report_model_config(period.subject)
    except Exception:
        if not period.subject:
            raise ReportError("请先在维护设置连接已授权的聊天模型。", 503) from None
        config = None
    report_model = {"name": config.model, "provider": config.provider_name,
                    "effort": config.reasoning_effort} if config is not None else None
    with manager._locked(notebook):
        existing = rows(manager, notebook)
        exact = next((r for r in existing if r["fingerprint"] == source["fingerprint"] and r["policy"] == version and r.get("textbook_scope", []) == source.get("textbook_scope", []) and r.get("report_model") == report_model and r["state"] in {"pending", "ready"} and r.get("result_level") != "records"), None)
        if exact:
            return public(exact, detail=True), None
        if any(r["state"] == "pending" for r in existing):
            raise ReportError("已有一份报告正在整理，完成后再生成下一份。")
        if len(existing) >= 100:
            raise ReportError("已保存100份报告，请先导出并移除不再需要的报告。")
        data = {"range": period.payload(), "state": "pending", "stage": "generating", "message": "正在整理完整原文…", "worker": BOOT, "lease_until": time.time() + LEASE, "fingerprint": source["fingerprint"], "policy": version, "evidence": source["messages"], "coverage": source["coverage"], "metrics": source["metrics"], "summary": None}
        data["report_model"] = report_model
        if period.subject:
            data["subject"] = period.subject
        if period.textbook_id:
            data["textbook_id"] = period.textbook_id
        if source.get("textbook_scope"):
            data["textbook_scope"] = source["textbook_scope"]
        if period.extra_sessions:
            data["extra_sessions"] = [item.model_dump() for item in period.extra_sessions]
        added = manager.add_record([notebook], "chat", "学习报告", "", "", metadata={"student_report": data})
        row = unpack(added["record"])
    return public(row), (manager, notebook, row, source, config)


async def export_word(report_id: str) -> bytes:
    report = await detail(report_id)
    if report["state"] != "ready" or not report.get("subject_review"):
        raise ReportError("这份专项报告还没有可导出的正文。")
    return await bridge("word", report)


async def bridge(operation, data):
    node = shutil.which("node")
    if not node:
        raise ReportError("本机报告组件尚未就绪，请重新启动应用。")
    if operation == "word":
        entry = ROOT / "word-runtime.cjs"
        if not entry.is_file():
            entry = ROOT.parents[2] / "scripts/report-word/word-runtime.cjs"
        if not entry.is_file():
            raise ReportError("本机 Word 导出组件尚未安装。", 503)
        args = [str(entry)]
    else:
        args = [str(ROOT / "report-contract.cjs"), operation]
    process = await asyncio.create_subprocess_exec(node, *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, error = await asyncio.wait_for(process.communicate(json.dumps(data, ensure_ascii=False).encode()), 60 if operation == "word" else 15)
        if operation == "word":
            if process.returncode or not output.startswith(b"PK\x03\x04"):
                raise ReportError("这次未能生成 Word，请稍后重试。", 503)
            return output
        if process.returncode:
            if error == b"NO_REVIEW_EVIDENCE":
                raise ReportError("所选记录没有足够的本科学习依据，已保留原记录。")
            raise ReportError("报告内容或原文依据未通过校验，请核对原记录后手动重试。")
        return json.loads(output)
    except TimeoutError:
        if operation == "word":
            raise ReportError("Word 排版超时，请稍后重试。", 504) from None
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def generate(manager, notebook, row, source, config, complete=None):
    from deeptutor.services.llm.factory import complete_with_config
    from deeptutor.services.llm.metrics import TurnUsage, current_usage
    usage = TurnUsage(turn_id="student-report-" + row["id"], source="student_report")
    usage_token = current_usage.set(usage)
    stage = "generating"
    period = saved_period(row)
    complete_from_provider = complete is None
    has_model = config is not None or complete is not None
    if complete is None:
        async def complete(system, prompt):
            return await complete_with_config(config, prompt, system_prompt=system, max_retries=0, response_format={"type": "json_object"})

    async def read_output(system, prompt):
        text = (await complete(system, json.dumps(prompt, ensure_ascii=False))).strip()
        if not text:
            raise ReportError("模型没有返回报告正文，可能已用完本轮输出额度。")
        return json.loads(text.removeprefix("```json").removesuffix("```").strip())

    async def check_sources():
        current = await collect(period)
        changed = not await valid_sources(row, current) if period.subject else current["fingerprint"] != row["fingerprint"]
        if changed or policy_version() != row["policy"]:
            raise ReportError("整理期间原文或规则有更新，请重新生成。")

    try:
        async with asyncio.timeout(LEASE - 35):
            if period.subject and not any(m["role"] == "user" for m in source["messages"]) and not any(book["outline"] for book in source.get("textbook_scope", [])):
                raise ReportError("所选时段暂无可用于分析的学生原文。")
            if not has_model:
                raise ReportError("当前没有可用的报告模型。")
            prepared = await bridge("prepare", {"source": source})
            system = prepared["system"]
            if not period.subject:
                system += "\n整理所选日期的学习日报或阶段报告。仅返回规范JSON，每项refs用m编号；knowledgeCandidates=[]，goal=null，不生成数值统计。"
            raw = await read_output(system, prepared["input"])
            draft = await bridge("validate", {"source": source, "raw": raw})
            stage = "reviewing"
            with manager._locked(notebook):
                current = manager.get_record(notebook, row["id"])
                if not current or unpack(current)["state"] != "pending":
                    return
                save(manager, notebook, {**row, "stage": "reviewing", "message": "正在逐项核对原文依据…"})
            review_system = prepared.get("reviewSystem") or system + '\n独立审核候选报告。逐条核对日期、角色、题设、作答、计划和refs；contextRefs不能替代直接依据。仅返回{"approved":true,"issues":[]}，有任一确定问题则false及简短issues。'
            review = await read_output(review_system, {**prepared["input"], "draft": draft})
            if review.get("approved") is not True or review.get("issues") != []:
                raise ReportError("专项内容未通过独立核对。")
            summary = await bridge("finish", {"source": source, "draft": draft, "review": review})
            stage = "checking_sources"
            await check_sources()
            updates = {"state": "ready", "stage": None, "summary": None if period.subject else summary, "message": "已依据原文整理，并完成独立核对。"}
            if period.subject:
                if complete_from_provider and config is not None:
                    model_label = "Kimi K3.1 Pro" if config.model == "kimi-k3.1-pro" else config.model
                    summary["cover"] += "\n\n生成与核对模型：" + model_label + " · High"
                updates.update(subject_review=summary, result_level="full")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        LOGGER.warning("Student report %s stopped in %s (%s)", row["id"], stage, type(error).__name__)
        reason = str(error) if isinstance(error, ReportError) else (
            "模型返回的报告格式不完整。" if isinstance(error, json.JSONDecodeError) else
            "报告整理超时。" if isinstance(error, TimeoutError) else "这次整理或独立核对未完成。"
        )
        updates = {"state": "failed", "stage": None, "summary": None, "message": reason + "原记录保留，可手动重试。"}
        if period.subject and stage != "checking_sources":
            try:
                async with asyncio.timeout(25):
                    await check_sources()
                    record_review = await bridge("records", {"source": source})
                updates.update(state="ready", subject_review=record_review, result_level="records", message=reason + "已生成完整的知识点巩固版，含练习、答案和解析。")
            except Exception as fallback_error:
                LOGGER.warning("Student report %s could not build records (%s)", row["id"], type(fallback_error).__name__)
    finally:
        current_usage.reset(usage_token)
    updates["usage"] = usage.summary()
    with manager._locked(notebook):
        current = manager.get_record(notebook, row["id"])
        if current and unpack(current)["state"] == "pending":
            save(manager, notebook, {**unpack(current), **updates})


def remove(report_id: str):
    manager, notebook = storage()
    with manager._locked(notebook):
        record = manager.get_record(notebook, report_id)
        if not record or "student_report" not in record.get("metadata", {}):
            raise ReportError("报告不存在或已移除。", 404)
        manager.remove_record(notebook, report_id)
