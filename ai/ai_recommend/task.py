from celery import shared_task
from .ml.etl import fetch_mistakes
from .ml.features import build_features
from .ml.trainer import train_model

@shared_task
def train_ai_model_task():
    print("🚀 Starting ETL + Training...")
    df_mistakes = fetch_mistakes()
    features = build_features(df_mistakes)
    version = train_model(features)
    print(f"✅ Model trained and saved: {version}")
    return version.id
