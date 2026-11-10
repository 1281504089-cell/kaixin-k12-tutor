from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import student_learning as api
from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.student_learning import reports


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from deeptutor.services import session, workspace
    from deeptutor.services.workspace import context
    from deeptutor.services.model_selection import llm
    from deeptutor.services.llm import config
    from deeptutor.multi_user import learning_access

    owner = ["a"]
    active = [""]
    stores = {name: SQLiteSessionStore(tmp_path / (name + ".sqlite3")) for name in ("", "math", "english")}

    def paths():
        value = PathService(workspace_root=tmp_path / owner[0])
        value.ensure_all_directories()
        return value

    @contextmanager
    def scope(key):
        previous, active[0] = active[0], key
        try:
            yield
        finally:
            active[0] = previous

    monkeypatch.setattr(reports, "get_account_path_service", paths)
    monkeypatch.setattr(context, "workspace_context", scope)
    monkeypatch.setattr(workspace, "get_content_workspace_service", lambda: SimpleNamespace(describe_catalog=lambda: {
        "root": str(tmp_path),
        "workspaces": [
            {"workspace_id": key, "display_name": name, "path": str(tmp_path / ("student-study-" + key)),
             "kind": "workspace", "status": "ready", "archived": False}
            for key, name in (("math", "数学"), ("english", "英语"))
        ],
    }))
    monkeypatch.setattr(session, "get_session_store", lambda: stores[active[0]])
    monkeypatch.setattr(learning_access, "learning_surface_allowed", lambda _: True)
    monkeypatch.setattr(llm, "list_llm_options", lambda _: {"options": []})
    monkeypatch.setattr(config, "get_llm_config", lambda: config.LLMConfig(model="synthetic-model", api_key="no-key", base_url="http://127.0.0.1:1"))
    monkeypatch.setenv("PATH", "/Users/Admin1/.local/bin:" + os.environ.get("PATH", ""))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/student")
    return SimpleNamespace(client=TestClient(app), owner=owner, stores=stores, paths=paths)


PERIOD = reports.ReportRange(from_date="2024-02-28", to_date="2024-02-29")


async def seed(f, *, workspace="", sid="fractions", role="user", content="请解释异分母分数相加，1/2+1/3为什么要通分？", at="2024-02-27T16:30:00+00:00", parent=None, attachments=None, metadata=None):
    store = f.stores[workspace]
    if await store.get_session(sid) is None:
        await store.create_session(title="分数学习", session_id=sid)
    kwargs = {"attachments": attachments} if attachments else {}
    if metadata is not None:
        kwargs["metadata"] = metadata
    if parent is not None:
        kwargs["parent_message_id"] = parent
    mid = await store.add_message(sid, role, content, **kwargs)
    with store._connect() as conn:
        conn.execute("UPDATE messages SET created_at=? WHERE id=?", (datetime.fromisoformat(at).timestamp(), mid))
    return mid


def output():
    return {"overview": {"text": "记录中讨论了异分母分数加法。", "refs": ["m1"]}, "records": [{"subject": "数学", "title": "异分母分数加法", "text": "学生请求解释通分的原因。", "refs": ["m1"]}], "observations": [], "knowledgeCandidates": [], "goal": None, "nextSteps": [{"text": "可以用同样大小的小格子表示两种分数。", "refs": ["m1"]}]}


@pytest.mark.parametrize("start,end", [("2024-02-30", "2024-03-01"), ("2024-02-01", "2024-02-29"), ("2024-03-02", "2024-03-01"), ("2099-01-01", "2099-01-02"), ("20240228", "2024-02-29")])
def test_bad_dates_do_not_admit_work(start, end):
    with pytest.raises(ValueError):
        reports.ReportRange(from_date=start, to_date=end)


def test_day_and_leap_ranges_are_valid():
    assert reports.ReportRange(from_date="2024-02-29", to_date="2024-02-29").payload() == {"from": "2024-02-29", "to": "2024-02-29"}


