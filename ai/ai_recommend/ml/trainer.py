
from .etl import fetch_mistakes
import joblib, os   
from datetime import datetime
from sklearn.ensemble import RandomForestRegressor
from ai.ai_recommend.models import AIModelVersion, TrainingRun


ARTIFACT_DIR = "ml/artifacts"
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def train_model(features):
    X = features[["mistake_rate", "count"]]
    y = (1 - features["mistake_rate"]).clip(0, 1)  # ít lỗi = score cao

    model = RandomForestRegressor(n_estimators=50)
    model.fit(X, y)

    artifact_path = f"{ARTIFACT_DIR}/recommend_model_{datetime.now().strftime('%Y%m%d_%H%M')}.pkl"
    joblib.dump(model, artifact_path)

    # Lưu metadata vào DB AI
    version = AIModelVersion.objects.create(
        name="RandomForest",
        version=datetime.now().strftime("%Y.%m.%d-%H%M"),
        description="Trained every 2h by Celery",
        artifact_path=artifact_path,
    )
    TrainingRun.objects.create(model=version, status="succeeded")

    return version