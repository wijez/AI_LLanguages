from typing import Iterable, Optional
from django.utils import timezone
from django.db import transaction
from languages.models import RoleplayScenario, RoleplayBlock
from .embed_text import mark_dirty_scenarios, mark_dirty_blocks
from .ollama_client import embed_many
import os

MODEL = os.getenv("RAG_OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")

@transaction.atomic
def embed_scenarios(qs: Optional[Iterable[RoleplayScenario]] = None, batch=64, force=False):
    qs = list(qs or RoleplayScenario.objects.all())
    items = qs if force else mark_dirty_scenarios(qs)
    if not items: return 0
    texts = [x.embedding_text for x in items]
    vecs = []
    for i in range(0, len(texts), batch):
        vecs.extend(embed_many(texts[i:i+batch]))
    for x, v in zip(items, vecs):
        x.embedding = v
        x.embedding_model = MODEL
        x.embedding_updated_at = timezone.now()
        x.save(update_fields=["embedding", "embedding_model", "embedding_updated_at", "updated_at"])
    return len(items)

@transaction.atomic
def embed_blocks(qs: Optional[Iterable[RoleplayBlock]] = None, batch=128, force=False):
    qs = list(qs or RoleplayBlock.objects.select_related("scenario").all())
    items = qs if force else mark_dirty_blocks(qs)
    if not items: return 0
    texts = [x.embedding_text for x in items]
    vecs = []
    for i in range(0, len(texts), batch):
        vecs.extend(embed_many(texts[i:i+batch]))
    for x, v in zip(items, vecs):
        x.embedding = v
        x.embedding_model = MODEL
        x.embedding_updated_at = timezone.now()
        x.save(update_fields=["embedding", "embedding_model", "embedding_updated_at", "updated_at"])
    return len(items)