@pytest.mark.asyncio
async def test_collects_nine_subject_scopes_with_beijing_dates_and_latest_branch(setup):
    question = await seed(setup)
    await seed(setup, role="assistant", content="旧分支：2/5", parent=question)
    await seed(setup, role="assistant", content="新分支：先通分得到5/6。", parent=question)
    await seed(setup, workspace="math", sid="same-id", content="我想看看一个例子。")
    await seed(setup, sid="outside", content="范围外", at="2024-02-27T15:59:59+00:00")
    await seed(setup, sid="deleted", content="已删除的资料")
    await setup.stores[""].soft_delete_session("deleted")
    source = await reports.collect(PERIOD)
    assert len(source["messages"]) == 3
    assert {m["date"] for m in source["messages"]} == {"2024-02-28"}
    assert {m["projectName"] for m in source["messages"]} == {"数学", "未归类对话"}
    assert not any("旧分支" in m["content"] or "已删除" in m["content"] for m in source["messages"])
    assert source["metrics"]["minutes"] is None and source["metrics"]["accuracy"] is None


@pytest.mark.asyncio
async def test_selected_branch_and_material_permissions_match_native_learning_view(setup, monkeypatch):
    from deeptutor.multi_user import learning_access
    question = await seed(setup)
    chosen = await seed(setup, role="assistant", content="学生选择保留的旧回答。", parent=question)
    await seed(setup, role="assistant", content="未选择的新回答。", parent=question)
    await setup.stores[""].update_session_preferences("fractions", {"selected_branches": {str(question): chosen}})
    source = await reports.collect(PERIOD)
    assert any("保留的旧回答" in m["content"] for m in source["messages"])
    assert not any("未选择的新回答" in m["content"] for m in source["messages"])
    await setup.stores[""].update_session_preferences("fractions", {"workspace_mode": "immersive_reading", "reading_material_id": "unassigned"})
    monkeypatch.setattr(learning_access, "learning_material_allowed", lambda _: False)
    assert not (await reports.collect(PERIOD))["messages"]


