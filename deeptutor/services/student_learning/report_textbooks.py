"""Bound a review to the actual PDF outline and, when known, the pages discussed."""

import re

from deeptutor.multi_user.learning_access import learning_material_allowed, learning_surface_allowed
from deeptutor.reading import ReadingError, ReadingStore

from . import textbooks
from .reports import ReportError


PRINTED_CONTENTS = re.compile(r"(?im)^\s*(?:目\s*录|contents)\s*$")
PRINTED_ENTRY = re.compile(r"^(.+?)\s*(?:[.…．·]\s*){2,}(\d+)\s*$")
CHAPTER_PREFIX = re.compile(r"^(?:第[一二三四五六七八九十百\d]+(?:课|节|章|单元)|\d+(?:\.\d+)+)\s*")


def printed_outline(store: ReadingStore, material: str, count: int, notes: str) -> tuple[list[dict], bool]:
    """Use printed TOC entries without treating printed numbering as PDF locators."""
    for page in range(1, min(12, count) + 1):
        text = store.unit_text(material, page)
        if not PRINTED_CONTENTS.search(text):
            continue
        rows = []
        for locator in range(page, min(page + 2, count) + 1):
            page_text = text if locator == page else store.unit_text(material, locator)
            entries = [entry.groups() for line in page_text.splitlines()
                       if (entry := PRINTED_ENTRY.fullmatch(line.strip()))]
            if not entries:
                break
            rows.extend(entries)
        if rows:
            normalized_notes = re.sub(r"\s+", "", notes)
            matches = []
            for title, number in rows:
                chapter = re.sub(r"\s+", "", CHAPTER_PREFIX.sub("", title).strip())
                if len(chapter) >= 4 and chapter in normalized_notes:
                    matches.append((title, number))
            return [{"title": title[:155] + f"（印刷页 {number}）"}
                    for title, number in (matches or rows)[:24]], bool(matches)
        return [{"title": line.strip()[:180]} for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("【")][:24], False
    return [], False


def report_textbook_scope(source: dict) -> list[dict]:
    selected = source.get("textbook_id")
    if not learning_surface_allowed("reading"):
        if selected:
            raise ReportError("当前账号没有教材阅读权限。", 403)
        return []
    turns = source.get("reading_sources", {})
    messages = [m for m in source["messages"] if m["role"] == "user" and m.get("kind") != "student_reflection"]
    by_material = {}
    for message in reversed(messages):
        if ref := turns.get(message["id"]):
            by_material.setdefault(ref[0], []).append(ref[1:])
    material_ids = [selected] if selected else list(by_material)[:3]
    if not material_ids:
        return []
    store = ReadingStore()
    catalog = {book["id"]: book.get("subject") for book in textbooks.catalog()["books"]}
    notes = "\n".join(m["content"] for m in messages)
    scopes = []
    for material in material_ids:
        if not learning_material_allowed(material):
            if selected:
                raise ReportError("这份教材当前不可用，请重新选择。", 422)
            continue
        subject = source["subject"]
        if catalog.get(material) and catalog[material] not in {subject, "ethics" if subject == "politics" else subject}:
            if selected:
                raise ReportError("这份教材和所选学科不同，请重新选择。", 422)
            continue
        try:
            manifest = store.manifest(material)
            if manifest.render_mode != "pdf":
                raise ValueError("not PDF")
            pages = sorted({page for page, rev in by_material.get(material, [])
                            if (rev is None or rev == manifest.revision) and type(page) is int and 1 <= page <= manifest.unit_count})
            outline = [row for row in store.outline(material) if not row.synthesised and row.title.strip() and 1 <= row.locator <= manifest.unit_count]
            matched = {row for row in outline if len(row.title.strip()) >= 4 and row.title.strip() in notes}
            for page in pages:
                if preceding := [row for row in outline if row.locator <= page]:
                    matched.add(max(preceding, key=lambda row: (row.locator, row.level)))
            printed_match = False
            if matched:
                entries = sorted(matched, key=lambda row: (row.locator, row.level))[:16]
                scope = [{"title": row.title[:180], "page": row.locator} for row in entries]
            else:
                scope = [{"title": row.title[:180], "page": row.locator} for row in sorted(outline, key=lambda row: row.level)[:24]]
                if not scope:
                    scope, printed_match = printed_outline(store, material, manifest.unit_count, notes)
            scopes.append({"material_id": material, "title": manifest.title[:180], "outline": scope,
                           "matched": bool(matched) or printed_match, "pages": pages[:12]})
        except (ReadingError, OSError, ValueError):
            if selected:
                raise ReportError("这份教材 PDF 无法读取，请重新选择。", 422) from None
    return scopes
