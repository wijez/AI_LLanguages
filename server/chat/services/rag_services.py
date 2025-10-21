from __future__ import annotations

import json
import numpy as np

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple, Dict, Any, Protocol


from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from sentence_transformers.util import normalize_embeddings

from pgvector.django import CosineDistance

from languages.models import Topic
from models import RoleplayScenario, RoleplayBlock, Word
from sentence_transformers import SentenceTransformer
from openai import OpenAI


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]: ...


class SentenceTranformerEmbedder:
    """ embedding mà không cần mạng"""
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        self.model = SentenceTransformer(model_name)
        self._dim = self.model.get_sentence_embedding_dimension()

    @property
    def dim(self) -> int:
        return self._dim
    
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        emb = self.model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
        return emb.astype("float32").tolist

    
class OpenAIEmbedder:
    def __init__(self, model: str) -> None:
        self.client = OpenAI()
        self.model = model
        self._dim = 1536 if "-small" in model else 3072

    @property
    def dim(self) -> int:
        return self._dim
    
    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        resp = self.client.embeddings.create(model=self.model, input=list(texts))
        return [d.embedding for d in resp.data]
    

def _flatten(obj: Any, max_lenght: int = 800) -> str:
    """ Làm phẳng nội dung"""
    try: 
        s = json.dumps(obj, ensure_ascii=False, separator=(",",":"))
    except Exception:
        s = str(obj)
        return s[:max_lenght]


def _has_fields( instance: Any, names: Sequence[str]) -> bool:
    return all(hasattr(instance, n) for n in names)