@pytest.mark.asyncio
async def test_generation_is_two_calls_high_and_reading_or_repeating_does_not_call_model(setup):
    await seed(setup)
    await seed(setup, role="assistant", content="把分母化成6，1/2+1/3=3/6+2/6=5/6。")
    row, task = await reports.begin(PERIOD)
    assert task[-1].reasoning_effort == "high"
    assert task[-1].max_tokens == 16384
    repeat, duplicate = await reports.begin(PERIOD)
    assert repeat["id"] == row["id"] and duplicate is None
    complete = AsyncMock(side_effect=[json.dumps(output(), ensure_ascii=False), '{"approved":true,"issues":[]}'])
    await reports.generate(*task, complete=complete)
    actual = await reports.detail(row["id"])
    assert actual["state"] == "ready" and complete.await_count == 2
    assert "独立审核" in complete.call_args_list[1].args[0]
    claim = actual["summary"]["records"][0]
    assert len(claim["refs"]) == 1 and len(claim["contextRefs"]) == 2
    assert actual["metrics"]["exercise_count"] is None
    assert (await reports.begin(PERIOD))[1] is None
    assert (await reports.overview(PERIOD))["report"]["id"] == row["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("answers,calls", [(["not JSON"], 1), ([json.dumps({**output(), "overview": {"text": "胡编", "refs": ["unknown"]}})], 1), ([json.dumps(output()), '{"approved":false,"issues":["缺少依据"]}'], 2)])
async def test_bad_json_refs_or_independent_review_never_publish_a_draft(setup, answers, calls):
    await seed(setup)
    row, task = await reports.begin(PERIOD)
    complete = AsyncMock(side_effect=answers)
    await reports.generate(*task, complete=complete)
    actual = await reports.detail(row["id"])
    assert actual["state"] == "failed" and "summary" not in actual
    assert complete.await_count == calls
    assert (await setup.stores[""].get_last_message("fractions"))["content"].startswith("请解释")


@pytest.mark.asyncio
async def test_new_messages_make_a_snapshot_stale_and_deletion_removes_its_evidence(setup):
    await seed(setup)
    row, task = await reports.begin(PERIOD)
    await reports.generate(*task, complete=AsyncMock(side_effect=[json.dumps(output()), '{"approved":true,"issues":[]}']))
    await seed(setup, content="我还想了解分母的含义。")
    assert (await reports.detail(row["id"]))["stale"]
    await setup.stores[""].soft_delete_session("fractions")
    with pytest.raises(reports.ReportError, match="原文"):
        await reports.detail(row["id"])
    manager, notebook = reports.storage()
    raw = reports.unpack(manager.get_record(notebook, row["id"]))
    assert raw["summary"] is None and raw["evidence"] == []


@pytest.mark.asyncio
async def test_other_account_cannot_read_a_report_and_late_completion_cannot_restore_it(setup):
    await seed(setup)
    row, task = await reports.begin(PERIOD)
    setup.owner[0] = "b"
    with pytest.raises(reports.ReportError):
        await reports.detail(row["id"])
    setup.owner[0] = "a"
    async def complete(*_):
        reports.remove(row["id"])
        return json.dumps(output())
    await reports.generate(*task, complete=complete)
    assert (await reports.overview(PERIOD))["history"] == []


@pytest.mark.asyncio
async def test_over_budget_sources_fail_before_any_model_request(setup):
    await seed(setup, content="完整题干" * 26000)
    with pytest.raises(reports.ReportError) as exc:
        await reports.begin(PERIOD)
    assert exc.value.status == 413
    assert reports.rows(*reports.storage()) == []


@pytest.mark.asyncio
async def test_empty_and_interrupted_reports_are_explicit(setup, monkeypatch):
    assert (await reports.overview(PERIOD))["report"] is None
    with pytest.raises(reports.ReportError, match="没有可整理"):
        await reports.begin(PERIOD)
    await seed(setup)
    row, _ = await reports.begin(PERIOD)
    monkeypatch.setattr(reports, "BOOT", "a-new-process")
    assert (await reports.detail(row["id"]))["state"] == "failed"


def test_http_date_validation_and_report_ids_do_not_expose_paths(setup):
    assert setup.client.get("/api/student/reports?from_date=2024-02-30&to_date=2024-03-01").status_code == 422
    assert setup.client.post("/api/student/reports", json={"from_date": "2024-02-28", "to_date": "2024-02-29", "user_id": "b"}).status_code == 422
    assert setup.client.get("/api/student/reports/foreign").status_code == 404


def test_report_permissions_follow_chat_surface_without_prefix_collisions():
    from deeptutor.api.routers.auth import _learning_surface_for_path
    assert _learning_surface_for_path("/api/student/reports", "GET") == "chat"
    assert _learning_surface_for_path("/api/student/reports/own", "GET") == "chat"
    assert _learning_surface_for_path("/api/student/reports-private", "GET") == ""


@pytest.mark.asyncio
async def test_four_reflections_are_scoped_self_reports_not_backdated_messages_or_scores(setup, monkeypatch):
    from deeptutor.services.llm import config
    monkeypatch.setattr(config, "get_llm_config", lambda: pytest.fail("Saving a reflection must not call a model"))
    body = reports.Reflection(from_date=PERIOD.from_date, to_date=PERIOD.to_date, goal="想理解通分", state="能跟着看，还没有自己重做", process="听过老师讲解", adjustment="计划明天重试，尚未执行")
    saved = reports.save_reflection(body)
    assert saved["revision"] == 1
    source = await reports.collect(PERIOD)
    assert source["metrics"]["message_count"] == 0
    assert source["metrics"]["active_days"] == 0
    assert source["metrics"]["reflection_count"] == 1
    assert source["metrics"]["minutes"] is None
    row = source["messages"][0]
    assert row["date"] is None and row["kind"] == "student_reflection"
    assert row["scopeRange"] == PERIOD.payload()
    assert row["createdAt"].startswith(datetime.now(timezone.utc).date().isoformat())
    assert all(name in row["content"] for name in reports.REFLECTION_QUESTIONS.values())
    prepared = await reports.bridge("prepare", {"source": source})
    assert "保存时间" in prepared["system"] and "学生自报" in prepared["system"]


def test_reflection_revision_reuse_account_isolation_and_http_save(setup):
    body = {"from_date": PERIOD.from_date, "to_date": PERIOD.to_date, "revision": 0, "goal": "想理解分数"}
    first = setup.client.put("/api/student/reports/reflection", json=body)
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert setup.client.put("/api/student/reports/reflection", json=body).status_code == 409
    same = setup.client.put("/api/student/reports/reflection", json={**body, "revision": 1})
    assert same.json()["revision"] == 1
    assert setup.client.delete("/api/student/reports/" + first.json()["id"]).status_code == 404
    assert reports.reflection(PERIOD)["answers"]["goal"] == body["goal"]
    setup.owner[0] = "b"
    assert reports.reflection(PERIOD)["revision"] == 0


@pytest.mark.asyncio
async def test_modified_reflection_invalidates_a_saved_report(setup):
    await seed(setup)
    reports.save_reflection(reports.Reflection(from_date=PERIOD.from_date, to_date=PERIOD.to_date, goal="想理解分数"))
    row, task = await reports.begin(PERIOD)
    await reports.generate(*task, complete=AsyncMock(side_effect=[json.dumps(output()), '{"approved":true,"issues":[]}']))
    reports.save_reflection(reports.Reflection(from_date=PERIOD.from_date, to_date=PERIOD.to_date, revision=1, goal="原补充需要更正"))
    with pytest.raises(reports.ReportError):
        await reports.detail(row["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("subject,heading,count", [("english", "八章", 7), ("math", "九章节", 10)])
async def test_subject_review_has_its_own_skill_sources_reflection_and_exercises(setup, subject, heading, count):
    other = "english" if subject == "math" else "math"
    await seed(setup, workspace=other, content="其他学科原文")
    await seed(setup, content="未归类原文")
    question = await seed(setup, workspace=subject, at="2024-02-29T15:59:00+00:00")
    await seed(setup, workspace=subject, parent=question, role="assistant", content="次日零点回答", at="2024-02-29T16:01:00+00:00")
    period = reports.ReportRange(**PERIOD.model_dump(exclude={"subject"}), subject=subject)
    reports.save_reflection(reports.Reflection(**period.model_dump(), goal="本学科目标"))
    assert reports.reflection(PERIOD)["revision"] == 0
    source = await reports.collect(period)
    assert len(source["messages"]) == 3
    assert source["messages"][1]["content"] == "次日零点回答"
    assert source["messages"][1]["reviewDate"] == "2024-02-29"
    assert source["messages"][2]["kind"] == "student_reflection"
    prepared = await reports.bridge("prepare", {"source": source})
    assert heading in prepared["system"]
    assert len(prepared["input"]["headings"]) == (8 if subject == "english" else 9)
    assert all(x not in json.dumps(prepared["input"], ensure_ascii=False) for x in ("其他学科原文", "未归类原文"))

    kinds = (["choice"] * 4 + ["fill"] * 4 + ["solution"] * 2) if subject == "math" else ["fill"] * count
    candidate = {
        "title": "学科复盘", "cover": "根据选定的学科对话回顾", "weaknesses": [],
        "learningSummary": ["先读题干。", "写出关键条件。", "独立练习。"],
        "sections": [{"text": "有对话记录。", "refs": ["m1"]} for _ in prepared["input"]["headings"]],
        "exercises": [
            {"id": i, "type": kind, "weaknessId": None, "question": "请写出一例。", "answer": "示例", "explanation": "核对题干。",
             "options": ["甲", "乙", "丙", "丁"] if kind == "choice" else []}
            for i, kind in enumerate(kinds, 1)
        ],
    }
    row, task = await reports.begin(period)
    complete = AsyncMock(side_effect=[json.dumps(candidate), '{"approved":true,"issues":[]}'])
    await reports.generate(*task, complete=complete)
    actual = await reports.detail(row["id"])
    assert actual["subject"] == subject and actual["result_level"] == "full"
    assert len(actual["subject_review"]["exercises"]) == count
    assert actual["subject_review"]["sections"][0]["refs"] == [actual["evidence"][0]["id"]]
    assert complete.await_count == 2
    assert (await reports.overview(PERIOD))["report"] is None


@pytest.mark.asyncio
async def test_subject_empty_model_body_keeps_readable_records_and_allows_retry(setup):
    await seed(setup, workspace="math")
    period = reports.ReportRange(**PERIOD.model_dump(exclude={"subject"}), subject="math")
    row, task = await reports.begin(period)
    complete = AsyncMock(return_value="")
    await reports.generate(*task, complete=complete)
    result = await reports.detail(row["id"])
    assert result["result_level"] == "records"
    review = result["subject_review"]
    assert len(review["sections"]) == 9 and len(review["exercises"]) == 10
    assert [exercise["type"] for exercise in review["exercises"]] == ["choice"] * 4 + ["fill"] * 4 + ["solution"] * 2
    assert "分数与通分" in review["title"]
    assert "没有返回报告正文" in result["message"]
    assert complete.await_count == 1
    assert (await reports.begin(period))[0]["id"] != row["id"]


@pytest.mark.asyncio
async def test_deepseek_report_budget_has_room_for_thinking_and_json(setup, monkeypatch):
    from deeptutor.services.llm import config
    monkeypatch.setattr(config, "get_llm_config", lambda: config.LLMConfig(model="deepseek-flash", api_key="no-key"))
    await seed(setup, workspace="math")
    _, task = await reports.begin(reports.ReportRange(**PERIOD.model_dump(exclude={"subject"}), subject="math"))
    assert task[-1].max_tokens == 32768
    assert task[-1].reasoning_effort == "high"


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["math", "english"])
async def test_manual_scope_adds_normal_and_reading_chats_without_changing_default(setup, monkeypatch, subject):
    from deeptutor.multi_user import learning_access
    from deeptutor.services.workspace import navigation

    other = "english" if subject == "math" else "math"
    await seed(setup, workspace=subject, sid="shared", content="默认学科项目")
    await seed(setup, sid="shared", content="手动补充普通聊天")
    await seed(setup, sid="ignored", content="未勾选的普通聊天")
    await seed(setup, workspace=other, sid="reader", content="手动补充边读边问")
    await setup.stores[other].update_session_preferences(
        "reader", {"session_kind": "immersive_reading", "reading_material_id": "book"}
    )
    await seed(setup, workspace=other, sid="blocked", content="不可访问的阅读对话")
    await setup.stores[other].update_session_preferences(
        "blocked", {"capability": "immersive_reading", "reading_material_id": "revoked"}
    )
    monkeypatch.setattr(learning_access, "learning_material_allowed", lambda key: key == "book")

    async def fixture_index(limit, offset):
        return {"sessions": [
            {**row, "content_workspace_id": workspace}
            for workspace, store in setup.stores.items()
            for row in await store.list_sessions(limit=limit, offset=offset)
        ]}

    monkeypatch.setattr(navigation, "session_index", fixture_index)
    listed = setup.client.get("/api/student/reports/sessions", params={"subject": subject})
    assert listed.status_code == 200
    options = {(row["workspace_id"], row["session_id"]): row["kind"] for row in listed.json()["sessions"]}
    assert options == {("", "shared"): "chat", ("", "ignored"): "chat", (other, "reader"): "reading"}

    refs = [
        {"workspace_id": "", "session_id": "shared"},
        {"workspace_id": other, "session_id": "reader"},
    ]
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject=subject)
    extra_period = reports.ReportRange(**{**period.model_dump(), "extra_sessions": [*refs, refs[0]]})
    assert {m["content"] for m in (await reports.collect(period))["messages"]} == {"默认学科项目"}
    assert {m["content"] for m in (await reports.collect(extra_period))["messages"]} == {
        "默认学科项目", "手动补充普通聊天", "手动补充边读边问",
    }
    overview = setup.client.get("/api/student/reports", params=[
        ("from_date", period.from_date), ("to_date", period.to_date), ("subject", subject),
        ("extra_session", ":shared"), ("extra_session", other + ":reader"),
    ])
    assert overview.status_code == 200 and overview.json()["metrics"]["conversation_count"] == 3

    row, task = await reports.begin(extra_period)
    await reports.generate(*task, complete=AsyncMock(return_value=""))
    result = await reports.detail(row["id"])
    assert result["extra_session_count"] == 2 and result["result_level"] == "records"
    assert (await reports.overview(period))["report"] is None
    assert (await reports.overview(extra_period))["report"]["id"] == row["id"]

    await setup.stores[other].soft_delete_session("reader")
    assert (await reports.collect(extra_period))["missing_extra_sessions"] == 1
    with pytest.raises(reports.ReportError, match="原文"):
        await reports.detail(row["id"])


@pytest.mark.asyncio
async def test_extra_sessions_outside_period_or_workspace_are_reported_before_model_use(setup):
    await seed(setup, sid="later", at="2024-03-01T16:30:00+00:00")
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="math", extra_sessions=[
        {"workspace_id": "", "session_id": "later"},
        {"workspace_id": "unknown", "session_id": "unauthorized"},
    ])
    assert (await reports.overview(period))["missing_extra_sessions"] == 2
    with pytest.raises(reports.ReportError, match="部分补充对话"):
        await reports.begin(period)


