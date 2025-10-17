from celery import shared_task
from .ml.etl import fetch_mistakes
from .ml.features import build_features
from .ml.trainer import train_model
from django.utils import timezone
from datetime import timedelta
from .models import Recommendation

@shared_task
def train_ai_model_task():
    print("🚀 Starting ETL + Training...")
    df_mistakes = fetch_mistakes()
    features = build_features(df_mistakes)
    version = train_model(features)
    print(f"✅ Model trained and saved: {version}")
    return version.id


@shared_task
def prune_old_recs(days=30):
    cutoff = timezone.now() - timedelta(days=days)
    Recommendation.objects.filter(created_at__lt=cutoff).delete()
