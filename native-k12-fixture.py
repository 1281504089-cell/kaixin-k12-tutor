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
        row = conn.execute("SELECT q.qualified_id FROM questions q JOIN documents d ON d.payload_sha=q.payload_sha ORDER BY (json_array_length(d.body_json,'$.assets')>0) DESC,q.qualified_id LIMIT 1").fetchone()
    question = question_sources.detail(row[0], root=pack, revision=manifest["bank_revision"])
    store = get_sqlite_session_store()
    session = await store.create_session("题库来源跳转合成验证")
    await store.add_message(session["id"], "user", "只验证已有公开题源的显示与跳转，不发起模型。")
    source = {**question["source"], "reference_used": True}
    event = {"type": "sources", "source": "chat", "stage": "responding", "content": "", "timestamp": int(time.time() * 1000), "metadata": {"sources": [source]}}
    await store.add_message(session["id"], "assistant", "本消息是来源显示合成验证。[查看本次原题](" + source["url"] + ")", capability="chat", events=[event], metadata={"sources": [source]})
    return {"session": session["id"], "qualified_id": question["qualified_id"], "bank_revision": question["bank_revision"], "href": source["url"], "question": question["question"], "title": question["title"], "images": len(question["assets"]), "model_calls": 0}


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