@dataclass
class RAGService:
    embedder: Embedder
    """Chuyển sang dạng chuỗi"""
    def build_text_for_block(self, block: RoleplayBlock) -> str:
        sc = getattr(block, "scenario", None)
        tp = getattr(sc, "topic", None) if sc else None
        sc_title = getattr(sc, "title", "")
        sc_slug = getattr(sc, "slug", "")
        tp_title = getattr(tp, "title", "")
        tp_slug = getattr(tp, "slug", "")
        parts = [
            f"Scenario: {sc_title} ({sc_slug})" if sc_title or sc_slug else "",
            f"Topic: {tp_title} ({tp_slug})" if tp_title or tp_slug else "",
            f"Section: {block.section}",
            f"Role: {block.role}" if block.role else "",
            f"Text: {block.text}".strip(),
            f"Lang: {block.lang_hint}" if block.lang_hint else "",
        ]
        return " | ".join([p for p in parts if p])

    def build_text_for_scenario(self, scenario: RoleplayScenario) -> str:
        topic = getattr(scenario, "topic", None)
        topic_part = f"Topic: {getattr(topic, 'title', '')} ({getattr(topic, 'slug', '')})" if topic else ""
        tags = ",".join(getattr(scenario, "tags", []) or [])
        parts = [
            f"Title: {scenario.title}",
            topic_part,
            f"Level: {scenario.level}",
            f"Tags: {tags}" if tags else "",
            f"Desc: {scenario.description}" if scenario.description else "",
        ]
        return " | ".join([p for p in parts if p])

    def build_text_for_word(self, word: Word) -> str: 
        definition = getattr(word, "definition", "")
        example = getattr(word, "example_sentence", "")
        parts = [
            f"Word: {word.text}",
            f"POS: {word.part_of_speech}" if word.part_of_speech else "",
            f"Def: {definition}" if definition else "",
            f"Ex: {example}" if example else "",
        ]
        return " | ".join([p for p in parts if p])
    
    def build_text_for_topic(self, topic: Topic) -> str:
        parts = [
            f"Topic: {topic.title}",
            f"Slug: {topic.slug}",
            f"Desc: {topic.description}" if topic.description else "",
        ]
        return " | ".join([p for p in parts if p])
    
    def upsert_instance(self, instance: Any) -> bool:
        require = ("embedding", "embedding_text", "embedding_updated_at")
        if not _has_fields(instance, require):
            return False
        
        if isinstance(instance, RoleplayBlock):
            text = self.build_text_for_block(instance)
        elif isinstance( instance, RoleplayScenario): 
            text = self.build_text_for_scenario(instance)
        elif isinstance( instance, Word):
            text = self.build_text_for_word(instance)
        elif isinstance(instance, Topic):
            text = self.build_text_for_topic(instance)
        else:
            raise TypeError(f"Unsupported model: {type(instance)}")

        if not text.strip():
            return False

        vec = self.embedder.embed_texts([text])[0]

        instance.embedding_text = text
        instance.embedding = vec
        instance.embedding_updated_at = timezone.now()
        instance.save(update_fields=["embedding_text", "embedding", "embedding_updated_at"])
        return True

    
    def _batched(self, qs: QuerySet, batch_size: int ) -> Iterable[List[Any]]:
        buffer: List[Any] = []
        for obj in qs.iterator(chunk_size= batch_size):
            buffer.append(obj)
            if len(buffer) >= batch_size:
                yield buffer
                buffer = []
        if buffer: 
            yield buffer
    
    def _index_queryset(self, qs: QuerySet, kind: str, batch_size: int = 128) -> Tuple[int, int]:
        """lập chỉ mục truy vấn """
        ok = skipped = 0
        builders = {
            "block": self.build_text_for_block,
            "scenario": self.build_text_for_scenario,
            "word": self.build_text_for_word,
            "topic": self.build_text_for_topic,
        }  
        build = builders[kind]

        if kind == "block":
            qs = qs.select_related("scenario", "scenario__topic")
        elif kind == "scenario":
            qs = qs.select_related("topic")
        
        for batch in self._batched(qs, batch_size=batch_size):
            texts = [build(x) for x in batch]
            mask = [bool(t.strip()) for t in texts]
            if not any(mask):
                skipped += len(batch)
                continue
            # Embed only non-empty
            to_embed = [t for t, m in zip(texts, mask) if m]
            vecs = self.embedder.embed_texts(to_embed)
            vi = 0
            with transaction.atomic():
                for obj, m, t in zip(batch, mask, texts):
                    if not _has_fields(obj, ("embedding", "embedding_text", "embedding_updated_at")):
                        skipped += 1
                        continue
                    if not m:
                        skipped += 1
                        continue
                    obj.embedding_text = t
                    obj.embedding = vecs[vi]
                    obj.embedding_updated_at = timezone.now()
                    obj.save(update_fields=["embedding_text", "embedding", "embedding_updated_at"])
                    ok += 1
                    vi += 1
            return ok, skipped

    def index_blocks(self, qs: Optional[QuerySet] = None, **filters) -> Tuple[int, int]:
        pass

    def index_scenarios(self, qs: Optional[QuerySet] = None, **filters) -> Tuple[int, int]:
        pass

    def index_words(self, qs: Optional[QuerySet] = None, **filters) -> Tuple[int, int]:
        pass

    def index_topics(self, qs: Optional[QuerySet] = None, **filters) -> Tuple[int, int]:
        pass

    def _embed_query(self, query: str) -> List[float]:
        return self.embedder.embed_texts([query])[0]

    def search_blocks(
    self,
    query: str,
    top_k: int = 8,
    *,
    language_id: Optional[int] = None,
    topic_id: Optional[int] = None,
    scenario_id: Optional[str] = None,
    section_in: Optional[Sequence[str]] = None,
    min_created_at: Optional[datetime] = None,
    ) -> List[RoleplayBlock]:
        vec = self._embed_query(query)
        qs = RoleplayBlock.objects.exclude(embedding__isnull=True)
        if scenario_id:
            qs = qs.filter(scenario_id=scenario_id)
        if topic_id:
            qs = qs.filter(scenario__topic_id=topic_id)
        if language_id:
            qs = qs.filter(scenario__topic__language_id=language_id)
        if section_in:
            qs = qs.filter(section__in=list(section_in))
        if min_created_at:
            qs = qs.filter(created_at__gte=min_created_at)
        qs = qs.select_related("scenario", "scenario__topic")
        qs = qs.annotate(dist=CosineDistance("embedding", vec)).order_by("dist")
        return list(qs[:top_k])

    def search_scenarios(
    self,
    query: str,
    top_k: int = 8,
    *,
    language_id: Optional[int] = None,
    topic_id: Optional[int] = None,
    level_in: Optional[Sequence[str]] = None,
    is_active: Optional[bool] = True,
    ) -> List[RoleplayScenario]:
        vec = self._embed_query(query)
        qs = RoleplayScenario.objects.exclude(embedding__isnull=True)
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        if language_id:
            qs = qs.filter(topic__language_id=language_id)
        if level_in:
            qs = qs.filter(level__in=list(level_in))
        qs = qs.select_related("topic")
        qs = qs.annotate(dist=CosineDistance("embedding", vec)).order_by("dist")
        return list(qs[:top_k])


    def expand_neighbors(self, blocks: Sequence[RoleplayBlock], window: int = 1) -> List[RoleplayBlock]:
        """For each block, fetch ±window by order within same scenario-section to keep context."""
        if not blocks:
            return []
        from django.db.models import Q
        out: Dict[Tuple[str, str], set[int]] = {}
        for b in blocks:
            key = (str(b.scenario_id), b.section)
            out.setdefault(key, set()).add(b.order)
            for d in range(1, window + 1):
                out[key].add(b.order + d)
                out[key].add(b.order - d)
        q = Q()
        for (sc_id, section), orders in out.items():
            q |= Q(scenario_id=sc_id, section=section, order__in=list(orders))
        neighbors = list(
            RoleplayBlock.objects.filter(q).select_related("scenario", "scenario__topic").order_by("scenario_id", "section", "order")
        )
        # De-dup while keeping order
        seen = set()
        uniq: List[RoleplayBlock] = []
        for n in neighbors:
            k = (n.pk)
            if k in seen:
                continue
            seen.add(k)
            uniq.append(n)
        return uniq


