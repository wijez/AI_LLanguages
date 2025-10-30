import hashlib
from typing import Iterable
from languages.models import RoleplayScenario, RoleplayBlock

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def scenario_text(s: RoleplayScenario) -> str:
    if s.embedding_text:
        return s.embedding_text.strip()
    parts = [f"[{b.section}#{b.order}] {b.role or '-'}: {b.text}"
             for b in s.blocks.order_by("section", "order", "created_at")]
    return "\n".join(parts).strip()

def block_text(b: RoleplayBlock) -> str:
    return (b.embedding_text or f"[{b.section}#{b.order}] {b.role or '-'}: {b.text}").strip()

def mark_dirty_scenarios(items: Iterable[RoleplayScenario]) -> list[RoleplayScenario]:
    dirty = []
    for s in items:
        new_text = scenario_text(s)
        new_hash = sha256(new_text)
        if new_hash != getattr(s, "embedding_hash", ""):
            s.embedding_text = new_text
            s.embedding_hash = new_hash
            s.embedding = None  # đánh dấu cần embed lại
            s.save(update_fields=["embedding_text", "embedding_hash", "embedding", "updated_at"])
            dirty.append(s)
    return dirty

def mark_dirty_blocks(items: Iterable[RoleplayBlock]) -> list[RoleplayBlock]:
    dirty = []
    for b in items:
        new_text = block_text(b)
        new_hash = sha256(new_text)
        if new_hash != getattr(b, "embedding_hash", ""):
            b.embedding_text = new_text
            b.embedding_hash = new_hash
            b.embedding = None
            b.save(update_fields=["embedding_text", "embedding_hash", "embedding", "updated_at"])
            dirty.append(b)
    return dirty
