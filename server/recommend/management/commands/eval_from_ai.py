# server/recommend/management/commands/eval_from_ai.py
from __future__ import annotations
import os
from datetime import datetime, timedelta
import pandas as pd

from django.core.management.base import BaseCommand
from django.utils import timezone

from recommend.utils.ai_client import ai_fetch_predictions
from languages.models import LanguageEnrollment, UserSkillStats
from learning.models import LessonSession
from progress.models import DailyXP
from vocabulary.models import KnownWord, LearningInteraction, Mistake

class Command(BaseCommand):
    help = "Build eval data, call AI /api/predict, merge & print metrics."

    def add_arguments(self, parser):
        parser.add_argument("--snapshot_id", type=str, required=True)
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--target_window_days", type=int, default=7)
        parser.add_argument("--features_uri", type=str, default=None)
        parser.add_argument("--save_eval", type=str, default=None)  # path parquet/csv optional
        parser.add_argument("--topk", type=int, default=50)

    def handle(self, *args, **opts):
        snapshot_id = opts["snapshot_id"]
        days = opts["days"]
        tgt = opts["target_window_days"]
        features_uri = opts["features_uri"]
        save_eval = opts["save_eval"]
        topk = opts["topk"]

        now = timezone.now()
        start = now - timedelta(days=days)
        target_start = now - timedelta(days=tgt)

        # ---- enrollments
        enr = list(LanguageEnrollment.objects.values("id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"))
        df_enr = pd.DataFrame(enr) if enr else pd.DataFrame(columns=["id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"])
        df_enr.rename(columns={"id":"enrollment_id"}, inplace=True)

        # ---- daily xp
        dx = list(DailyXP.objects.filter(
            date__gte=(now - timedelta(days=30)).date()
        ).values("user_id","date","xp"))

        df_dx = pd.DataFrame(dx) if dx else pd.DataFrame(columns=["user_id","date","xp"])
        if not df_dx.empty:
            # ép về date để so sánh đồng kiểu
            df_dx["date"] = pd.to_datetime(df_dx["date"]).dt.date

        ts7 = (now - timedelta(days=7)).date()
        dx7 = (
            df_dx[df_dx["date"] >= ts7]
            .groupby("user_id", as_index=False)["xp"]
            .sum()
            .rename(columns={"xp": "xp_7d"})
        ) if not df_dx.empty else pd.DataFrame(columns=["user_id","xp_7d"])

        dx30 = (
            df_dx.groupby("user_id", as_index=False)["xp"]
                .sum()
                .rename(columns={"xp": "xp_30d"})
        ) if not df_dx.empty else pd.DataFrame(columns=["user_id","xp_30d"])


        # ---- lesson sessions + label
        sess = list(LessonSession.objects.filter(started_at__gte=start).values("enrollment_id","status","completed_at","duration_seconds","xp_earned"))
        df_sess = pd.DataFrame(sess) if sess else pd.DataFrame(columns=["enrollment_id","status","completed_at","duration_seconds","xp_earned"])
        if not df_sess.empty and "completed_at" in df_sess:
            df_sess["completed_at"] = pd.to_datetime(df_sess["completed_at"])
            recent = df_sess[df_sess["completed_at"].notna() & (df_sess["completed_at"] >= target_start)]
            if not recent.empty:
                y = (recent.groupby("enrollment_id", as_index=False).size().rename(columns={"size":"any_completed"}))
                y["gt_target_completed"] = (y["any_completed"] > 0).astype("int8")
                df_y = y[["enrollment_id","gt_target_completed"]]
            else:
                df_y = pd.DataFrame(columns=["enrollment_id","gt_target_completed"])
            s7 = df_sess[df_sess["completed_at"].notna() & (df_sess["completed_at"] >= now - timedelta(days=7))]
            s7_agg = (s7.groupby("enrollment_id",as_index=False)
                        .agg(sessions_7d=("status","size"),
                             sess7_dur_sum=("duration_seconds","sum"),
                             sess7_xp_sum=("xp_earned","sum"))) if not s7.empty else pd.DataFrame(columns=["enrollment_id","sessions_7d","sess7_dur_sum","sess7_xp_sum"])
        else:
            df_y = pd.DataFrame(columns=["enrollment_id","gt_target_completed"])
            s7_agg = pd.DataFrame(columns=["enrollment_id","sessions_7d","sess7_dur_sum","sess7_xp_sum"])

        # ---- known words
        kw = list(KnownWord.objects.values("enrollment_id","status","ease_factor"))
        df_kw = pd.DataFrame(kw) if kw else pd.DataFrame(columns=["enrollment_id","status","ease_factor"])
        if not df_kw.empty:
            df_kw["is_mastered"] = (df_kw["status"]=="mastered").astype("int8")
            kw_agg = (df_kw.groupby("enrollment_id",as_index=False)
                        .agg(kw_count=("status","size"),
                             kw_mastered=("is_mastered","sum"),
                             ease_mean=("ease_factor","mean")))
        else:
            kw_agg = pd.DataFrame(columns=["enrollment_id","kw_count","kw_mastered","ease_mean"])

        # ---- proficiency
        st = list(UserSkillStats.objects.values("enrollment_id","proficiency_score"))
        df_st = pd.DataFrame(st) if st else pd.DataFrame(columns=["enrollment_id","proficiency_score"])
        prof = (df_st.groupby("enrollment_id",as_index=False)["proficiency_score"].mean().rename(columns={"proficiency_score":"prof_mean"})) if not df_st.empty else pd.DataFrame(columns=["enrollment_id","prof_mean"])

        # ---- interactions (30d/7d)
        li = list(LearningInteraction.objects.filter(created_at__gte=now - timedelta(days=30)).values(
            "enrollment_id","action","success","duration_seconds","xp_earned","created_at"
        ))
        df_li = pd.DataFrame(li) if li else pd.DataFrame(columns=["enrollment_id","action","success","duration_seconds","xp_earned","created_at"])
        if not df_li.empty:
            df_li["created_at"] = pd.to_datetime(df_li["created_at"])
            li30 = (df_li.groupby("enrollment_id",as_index=False)
                      .agg(li_30_count=("action","size"),
                           li_30_dur_sum=("duration_seconds","sum"),
                           li_30_xp_sum=("xp_earned","sum"),
                           li_30_success_rate=("success","mean")))
            li7 = df_li[df_li["created_at"] >= now - timedelta(days=7)]
            li7_agg = (li7.groupby("enrollment_id",as_index=False)
                        .agg(li_7_count=("action","size"),
                             li_7_dur_sum=("duration_seconds","sum"),
                             li_7_xp_sum=("xp_earned","sum"),
                             li_7_success_rate=("success","mean"))) if not li7.empty else pd.DataFrame(columns=["enrollment_id","li_7_count","li_7_dur_sum","li_7_xp_sum","li_7_success_rate"])
            piv_li = (li7.assign(cnt=1).pivot_table(index="enrollment_id",columns="action",values="cnt",aggfunc="sum",fill_value=0).reset_index()) if not li7.empty else pd.DataFrame()
            if not piv_li.empty:
                piv_li.columns = ["enrollment_id"] + [f"li_7_action_{c}" for c in piv_li.columns if c!="enrollment_id"]
            last_li = (df_li.groupby("enrollment_id",as_index=False)["created_at"].max().rename(columns={"created_at":"last_li_ts"}))
            if not last_li.empty:
                last_li["li_days_since_last"] = (now - last_li["last_li_ts"]).dt.total_seconds()/86400.0
                last_li = last_li[["enrollment_id","li_days_since_last"]]
        else:
            li30 = pd.DataFrame(columns=["enrollment_id","li_30_count","li_30_dur_sum","li_30_xp_sum","li_30_success_rate"])
            li7_agg = pd.DataFrame(columns=["enrollment_id","li_7_count","li_7_dur_sum","li_7_xp_sum","li_7_success_rate"])
            piv_li = pd.DataFrame(columns=["enrollment_id","li_7_action_start_lesson","li_7_action_complete_lesson","li_7_action_review_word","li_7_action_practice_skill"])
            last_li = pd.DataFrame(columns=["enrollment_id","li_days_since_last"])

        # ---- mistakes (30d/7d)
        mk = list(Mistake.objects.filter(timestamp__gte=now - timedelta(days=30)).values("enrollment_id","source","score","timestamp"))
        df_mk = pd.DataFrame(mk) if mk else pd.DataFrame(columns=["enrollment_id","source","score","timestamp"])
        if not df_mk.empty:
            df_mk["timestamp"] = pd.to_datetime(df_mk["timestamp"])
            mk30 = (df_mk.groupby("enrollment_id",as_index=False).agg(mk_30_count=("source","size"), mk_30_score_mean=("score","mean")))
            mk7 = df_mk[df_mk["timestamp"] >= now - timedelta(days=7)]
            mk7_agg = (mk7.groupby("enrollment_id",as_index=False).agg(mk_7_count=("source","size"), mk_7_score_mean=("score","mean"))) if not mk7.empty else pd.DataFrame(columns=["enrollment_id","mk_7_count","mk_7_score_mean"])
            piv_mk = (mk7.assign(cnt=1).pivot_table(index="enrollment_id",columns="source",values="cnt",aggfunc="sum",fill_value=0).reset_index()) if not mk7.empty else pd.DataFrame()
            if not piv_mk.empty:
                piv_mk.columns = ["enrollment_id"] + [f"mk_7_src_{c}" for c in piv_mk.columns if c!="enrollment_id"]
            last_mk = (df_mk.groupby("enrollment_id",as_index=False)["timestamp"].max().rename(columns={"timestamp":"last_mk_ts"}))
            if not last_mk.empty:
                last_mk["mk_days_since_last"] = (now - last_mk["last_mk_ts"]).dt.total_seconds()/86400.0
                last_mk = last_mk[["enrollment_id","mk_days_since_last"]]
        else:
            mk30 = pd.DataFrame(columns=["enrollment_id","mk_30_count","mk_30_score_mean"])
            mk7_agg = pd.DataFrame(columns=["enrollment_id","mk_7_count","mk_7_score_mean"])
            piv_mk = pd.DataFrame(columns=["enrollment_id","mk_7_src_pronunciation","mk_7_src_grammar","mk_7_src_vocab","mk_7_src_listening","mk_7_src_spelling"])
            last_mk = pd.DataFrame(columns=["enrollment_id","mk_days_since_last"])

        df_eval = (df_enr
            .merge(dx7, how="left", on="user_id")
            .merge(dx30, how="left", on="user_id")
            .merge(s7_agg, how="left", on="enrollment_id")
            .merge(prof, how="left", on="enrollment_id")
            .merge(kw_agg, how="left", on="enrollment_id")
            .merge(li30, how="left", on="enrollment_id")
            .merge(li7_agg, how="left", on="enrollment_id")
            .merge(piv_li, how="left", on="enrollment_id")
            .merge(last_li, how="left", on="enrollment_id")
            .merge(mk30, how="left", on="enrollment_id")
            .merge(mk7_agg, how="left", on="enrollment_id")
            .merge(piv_mk, how="left", on="enrollment_id")
            .merge(last_mk, how="left", on="enrollment_id")
            .merge(df_y, how="left", on="enrollment_id")
        )

        # fill 0
        for c in [col for col in df_eval.columns if col not in ("enrollment_id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at")]:
            df_eval[c] = df_eval[c].fillna(0)

        # save optional
        if save_eval:
            if save_eval.endswith(".parquet"):
                df_eval.to_parquet(save_eval, index=False)
            else:
                df_eval.to_csv(save_eval, index=False)

        # ---- call AI predict
        preds = ai_fetch_predictions(snapshot_id=snapshot_id, features_uri=features_uri, enrollment_ids=None)
        if not preds:
            self.stdout.write(self.style.ERROR("No predictions returned from AI."))
            return

        df_pred = pd.DataFrame(preds)  # columns: enrollment_id, p_hat
        df = df_eval.merge(df_pred, how="inner", on="enrollment_id")
        if df.empty or "gt_target_completed" not in df.columns:
            self.stdout.write(self.style.ERROR("Eval join empty or missing ground-truth label."))
            return

        # ---- metrics
        import numpy as np
        from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

        y = df["gt_target_completed"].astype(int).values
        p = np.clip(df["p_hat"].astype(float).values, 0.0, 1.0)

        auc = roc_auc_score(y, p) if len(np.unique(y)) > 1 else float("nan")
        aupr = average_precision_score(y, p)
        brier = brier_score_loss(y, p)

        topk = min(topk, len(df))
        hit_rate = df.sort_values("p_hat", ascending=False).head(topk)["gt_target_completed"].mean()

        self.stdout.write(self.style.SUCCESS(f"AUC:   {auc:.4f}"))
        self.stdout.write(self.style.SUCCESS(f"AUPRC: {aupr:.4f}"))
        self.stdout.write(self.style.SUCCESS(f"Brier: {brier:.4f}"))
        self.stdout.write(self.style.SUCCESS(f"Top-{topk} HitRate: {hit_rate:.4f}"))

        # Calibration buckets
        df["bucket"] = pd.qcut(df["p_hat"], 10, duplicates="drop")
        calib = df.groupby("bucket").agg(
            mean_pred=("p_hat","mean"),
            emp_rate=("gt_target_completed","mean"),
            n=("p_hat","size")
        ).reset_index()
        self.stdout.write("Calibration by decile:")
        self.stdout.write(calib.to_string(index=False))