@pytest.mark.asyncio
async def test_empty_subject_can_create_complete_practice_report_without_a_model(setup):
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="english")
    row, task = await reports.begin(period)
    complete = AsyncMock()
    await reports.generate(*task, complete=complete)
    result = await reports.detail(row["id"])
    assert result["result_level"] == "records"
    assert len(result["subject_review"]["sections"]) == 8
    assert len(result["subject_review"]["exercises"]) == 7
    assert not result["evidence"]
    complete.assert_not_awaited()


def test_subject_evidence_keeps_whole_turns_under_the_model_budget():
    def entry(id, role, content):
        return {"id": id, "conversationId": "lesson", "role": role, "content": content}
    older = [entry("u1", "user", "旧题"), entry("a1", "assistant", "很长的旧答案" * 10000)]
    newer = [entry("u2", "user", "新题"), entry("a2", "assistant", "新答案")]
    sampled = reports.report_evidence(older + newer)
    assert sampled[0] == older[0] and sampled[-2:] == newer
    assert sampled[1]["content_excerpt"] and "中间原文略" in sampled[1]["content"]
    assert sampled[1]["source_digest"] == reports.digest(older[1])
    assert len(sampled[1]["content"]) < 4000


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["chinese", "physics", "chemistry", "biology", "history", "geography", "politics"])
async def test_additional_subjects_have_their_own_rule_and_complete_practice(setup, subject):
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject=subject)
    source = await reports.collect(period)
    prepared = await reports.bridge("prepare", {"source": source})
    assert ("记忆大纲" if subject in {"chinese", "history", "geography", "politics"} else "知识结构与关键概念") in prepared["input"]["headings"][1]
    assert "三道" in prepared["system"] and "textbookScope" in prepared["reviewSystem"]
    draft = await reports.bridge("records", {"source": source})
    for heading in ("核心知识点", "常见考法", "易错点与纠正"):
        assert heading in prepared["system"]
        assert any(heading in section["text"] for section in draft["sections"])
    assert len(draft["sections"]) == 7
    assert len(draft["learningSummary"]) == 3
    assert len(draft["exercises"]) == 3
    assert all(exercise["answer"] and exercise["explanation"] for exercise in draft["exercises"])


