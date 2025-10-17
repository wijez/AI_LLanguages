import os, math, random, pandas as pd
from datetime import timedelta
from django.utils import timezone

from languages.models import LanguageEnrollment, Lesson
from learning.models import LessonSession
from progress.models import DailyXP
from recommend.utils.ai_client import ai_trigger_train

# ===== Tham số snapshot
SNAPSHOT_ID = "2025-10-10-test"
TARGET_DAYS = 14   # cửa sổ làm nhãn (để có 0/1 dễ hơn)
LOOKBACK_DAYS = 60

# ===== MinIO options (lấy từ ENV của BE)
storage_options = {
    "key": os.getenv("MINIO_ACCESS_KEY"),
    "secret": os.getenv("MINIO_SECRET_KEY"),
    "client_kwargs": {"endpoint_url": os.getenv("MINIO_ENDPOINT")},
}
bucket = os.getenv("MINIO_BUCKET", "ai-snapshots")
features_uri = f"s3://{bucket}/snapshots/{SNAPSHOT_ID}/features.parquet"
labels_uri   = f"s3://{bucket}/snapshots/{SNAPSHOT_ID}/labels.parquet"

now = timezone.now()
start = now - timedelta(days=LOOKBACK_DAYS)
target_start = now - timedelta(days=TARGET_DAYS)

# ===== Enrollments
enr_qs = LanguageEnrollment.objects.values(
    "id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"
)
df_enr = pd.DataFrame(list(enr_qs)) if enr_qs.exists() else pd.DataFrame(
    columns=["id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"]
)
df_enr.rename(columns={"id":"enrollment_id"}, inplace=True)

# Trường hợp không có enrollment nào thì dừng sớm, tránh file rỗng lẻ
if df_enr.empty:
    print("No enrollments found. Seed data first.")
    raise SystemExit(0)

# ===== DailyXP (7d/30d)
dx_qs = DailyXP.objects.filter(date__gte=(now - timedelta(days=30)).date()) \
                       .values("user_id","date","xp")
df_dx = pd.DataFrame(list(dx_qs)) if dx_qs.exists() else pd.DataFrame(columns=["user_id","date","xp"])
if not df_dx.empty:
    df_dx["date"] = pd.to_datetime(df_dx["date"])
    d7_cut = (now - timedelta(days=7)).date()
    dx7 = (df_dx[df_dx["date"].dt.date >= d7_cut]
           .groupby("user_id", as_index=False)["xp"].sum()
           .rename(columns={"xp":"xp_7d"}))
    dx30 = (df_dx.groupby("user_id", as_index=False)["xp"].sum()
            .rename(columns={"xp":"xp_30d"}))
else:
    dx7  = pd.DataFrame(columns=["user_id","xp_7d"])
    dx30 = pd.DataFrame(columns=["user_id","xp_30d"])

# ===== LessonSession → labels + vài features
sess_qs = LessonSession.objects.filter(started_at__gte=start) \
    .values("enrollment_id","status","completed_at","duration_seconds","xp_earned")
df_sess = pd.DataFrame(list(sess_qs)) if sess_qs.exists() else pd.DataFrame(
    columns=["enrollment_id","status","completed_at","duration_seconds","xp_earned"]
)

if not df_sess.empty and "completed_at" in df_sess.columns:
    df_sess["completed_at"] = pd.to_datetime(df_sess["completed_at"])

# Label: có lesson “completed” trong cửa sổ TARGET_DAYS?
if not df_sess.empty:
    recent = df_sess[
        df_sess["completed_at"].notna() & (df_sess["completed_at"] >= target_start)
    ]
    if not recent.empty:
        y = (recent[recent["status"] == "completed"]
             .groupby("enrollment_id", as_index=False)
             .size().rename(columns={"size":"any_completed"}))
        y["gt_target_completed"] = (y["any_completed"] > 0).astype("int8")
        df_y = y[["enrollment_id","gt_target_completed"]]
    else:
        df_y = pd.DataFrame(columns=["enrollment_id","gt_target_completed"])
else:
    df_y = pd.DataFrame(columns=["enrollment_id","gt_target_completed"])

# Feature 7 ngày gần nhất
if not df_sess.empty:
    s7 = df_sess[
        df_sess["completed_at"].notna() & (df_sess["completed_at"] >= now - timedelta(days=7))
    ]
    if not s7.empty:
        s7_agg = (s7.groupby("enrollment_id", as_index=False)
                    .agg(sessions_7d=("status","size"),
                         sess7_dur_sum=("duration_seconds","sum"),
                         sess7_xp_sum=("xp_earned","sum")))
    else:
        s7_agg = pd.DataFrame(columns=["enrollment_id","sessions_7d","sess7_dur_sum","sess7_xp_sum"])
else:
    s7_agg = pd.DataFrame(columns=["enrollment_id","sessions_7d","sess7_dur_sum","sess7_xp_sum"])

# ===== Build features (trainer cần cột 'id')
df_feat = (df_enr
    .merge(dx7,  how="left", on="user_id")
    .merge(dx30, how="left", on="user_id")
    .merge(s7_agg, how="left", on="enrollment_id")
).copy()

for c in [col for col in df_feat.columns
          if col not in ("enrollment_id","user_id","language_id","level","total_xp",
                         "streak_days","last_practiced","created_at")]:
    df_feat[c] = df_feat[c].fillna(0)

df_feat["id"] = df_feat["enrollment_id"]

# ===== labels.parquet
df_labels = pd.DataFrame({"recommendation_id": df_feat["id"]}).merge(
    df_y.rename(columns={"enrollment_id":"recommendation_id",
                         "gt_target_completed":"target_completed"}),
    how="left", on="recommendation_id"
)
df_labels["target_completed"] = df_labels["target_completed"].fillna(0).astype(int)
df_labels["created_at"] = pd.to_datetime(now)

# Chống corner case: nếu toàn 0 hoặc toàn 1, ép ngẫu nhiên một ít để model train được
if df_labels["target_completed"].nunique() == 1 and len(df_labels) >= 10:
    # Lật ~5% mẫu để có 2 lớp (chỉ phục vụ demo)
    flip_n = max(1, int(len(df_labels) * 0.05))
    idx = df_labels.sample(flip_n, random_state=42).index
    df_labels.loc[idx, "target_completed"] = 1 - df_labels.loc[idx, "target_completed"]
    print(f"[WARN] Label was single-class; flipped {flip_n} rows for demo training.")

# ===== Ghi ra MinIO
print("Saving to:", features_uri, labels_uri)
df_feat.to_parquet(features_uri, index=False, storage_options=storage_options)
df_labels.to_parquet(labels_uri, index=False, storage_options=storage_options)
print("Rows:", len(df_feat), len(df_labels), "Positives:", int(df_labels["target_completed"].sum()))

# ===== Gọi train
print("Trigger train…")
print(ai_trigger_train(SNAPSHOT_ID, {"max_depth": 3}))
