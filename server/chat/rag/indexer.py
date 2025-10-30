# chat/rag/indexer.py
from __future__ import annotations
from typing import List, Dict, Tuple, Iterable
import os, json, re
import numpy as np
from django.conf import settings

# ---- Embedding backend hook ----
#   get_embedder() -> object có .embed_texts(list[str]) -> np.ndarray, .embed_query(str) -> np.ndarray
try:
    from .embedders import get_embedder  # chỉnh import path cho đúng module của bạn
except Exception:  # fallback: sẽ raise rõ ràng khi gọi build_index
    get_embedder = None


# ---- Utils ----
def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def block_to_text(b: Dict) -> str:
    t = (b or {}).get("type")
    if t == "translate":
        return f"[translate {b.get('direction','vi->en')}] {b.get('prompt','')} => {b.get('answer','')}"
    if t == "multiple_choice":
        return f"[mcq] {b.get('prompt','')} choices={b.get('choices',[])} ans={b.get('answer','')}"
    if t == "fillgap":
        return f"[fill] {b.get('prompt','')} ans={b.get('answer','')}"
    if t == "ordering":
        return f"[reorder] tokens={b.get('tokens',[])} ans={' '.join(b.get('answer',[]))}"
    if t == "matching":
        return f"[match] {b.get('pairs',[])}"
    if t == "pron":
        return f"[pron] {b.get('prompt','')}"
    if t == "listening":
        return f"[listen] {b.get('prompt','')} ans={b.get('answer','')}"
    if t == "speaking":
        return f"[speak] {b.get('prompt','')}"
    if t == "reading":
        return f"[read] {b.get('prompt','')}"
    # generic / quiz:
    return json.dumps(b, ensure_ascii=False)


# ---- Harvest docs theo schema mới: Topic -> Lesson -> LessonSkill(order) -> Skill(content.blocks) ----
def harvest_docs(topic_slugs: Iterable[str] | None = None,
                 langs: Iterable[str] | None = None,
                 only_active_skills: bool = True) -> Tuple[List[str], List[Dict]]:
    """
    Trả về: (docs: List[str], metas: List[dict])
    - docs: text để embed
    - metas: metadata để filter lúc truy hồi
    """
    from languages.models import Topic, Lesson, LessonSkill, Skill  # import bên trong để tránh vòng lặp import

    qs_topic = Topic.objects.select_related("language")
    if topic_slugs:
        qs_topic = qs_topic.filter(slug__in=list(topic_slugs))
    if langs:
        qs_topic = qs_topic.filter(language__abbreviation__in=list(langs))

    # Prefetch lessons trước
    lessons_by_topic = {}
    for t in qs_topic:
        lessons_by_topic[t.id] = list(
            Lesson.objects.filter(topic=t).order_by("order", "id").only(
                "id", "title", "order", "topic_id"
            )
        )

    # Prefetch through + skills (giữ thứ tự theo LessonSkill.order)
    # NOTE: với nhiều topic, ta gom lesson_ids để query 1 lần
    all_lesson_ids: List[int] = [ls.id for L in lessons_by_topic.values() for ls in L]
    through_qs = []
    if all_lesson_ids:
        base = (LessonSkill.objects
                .filter(lesson_id__in=all_lesson_ids)
                .select_related("lesson", "skill")
                .order_by("lesson__order", "lesson__id", "order", "id"))
        if only_active_skills:
            base = base.filter(skill__is_active=True)
        through_qs = list(base.only("lesson_id", "skill_id", "order",
                                    "skill__id", "skill__title", "skill__type",
                                    "skill__content", "skill__language_code"))

    # Gom theo lesson_id
    skills_by_lesson: Dict[int, List] = {}
    for ls in through_qs:
        skills_by_lesson.setdefault(ls.lesson_id, []).append(ls.skill)

    docs: List[str] = []
    metas: List[Dict] = []

    # Duyệt Topic -> Lesson -> Skill -> blocks
    for t in qs_topic:
        lang_abbr = t.language.abbreviation  # ví dụ "en" / "vi"
        for ls in lessons_by_topic.get(t.id, []):
            for s in skills_by_lesson.get(ls.id, []):
                blocks = (s.content or {}).get("blocks", [])
                for idx, b in enumerate(blocks, start=1):
                    text_parts = [
                        f"[{lang_abbr}]",
                        f"Topic: {t.title}",
                        f"Lesson {ls.order}: {ls.title}",
                        f"Skill {s.type}: {s.title}",
                        block_to_text(b),
                    ]
                    txt = _norm(" | ".join(map(_norm, text_parts)))
                    docs.append(txt)
                    metas.append({
                        "language": lang_abbr,
                        "topic_slug": t.slug,
                        "topic_title": t.title,
                        "lesson_id": ls.id,
                        "lesson_order": ls.order,
                        "lesson_title": ls.title,
                        "skill_id": s.id,
                        "skill_type": s.type,
                        "skill_title": s.title,
                        "block_index": idx,
                        "block_type": (b or {}).get("type"),
                    })
    return docs, metas


# ---- Build & save index ----
def _index_dir() -> str:
    return getattr(settings, "RAG_INDEX_DIR", os.path.join(settings.BASE_DIR, "rag_index"))

def save_index(docs: List[str], metas: List[Dict], embs: np.ndarray, out_dir: str | None = None) -> None:
    out = out_dir or _index_dir()
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "docs.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)
    with open(os.path.join(out, "metas.json"), "w", encoding="utf-8") as f:
        json.dump(metas, f, ensure_ascii=False)
    np.save(os.path.join(out, "embeddings.npy"), embs)

def load_index(in_dir: str | None = None) -> Tuple[List[str], List[Dict], np.ndarray]:
    src = in_dir or _index_dir()
    with open(os.path.join(src, "docs.json"), "r", encoding="utf-8") as f:
        docs = json.load(f)
    with open(os.path.join(src, "metas.json"), "r", encoding="utf-8") as f:
        metas = json.load(f)
    embs = np.load(os.path.join(src, "embeddings.npy"))
    return docs, metas, embs


def build_index(topic_slugs: Iterable[str] | None = None,
                langs: Iterable[str] | None = None,
                out_dir: str | None = None) -> Dict:
    """
    Thu hoạch -> embed -> lưu index.
    """
    docs, metas = harvest_docs(topic_slugs=topic_slugs, langs=langs)
    if not docs:
        return {"docs": 0, "dim": 0, "note": "no docs"}

    if get_embedder is None:
        raise RuntimeError("No embedding backend. Please provide embedders.get_embedder().")

    embedder = get_embedder()
    vectors = embedder.embed_texts(docs)  # (N, D) np.ndarray
    save_index(docs, metas, vectors, out_dir=out_dir)
    return {"docs": len(docs), "dim": int(vectors.shape[1])}
