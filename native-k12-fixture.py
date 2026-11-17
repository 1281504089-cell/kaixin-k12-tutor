"""Create source-link history only in an explicitly marked disposable QA home."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


async def seed(core):
    from deeptutor.services.student_learning import question_sources
    from deeptutor.services.session import get_sqlite_session_store
    pack = core / "deeptutor/services/student_learning/question_bank_data"
    manifest = question_sources.prepare(pack)
    with sqlite3.connect((pack / "index.sqlite3").resolve().as_uri() + "?mode=ro&immutable=1", uri=True) as conn:
        candidates = conn.execute("SELECT q.qualified_id FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha WHERE q.usable=1 ORDER BY (json_array_length(d.body_json,'$.assets')>0) DESC,q.qualified_id").fetchall()
    question = None
    for row in candidates:
        try:
            current = question_sources.detail(row[0], root=pack, revision=manifest["bank_revision"])
        except (FileNotFoundError, PermissionError):
            continue  # Use the same live permission/runtime-isolation boundary as API detail.
        if current.get("can_select_original") is True and not current["source"].get("picture"):
            question = current
            break
    assert question is not None, "No permitted current original exercise fixture"
    store = get_sqlite_session_store()
    session = await store.create_session("题库来源跳转合成验证")
    await store.add_message(session["id"], "user", "只验证已有公开题源的显示与跳转，不发起模型。")
    source = {**question["source"], "reference_used": True}
    event = {"type": "sources", "source": "chat", "stage": "responding", "content": "", "timestamp": int(time.time() * 1000), "metadata": {"sources": [source]}}
    await store.add_message(session["id"], "assistant", "本消息是来源显示合成验证。[查看本次原题](" + source["url"] + ")", capability="chat", events=[event], metadata={"sources": [source]})
    picture_manifest = json.loads((core / "deeptutor/services/student_learning/question_picture_data/manifest.json").read_text())
    assert picture_manifest["bank_revision"] == manifest["bank_revision"] and picture_manifest["items"], "Required prepared question display pack is absent"
    picture_id = max(picture_manifest["items"], key=lambda identity: len(picture_manifest["items"][identity]["asset_sha256"]))
    pictured = question_sources.detail(picture_id, root=pack, revision=manifest["bank_revision"])
    assert pictured["source"].get("picture"), "Prepared picture failed its frozen-source binding"
    picture_session = await store.create_session("完整题目图历史合成验证")
    await store.add_message(picture_session["id"], "user", "只验证完整题目图，不发起模型。")
    picture_source = {**pictured["source"], "reference_used": True}
    picture_event = {**event, "metadata": {"sources": [picture_source]}}
    answer_marker = "完整题目图合成验证正文立即可读"
    await store.add_message(picture_session["id"], "assistant", answer_marker + "。[查看本次原题](" + picture_source["url"] + ")", capability="chat", events=[picture_event], metadata={"sources": [picture_source]})
    picture_fixture = {"session": picture_session["id"], "qualified_id": picture_id, "bank_revision": manifest["bank_revision"],
        "href": picture_source["url"], "picture": picture_source["picture"], "answer_marker": answer_marker,
        "images": len(pictured["assets"]), "question": pictured["question"], "source_payload_sha256": picture_manifest["items"][picture_id]["source_payload_sha256"]}
    return {"session": session["id"], "qualified_id": question["qualified_id"], "bank_revision": question["bank_revision"], "href": source["url"], "question": question["question"], "title": question["title"], "images": len(question["assets"]), "picture_fixture": picture_fixture, "model_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    assert (args.home / ".k12-release-qa-allowed").is_file(), "Refusing an unmarked home"
    assert Path(os.environ["DEEPTUTOR_HOME"]).resolve() == args.home.resolve()
    sys.path.insert(0, str(args.core.resolve()))
    result = asyncio.run(seed(args.core.resolve()))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "question"}))