@pytest.mark.asyncio
async def test_review_uses_actual_pdf_outline_and_places_word_evidence_after_the_answers(setup, monkeypatch, tmp_path):
    import io
    import zipfile
    from xml.etree import ElementTree as ET

    import pymupdf
    from deeptutor.reading import ReadingStore
    from deeptutor.services.student_learning import report_textbooks

    path = tmp_path / "现代史.pdf"
    with pymupdf.open() as pdf:
        for line in ("Contents", "Xinhai Revolution", "May Fourth Movement"):
            pdf.new_page().insert_text((72, 72), line)
        pdf.set_toc([[1, "辛亥革命", 2], [1, "五四运动", 3]])
        pdf.save(path)
    store = ReadingStore(tmp_path / "reading")
    book = store.ingest(path)
    monkeypatch.setattr(report_textbooks, "ReadingStore", lambda: store)
    monkeypatch.setattr(report_textbooks, "learning_material_allowed", lambda _: True)
    monkeypatch.setattr(report_textbooks.textbooks, "catalog", lambda: {"books": []})
    reading = await seed(setup, content="辛亥革命的经过怎么记？", metadata={"request_snapshot": {
        "readingMaterialId": book.material_id, "readingMaterialRevision": book.revision, "readingViewport": {"locator": 2}
    }})
    assert reading
    extra = [reports.ReportSession(workspace_id="", session_id="fractions")]
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="history", extra_sessions=extra)
    row, task = await reports.begin(period)
    scope = task[3]["textbook_scope"]
    assert scope[0]["pages"] == [2] and scope[0]["outline"] == [{"title": "辛亥革命", "page": 2}]
    prepared = await reports.bridge("prepare", {"source": task[3]})
    assert prepared["input"]["textbookScope"][0]["matched"]
    assert "五四运动" not in json.dumps(prepared["input"]["textbookScope"], ensure_ascii=False)
    await reports.generate(*task, complete=AsyncMock(return_value=""))
    report = await reports.detail(row["id"])
    assert "辛亥革命" in report["subject_review"]["exercises"][0]["question"]
    assert report["textbook_scope"] == scope
    docx = await reports.export_word(row["id"])
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    w = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = root.findall(".//w:body/w:p", w)
    def page_text(rows):
        return " ".join(t.text or "" for p in rows for t in p.findall(".//w:t", w))

    appendix = next(i for i, p in enumerate(paragraphs) if "教材与记录依据" in page_text([p]))
    assert paragraphs[appendix].find("w:pPr/w:pageBreakBefore", w) is not None
    assert "记住这一点" in page_text(paragraphs[:appendix])
    assert "参考答案与解析" in page_text(paragraphs[:appendix])
    assert "下次复习怎么做" in page_text(paragraphs[:appendix])
    assert "PDF 第 2 页" in page_text(paragraphs[appendix:])

    selected = period.model_copy(update={"extra_sessions": [], "textbook_id": book.material_id})
    scoped = report_textbooks.report_textbook_scope(await reports.collect(selected))
    assert not scoped[0]["matched"] and scoped[0]["pages"] == []
    assert [row["title"] for row in scoped[0]["outline"]] == ["辛亥革命", "五四运动"]
    with pytest.raises(reports.ReportError, match="教材 PDF 无法读取"):
        await reports.begin(selected.model_copy(update={"textbook_id": "abcd1234"}))

