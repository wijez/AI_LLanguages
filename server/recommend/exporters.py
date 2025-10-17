from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone
from typing import Dict

import boto3
import pandas as pd
from django.conf import settings
from django.utils import timezone as djtz

# ---- IMPORT MODELS khớp project của bạn ----
from users.models import User
from languages.models import LanguageEnrollment, UserSkillStats
from learning.models import LessonSession
from progress.models import DailyXP
from vocabulary.models import KnownWord, LearningInteraction, Mistake


# =========================
# MinIO (S3) helpers
# =========================
def _s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        region_name=os.getenv("MINIO_REGION", "us-east-1"),
    )


def _s3_url(key: str) -> str:
    """Trả về URI s3://bucket/key để AI đọc bằng s3fs/pyarrow."""
    return f"s3://{os.getenv('MINIO_BUCKET')}/{key}"


def _upload_parquet(df: pd.DataFrame, key: str) -> str:
    """
    Ghi DataFrame ra Parquet lên MinIO qua boto3.
    Yêu cầu 'pyarrow' đã cài (pandas sẽ dùng engine pyarrow).
    """
    try:
        import pyarrow  # noqa: F401
    except Exception as e:
        raise RuntimeError("Missing dependency 'pyarrow'. Install with: pip install pyarrow") from e

    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    _s3().put_object(
        Bucket=os.getenv("MINIO_BUCKET"),
        Key=key,
        Body=buf.getvalue(),
        ContentType="application/octet-stream",
    )
    return _s3_url(key)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# =========================
