# chat/rag/indexer.py
from typing import List, Dict, Tuple
import json, re

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def block_to_text(b: Dict) -> str:
    t = b.get("type")
    if t == "translate":       return f"[translate {b.get('direction','vi->en')}] {b.get('prompt','')} => {b.get('answer','')}"
    if t == "multiple_choice": return f"[mcq] {b.get('prompt','')} choices={b.get('choices',[])} ans={b.get('answer','')}"
    if t == "fill_blank":      return f"[fill] {b.get('prompt','')} ans={b.get('answer','')}"
    if t == "reorder":         return f"[reorder] tokens={b.get('tokens',[])} ans={' '.join(b.get('answer',[]))}"
    if t == "match":           return f"[match] {b.get('pairs',[])}"
    if t == "speak":           return f"[speak] {b.get('prompt','')}"
    if t == "listen_type":     return f"[listen] ans={b.get('answer','')}"
    return json.dumps(b, ensure_ascii=False)

def harvest_docs(topic_slugs: List[str] | None = None) -> Tuple[List[str], List[Dict]]:
    from languages.models import Topic, Skill, Lesson   # import trong hàm
    qs_topic = Topic.objects.all() if not topic_slugs else Topic.objects.filter(slug__in=topic_slugs)
    docs, metas = [], []
    for t in qs_topic:
        for s in Skill.objects.filter(topic=t).order_by("order","id"):
            for l in Lesson.objects.filter(skill=s).order_by("id"):
                blocks = (l.content or {}).get("blocks", [])
                for idx, b in enumerate(blocks, start=1):
                    docs.append(_norm(block_to_text(b)))
                    metas.append({
                        "topic": t.slug, "skill": s.title, "lesson": l.title,
                        "lesson_id": l.id, "block_index": idx, "block_type": b.get("type"),
                    })
    return docs, metas