@pytest.mark.asyncio
@pytest.mark.parametrize("extra_text", ["", "这一段是很长的学习记录。" * 10000])
async def test_short_and_oversized_records_generate_a_complete_export(setup, extra_text):
    original = "我想复习分数通分。" + extra_text
    await seed(setup, workspace="math", content=original)
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="math")
    row, task = await reports.begin(period)
    prepared = await reports.bridge("prepare", {"source": task[3]})
    messages = prepared["input"]["messages"]
    assert len(messages) == 1 and messages[0]["content"].startswith("我想复习分数通分")
    assert messages[0]["isExcerpt"] is bool(extra_text)
    assert len(messages[0]["content"]) < 4000
    complete = AsyncMock(side_effect=TimeoutError("model fixture timeout"))
    await reports.generate(*task, complete=complete)
    complete.assert_awaited_once()
    result = await reports.detail(row["id"])
    review = result["subject_review"]
    assert result["state"] == "ready" and result["result_level"] == "records"
    assert len(review["sections"]) == 9 and len(review["exercises"]) == 10
    assert all(question["answer"] and question["explanation"] for question in review["exercises"])
    assert (await reports.export_word(row["id"])).startswith(b"PK")
    if extra_text:
        assert "长记录节选" in review["cover"]
        assert result["evidence"][0]["content_excerpt"]
        fresh = await reports.collect(period)
        fresh["messages"][0]["content"] = original[:50000] + "这句变了" + original[50000:]
        assert not await reports.valid_sources(result, fresh)