# Snapshot Builder
# =========================
def build_snapshot(
    snapshot_id: str,
    days: int = 60,
    target_window_days: int = 7,
) -> Dict:
    """
    Tạo snapshot train cho AI gồm 2 file Parquet:

      - features.parquet: 1 hàng / enrollment (id == enrollment_id)
      - labels.parquet:   1 hàng / enrollment (recommendation_id == enrollment_id)
        target_completed = 1 nếu có LessonSession.completed trong target_window_days gần đây.

    Feature bao gồm:
      - Enrollment: level, total_xp, streak_days
      - DailyXP (user-level): xp_7d, xp_30d
      - LessonSession: sessions_7d
      - UserSkillStats: prof_mean (mean proficiency_score)
      - KnownWord: kw_count, kw_mastered, ease_mean
      - LearningInteraction: các tổng hợp 7d/30d, pivot theo action, recency
      - Mistake: tổng hợp 7d/30d, pivot theo source, recency
    """
    now = djtz.now()  # timezone-aware
    start = now - timedelta(days=days)
    target_start = now - timedelta(days=target_window_days)

    # ---------- Enrollments ----------
    enr_qs = LanguageEnrollment.objects.values(
        "id", "user_id", "level", "total_xp", "streak_days", "last_practiced"
    )
    df_enr = pd.DataFrame(list(enr_qs))
    if df_enr.empty:
        df_enr = pd.DataFrame(columns=["id", "user_id", "level", "total_xp", "streak_days", "last_practiced"])

    dx_qs = DailyXP.objects.filter(date__gte=(now - timedelta(days=30)).date()).values(
    "user_id", "date", "xp"
    )
    df_dx = pd.DataFrame(list(dx_qs))
    if df_dx.empty:
        df_dx = pd.DataFrame(columns=["user_id", "date", "xp"])
        df_dx_7 = pd.DataFrame(columns=["user_id", "xp_7d"])
        df_dx_30 = pd.DataFrame(columns=["user_id", "xp_30d"])
    else:
        # Ép về Timestamp NAIVE (không timezone) để so sánh NAIVE-NAIVE
        df_dx["date"] = pd.to_datetime(df_dx["date"]).dt.normalize().dt.tz_localize(None)

        # Mốc 7/30 ngày NAIVE
        ts7  = pd.Timestamp((now - timedelta(days=7)).date())
        ts30 = pd.Timestamp((now - timedelta(days=30)).date())

        df_dx_7 = (
            df_dx[df_dx["date"] >= ts7]
            .groupby("user_id", as_index=False)["xp"]
            .sum()
            .rename(columns={"xp": "xp_7d"})
        )
        df_dx_30 = (
            df_dx[df_dx["date"] >= ts30]
            .groupby("user_id", as_index=False)["xp"]
            .sum()
            .rename(columns={"xp": "xp_30d"})
        )
    # ---------- LessonSession aggregates ----------
    sess_qs = (
        LessonSession.objects.filter(started_at__gte=start)
        .values("enrollment_id", "status", "completed_at", "duration_seconds", "xp_earned")
    )
    df_sess = pd.DataFrame(list(sess_qs))
    if df_sess.empty:
        df_sess = pd.DataFrame(columns=["enrollment_id", "status", "completed_at", "duration_seconds", "xp_earned"])
    else:
        df_sess["completed_at"] = pd.to_datetime(df_sess["completed_at"])

    # sessions hoàn thành 7 ngày gần đây
    if not df_sess.empty:
        df_sess7 = df_sess[df_sess["completed_at"].notna()]
        df_sess7 = df_sess7[df_sess7["completed_at"] >= (now - timedelta(days=7))]
        df_sess7_agg = (
            df_sess7.groupby("enrollment_id", as_index=False)
            .size()
            .rename(columns={"size": "sessions_7d"})
        )
    else:
        df_sess7_agg = pd.DataFrame(columns=["enrollment_id", "sessions_7d"])

    # ---------- UserSkillStats (proficiency) ----------
    stats_qs = UserSkillStats.objects.values("enrollment_id", "proficiency_score")
    df_stats = pd.DataFrame(list(stats_qs))
    if not df_stats.empty:
        df_prof = (
            df_stats.groupby("enrollment_id", as_index=False)["proficiency_score"]
            .mean()
            .rename(columns={"proficiency_score": "prof_mean"})
        )
    else:
        df_prof = pd.DataFrame(columns=["enrollment_id", "prof_mean"])

    # ---------- KnownWord aggregates ----------
    kw_qs = KnownWord.objects.values("enrollment_id", "status", "ease_factor")
    df_kw = pd.DataFrame(list(kw_qs))
    if not df_kw.empty:
        df_kw["is_mastered"] = (df_kw["status"] == "mastered").astype("int8")
        df_kw_agg = (
            df_kw.groupby("enrollment_id", as_index=False)
            .agg(
                kw_count=("status", "size"),
                kw_mastered=("is_mastered", "sum"),
                ease_mean=("ease_factor", "mean"),
            )
        )
    else:
        df_kw_agg = pd.DataFrame(columns=["enrollment_id", "kw_count", "kw_mastered", "ease_mean"])

    # ---------- Base FEATURES (X) ----------
    if df_enr.empty:
        df_X = pd.DataFrame(columns=[
            "id", "user_id", "enrollment_id", "level", "total_xp", "streak_days", "created_at"
        ])
    else:
        df_X = pd.DataFrame({
            "id": df_enr["id"],
            "user_id": df_enr["user_id"],
            "enrollment_id": df_enr["id"],
            "level": df_enr.get("level", 0),
            "total_xp": df_enr.get("total_xp", 0),
            "streak_days": df_enr.get("streak_days", 0),
            "created_at": pd.Timestamp(now),
        })

    # join DailyXP
    df_X = df_X.merge(df_dx_7, how="left", on="user_id")
    df_X = df_X.merge(df_dx_30, how="left", on="user_id")

    # join session/prof/knownword
    df_X = df_X.merge(df_sess7_agg, how="left", on="enrollment_id")
    df_X = df_X.merge(df_prof,      how="left", on="enrollment_id")
    df_X = df_X.merge(df_kw_agg,    how="left", on="enrollment_id")

    # fillna base
    for col in ["xp_7d", "xp_30d", "sessions_7d", "prof_mean", "kw_count", "kw_mastered", "ease_mean", "streak_days"]:
        if col in df_X.columns:
            df_X[col] = df_X[col].fillna(0)

    # ---------- LearningInteraction aggregates (7d/30d) ----------
    li_qs = LearningInteraction.objects.filter(
        created_at__gte=now - timedelta(days=30)
    ).values("enrollment_id", "action", "success", "duration_seconds", "xp_earned", "created_at")
    df_li = pd.DataFrame(list(li_qs))
    if df_li.empty:
        df_li = pd.DataFrame(columns=["enrollment_id", "action", "success", "duration_seconds", "xp_earned", "created_at"])
    else:
        df_li["created_at"] = pd.to_datetime(df_li["created_at"])

    if not df_li.empty:
        li_30_agg = (
            df_li.groupby("enrollment_id", as_index=False)
            .agg(
                li_30_count=("action", "size"),
                li_30_dur_sum=("duration_seconds", "sum"),
                li_30_xp_sum=("xp_earned", "sum"),
                li_30_success_rate=("success", "mean"),
            )
        )
    else:
        li_30_agg = pd.DataFrame(columns=["enrollment_id", "li_30_count", "li_30_dur_sum", "li_30_xp_sum", "li_30_success_rate"])

    df_li7 = df_li[df_li["created_at"] >= (now - timedelta(days=7))] if not df_li.empty else df_li
    if not df_li7.empty:
        li_7_agg = (
            df_li7.groupby("enrollment_id", as_index=False)
            .agg(
                li_7_count=("action", "size"),
                li_7_dur_sum=("duration_seconds", "sum"),
                li_7_xp_sum=("xp_earned", "sum"),
                li_7_success_rate=("success", "mean"),
            )
        )
        piv_li = (
            df_li7.assign(cnt=1)
            .pivot_table(index="enrollment_id", columns="action", values="cnt", aggfunc="sum", fill_value=0)
            .reset_index()
        )
        piv_li.columns = ["enrollment_id"] + [f"li_7_action_{c}" for c in piv_li.columns if c != "enrollment_id"]
    else:
        li_7_agg = pd.DataFrame(columns=["enrollment_id", "li_7_count", "li_7_dur_sum", "li_7_xp_sum", "li_7_success_rate"])
        piv_li = pd.DataFrame(columns=[
            "enrollment_id",
            "li_7_action_start_lesson",
            "li_7_action_complete_lesson",
            "li_7_action_review_word",
            "li_7_action_practice_skill",
        ])

    if not df_li.empty:
        last_li = (
            df_li.groupby("enrollment_id", as_index=False)["created_at"].max()
            .rename(columns={"created_at": "last_li_ts"})
        )
        last_li["li_days_since_last"] = (now - last_li["last_li_ts"]).dt.total_seconds() / 86400.0
        last_li = last_li[["enrollment_id", "li_days_since_last"]]
    else:
        last_li = pd.DataFrame(columns=["enrollment_id", "li_days_since_last"])

    # ---------- Mistake aggregates (7d/30d) ----------
    mk_qs = Mistake.objects.filter(
        timestamp__gte=now - timedelta(days=30)
    ).values("enrollment_id", "source", "score", "timestamp")
    df_mk = pd.DataFrame(list(mk_qs))
    if df_mk.empty:
        df_mk = pd.DataFrame(columns=["enrollment_id", "source", "score", "timestamp"])
    else:
        df_mk["timestamp"] = pd.to_datetime(df_mk["timestamp"])

    if not df_mk.empty:
        mk_30_agg = (
            df_mk.groupby("enrollment_id", as_index=False)
            .agg(
                mk_30_count=("source", "size"),
                mk_30_score_mean=("score", "mean"),
            )
        )
    else:
        mk_30_agg = pd.DataFrame(columns=["enrollment_id", "mk_30_count", "mk_30_score_mean"])

    df_mk7 = df_mk[df_mk["timestamp"] >= (now - timedelta(days=7))] if not df_mk.empty else df_mk
    if not df_mk7.empty:
        mk_7_agg = (
            df_mk7.groupby("enrollment_id", as_index=False)
            .agg(
                mk_7_count=("source", "size"),
                mk_7_score_mean=("score", "mean"),
            )
        )
        piv_mk = (
            df_mk7.assign(cnt=1)
            .pivot_table(index="enrollment_id", columns="source", values="cnt", aggfunc="sum", fill_value=0)
            .reset_index()
        )
        piv_mk.columns = ["enrollment_id"] + [f"mk_7_src_{c}" for c in piv_mk.columns if c != "enrollment_id"]
    else:
        mk_7_agg = pd.DataFrame(columns=["enrollment_id", "mk_7_count", "mk_7_score_mean"])
        piv_mk = pd.DataFrame(columns=[
            "enrollment_id",
            "mk_7_src_pronunciation", "mk_7_src_grammar", "mk_7_src_vocab",
            "mk_7_src_listening", "mk_7_src_spelling"
        ])

    if not df_mk.empty:
        last_mk = (
            df_mk.groupby("enrollment_id", as_index=False)["timestamp"].max()
            .rename(columns={"timestamp": "last_mk_ts"})
        )
        last_mk["mk_days_since_last"] = (now - last_mk["last_mk_ts"]).dt.total_seconds() / 86400.0
        last_mk = last_mk[["enrollment_id", "mk_days_since_last"]]
    else:
        last_mk = pd.DataFrame(columns=["enrollment_id", "mk_days_since_last"])

    # ---------- Merge tất cả vào X ----------
    df_X = (
        df_X
        .merge(li_30_agg, how="left", on="enrollment_id")
        .merge(li_7_agg,  how="left", on="enrollment_id")
        .merge(piv_li,    how="left", on="enrollment_id")
        .merge(last_li,   how="left", on="enrollment_id")
        .merge(mk_30_agg, how="left", on="enrollment_id")
        .merge(mk_7_agg,  how="left", on="enrollment_id")
        .merge(piv_mk,    how="left", on="enrollment_id")
        .merge(last_mk,   how="left", on="enrollment_id")
    )

    # fillna phần mở rộng
    # for col in [
    #     "li_30_count", "li_30_dur_sum", "li_30_xp_sum", "li_30_success_rate",
    #     "li_7_count", "li_7_dur_sum", "li_7_xp_sum", "li_7_success_rate",
    #     "li_7_action_start_lesson", "li_7_action_complete_lesson",
    #     "li_7_action_review_word", "li_7_action_practice_skill",
    #     "li_days_since_last",
    #     "mk_30_count", "mk_30_score_mean",
    #     "mk_7_count", "mk_7_score_mean",
    #     "mk_7_src_pronunciation", "mk_7_src_grammar", "mk_7_src_vocab",
    #     "mk_7_src_listening", "mk_7_src_spelling",
    #     "mk_days_since_last",
    # ]:
    #     if col in df_X.columns:
    #         df_X[col] = df_X[col].fillna(0)

    numeric_cols = [
    "xp_7d","xp_30d","sessions_7d","prof_mean","kw_count","kw_mastered","ease_mean","streak_days",
    "li_30_count","li_30_dur_sum","li_30_xp_sum","li_30_success_rate",
    "li_7_count","li_7_dur_sum","li_7_xp_sum","li_7_success_rate",
    "li_7_action_start_lesson","li_7_action_complete_lesson",
    "li_7_action_review_word","li_7_action_practice_skill",
    "li_days_since_last",
    "mk_30_count","mk_30_score_mean",
    "mk_7_count","mk_7_score_mean",
    "mk_7_src_pronunciation","mk_7_src_grammar","mk_7_src_vocab","mk_7_src_listening","mk_7_src_spelling",
    "mk_days_since_last",
    ]
    for col in numeric_cols:
        if col in df_X.columns:
            df_X[col] = pd.to_numeric(df_X[col], errors="coerce").fillna(0)


    # ---------- LABELS (y): có completed trong target_window_days? ----------
    if not df_sess.empty:
        recent = df_sess[df_sess["completed_at"].notna() & (df_sess["completed_at"] >= target_start)]
        if not recent.empty:
            df_y = (
                recent.groupby("enrollment_id", as_index=False)
                .size()
                .rename(columns={"size": "any_completed"})
            )
            df_y["target_completed"] = (df_y["any_completed"] > 0).astype("int8")
            df_y = df_y[["enrollment_id", "target_completed"]]
        else:
            df_y = pd.DataFrame(columns=["enrollment_id", "target_completed"])
    else:
        df_y = pd.DataFrame(columns=["enrollment_id", "target_completed"])

    # Map: recommendation_id := enrollment_id để join với X.id
    if not df_y.empty:
        df_y = df_y.rename(columns={"enrollment_id": "recommendation_id"})
    else:
        df_y = pd.DataFrame(columns=["recommendation_id", "target_completed"])
    df_y["created_at"] = pd.Timestamp(now)

    # ---------- Upload lên MinIO ----------
    prefix = f"snapshots/{snapshot_id}"
    features_key = f"{prefix}/features.parquet"
    labels_key = f"{prefix}/labels.parquet"

    features_uri = _upload_parquet(df_X, features_key)
    labels_uri = _upload_parquet(df_y, labels_key)

    # ---------- Manifest ----------
    return {
        "features": features_uri,
        "labels": labels_uri,
        "meta": {
            "row_count_features": int(df_X.shape[0]),
            "row_count_labels": int(df_y.shape[0]),
            "start": start.isoformat(),
            "end": now.isoformat(),
            "target_window_days": target_window_days,
        },
    }
