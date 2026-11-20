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
    pictured = None
    for identity in sorted(picture_manifest["items"], key=lambda identity: len(picture_manifest["items"][identity]["asset_sha256"]), reverse=True):
        candidate = question_sources.detail(identity, root=pack, revision=manifest["bank_revision"])
        if candidate["source"].get("picture") and not candidate["source"].get("native") and not candidate["source"].get("native_required"):
            pictured = candidate
            break
    assert pictured is not None, "A non-native prepared image must remain covered independently"
    picture_id = pictured["qualified_id"]
    picture_session = await store.create_session("完整题目图历史合成验证")
    await store.add_message(picture_session["id"], "user", "只验证完整题目图，不发起模型。")
    picture_source = {**pictured["source"], "reference_used": True}
    picture_event = {**event, "metadata": {"sources": [picture_source]}}
    answer_marker = "完整题目图合成验证正文立即可读"
    await store.add_message(picture_session["id"], "assistant", answer_marker + "。[查看本次原题](" + picture_source["url"] + ")", capability="chat", events=[picture_event], metadata={"sources": [picture_source]})
    picture_fixture = {"session": picture_session["id"], "qualified_id": picture_id, "bank_revision": manifest["bank_revision"],
        "href": picture_source["url"], "picture": picture_source["picture"], "answer_marker": answer_marker,
        "images": len(pictured["assets"]), "question": pictured["question"], "source_payload_sha256": picture_manifest["items"][picture_id]["source_payload_sha256"]}
    native_id = "math:q_e9dd00ffa1178d29b41fadb4_2"
    native_question = question_sources.detail(native_id, root=pack, revision=manifest["bank_revision"])
    assert native_question["source"].get("native_required") and native_question["source"].get("native"), "Native student page fixture is required"
    native_session = await store.create_session("原生题页历史合成验证")
    await store.add_message(native_session["id"], "user", "只验证原生题页及历史，不发起模型。")
    native_source = {**native_question["source"], "reference_used": True}
    native_marker = "原生题页合成验证正文立即可读"
    await store.add_message(native_session["id"], "assistant", native_marker + "。[查看本次原题](" + native_source["url"] + ")", capability="chat",
        events=[{**event, "metadata": {"sources": [native_source]}}], metadata={"sources": [native_source]})
    native_fixture = {"session": native_session["id"], "qualified_id": native_id, "bank_revision": manifest["bank_revision"],
        "href": native_source["url"], "answer_marker": native_marker, "native": native_source["native"]}
    # Attach an actual three-page PDF and a legacy synthetic quote to the
    # same saved user message. Seed a separate subsequent answer for history.
    import hashlib
    import fitz
    from deeptutor.services.storage import get_attachment_store

    citation_session = (await store.create_session("桌面引用端到端验收"))["id"]
    filename = "citation-native-proof.pdf"
    proof_text = "CITATION_NATIVE_PAGE_3"
    with fitz.open() as pdf:
        for page_number in range(1, 4):
            page = pdf.new_page()
            page.insert_text((72, 78), proof_text if page_number == 3 else f"CITATION_NATIVE_PAGE_{page_number}")
        data = pdf.tobytes()
    attachment_store = get_attachment_store()
    pdf_url = await attachment_store.put(session_id=citation_session, attachment_id="citationpdf1",
                                         filename=filename, data=data, mime_type="application/pdf")
    quote_url = await attachment_store.put(session_id=citation_session, attachment_id="citationsnip",
                                           filename="quote.md", data=b"Selected only", mime_type="text/markdown")
    user = await store.add_message(citation_session, "user", "用第三页合成资料核对。",
        attachments=[{"type": "quote", "id": "citationsnip", "filename": "quote.md",
                      "url": quote_url, "extracted_text": "选段留在学生消息里。"},
                     {"type": "file", "id": "citationpdf1", "filename": filename,
                      "url": pdf_url, "mime_type": "application/pdf"}])
    paragraph = "原件第三页支持这一句。"
    pdf_href = pdf_url + "#page=3"
    citations = [
        {"type": "attachment", "url": pdf_href, "reference_used": True, "title": "已验证第三页",
         "attachment_id": "citationpdf1", "unit": "page", "page": 3, "mime_type": "application/pdf"},
        {"type": "attachment", "url": quote_url, "reference_used": True, "title": "误标的摘录",
         "attachment_id": "citationsnip", "mime_type": "text/markdown"},
    ]
    assistant = await store.add_message(citation_session, "assistant", paragraph +
        f"[实际原件]({pdf_href}) [误标的摘录]({quote_url})\n\n下一段不带引用。",
        capability="chat", events=[{**event, "metadata": {"sources": citations}}], parent_message_id=user)
    followup = await store.add_message(citation_session, "user", "再核对一遍。", parent_message_id=assistant)
    await store.add_message(citation_session, "assistant", "第二轮已保留。", capability="chat",
                            parent_message_id=followup)
    citation_fixture = {"session": citation_session, "message": assistant, "paragraph": paragraph,
      "href": pdf_href, "filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "page_text": proof_text}
    return {"session": session["id"], "qualified_id": question["qualified_id"], "bank_revision": question["bank_revision"], "href": source["url"], "question": question["question"], "title": question["title"], "images": len(question["assets"]), "native": source.get("native"), "picture_fixture": picture_fixture, "native_fixture": native_fixture, "desktop_citation_fixture": citation_fixture, "model_calls": 0}


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