def test_many_turns_cover_the_beginning_middle_and_end_of_the_selected_period():
    messages = [
        {"id": str(index), "conversationId": "lesson", "role": "user", "content": "复习要点" * 300}
        for index in range(220)
    ]
    sample = reports.report_evidence(messages)
    assert {0, 109, 219} <= {int(entry["id"]) for entry in sample}
    assert len(json.dumps(sample, ensure_ascii=False)) <= 52000
    assert len(sample) < len(messages)


def test_kimi_pro_high_is_scoped_to_subject_reports(setup, monkeypatch):
    from deeptutor.services.model_selection import llm, runtime
    from deeptutor.services.llm.config import LLMConfig

    kimi = LLMConfig(model="kimi-k3.1-pro", provider_name="moonshot", base_url="https://api.moonshot.cn/v1", api_key="fixture", reasoning_effort="low")
    monkeypatch.setattr(llm, "list_llm_options", lambda _: {"options": [
        {"provider": "moonshot", "model": "kimi-k3.1-pro-turbo", "profile_id": "kimi", "model_id": "turbo", "is_active_default": True},
        {"provider": "moonshot", "model": "kimi-k3.1-pro", "profile_id": "kimi", "model_id": "pro", "is_active_default": False},
    ]})

    def resolve(selection):
        assert selection.model_id == "pro"
        return kimi

    monkeypatch.setattr(runtime, "resolve_llm_config_for_selection", resolve)
    for subject in ("history", "physics"):
        config = reports.report_model_config(subject)
        assert (config.model, config.reasoning_effort) == ("kimi-k3.1-pro", "high")
    assert reports.report_model_config(None).model == "synthetic-model"
    kimi.api_key = ""
    assert reports.report_model_config("physics").model == "synthetic-model"


def test_printed_outline_finds_topic_on_continued_contents_page():
    from deeptutor.services.student_learning.report_textbooks import printed_outline

    pages = {
        1: "封面",
        2: "目录\n第一单元 晚清时期……1",
        3: "第11课 五四运动……64",
        4: "正文",
    }
    outline, matched = printed_outline(SimpleNamespace(unit_text=lambda _, page: pages[page]), "book", 4, "请讲讲五四运动。")
    assert matched
    assert outline == [{"title": "第11课 五四运动（印刷页 64）"}]


@pytest.mark.asyncio
async def test_subject_review_normalizes_model_exercise_labels(setup):
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="history")
    source = await reports.collect(period)
    result = await reports.bridge("records", {"source": source})
    result["exercises"][0].update(type="识记·单项选择", options=["A. 甲", "B. 乙", "C. 丙", "D. 丁"], answer="B")
    original_answer = result["exercises"][1]["answer"]
    result["exercises"][1].update(type="应用·材料分析", options=None, answer=None, solution=original_answer)
    normalized = await reports.bridge("validate", {"source": source, "raw": result})
    assert normalized["exercises"][0]["options"] == ["甲", "乙", "丙", "丁"]
    assert normalized["exercises"][0]["type"] == "choice"
    assert normalized["exercises"][1]["type"] == "solution"
    assert normalized["exercises"][1]["options"] == []
    assert normalized["exercises"][1]["answer"] == original_answer

    result["exercises"][0]["options"].pop()
    with pytest.raises(reports.ReportError):
        await reports.bridge("validate", {"source": source, "raw": result})


@pytest.mark.asyncio
@pytest.mark.parametrize("text_approved,figure_approved", [(True, True), (True, False), (False, True)])
async def test_report_only_displays_and_exports_a_reviewed_figure(setup, monkeypatch, text_approved, figure_approved):
    import base64
    from io import BytesIO
    from zipfile import ZipFile

    from PIL import Image
    from deeptutor.services.llm import factory
    from deeptutor.services.student_learning import report_figures

    await seed(setup, workspace="math", content="三角形的三条边在哪里？")
    period = reports.ReportRange(from_date=PERIOD.from_date, to_date=PERIOD.to_date, subject="math")
    row, task = await reports.begin(period)
    source = task[3]
    raw = await reports.bridge("records", {"source": source})
    raw["sections"][1]["text"] = "三角形的几何示意图用三条线段围成。"
    image = BytesIO()
    Image.new("RGB", (960, 480), "white").save(image, "PNG")
    monkeypatch.setattr(report_figures, "render_figure", lambda _: image.getvalue())
    monkeypatch.setattr(report_figures, "figure_model_config", lambda config: config)
    candidate = {"section": 1, "caption": "教学示意 · 三角形", "alt": "三个顶点依次连接形成三角形。",
                 "paths": [{"points": [[200, 300], [450, 80], [720, 300], [200, 300]], "tone": "blue", "style": "solid"}],
                 "labels": [{"at": [450, 48], "text": "A", "tone": "ink"}]}

    def review(approved):
        return {"approved": approved, "issues": [] if approved else ["与题设不符"]}

    complete = AsyncMock(side_effect=[json.dumps(x, ensure_ascii=False) for x in [
        raw, review(text_approved), {"figure": candidate}, review(figure_approved),
    ]])
    monkeypatch.setattr(factory, "complete_with_config", complete)
    await reports.generate(*task)
    result = await reports.detail(row["id"])
    assert result["state"] == "ready"
    assert result["result_level"] == ("full" if text_approved else "records")
    assert complete.await_count == (4 if text_approved else 2)

    shown = result["subject_review"].get("figure")
    if text_approved and figure_approved:
        assert shown["caption"] == candidate["caption"]
        assert base64.b64decode(shown["png"]) == image.getvalue()
    else:
        assert shown is None
    with ZipFile(BytesIO(await reports.export_word(row["id"]))) as word:
        xml = word.read("word/document.xml").decode()
        assert ("study-figure" in xml) is (shown is not None)
        if shown:
            assert xml.index(candidate["caption"]) < xml.index("教材与记录依据")


@pytest.mark.asyncio
async def test_report_skips_figures_for_text_only_and_non_science(setup, monkeypatch):
    from deeptutor.services.llm import factory
    from deeptutor.services.student_learning import report_figures

    complete = AsyncMock()
    monkeypatch.setattr(factory, "complete_with_config", complete)
    for subject, text in (("math", "用公分母统一计数单位。"), ("history", "结合图像讨论五四运动。")):
        result = await report_figures.build_figure({"subject": subject}, {"sections": [{"text": text}] * 9}, None, time_budget=240)
        assert result is None
    complete.assert_not_awaited()
