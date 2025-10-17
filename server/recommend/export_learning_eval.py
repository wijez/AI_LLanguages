# server/recommend/management/commands/export_learning_eval.py
from __future__ import annotations
import os
from datetime import datetime, timedelta
import pandas as pd
from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import User
from languages.models import LanguageEnrollment
from learning.models import LessonSession
from progress.models import DailyXP
from vocabulary.models import LearningInteraction, Mistake, KnownWord

class Command(BaseCommand):
    help = "Export user learning data for offline evaluation (CSV/Parquet)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60, help="Lookback window for activity.")
        parser.add_argument("--target_window_days", type=int, default=7, help="Window for ground-truth label.")
        parser.add_argument("--outdir", type=str, default="exports_eval", help="Output directory.")
        parser.add_argument("--fmt", type=str, default="parquet", choices=["parquet","csv"], help="File format.")

    def handle(self, *args, **opts):
        days = opts["days"]
        tgt = opts["target_window_days"]
        outdir = opts["outdir"]
        fmt = opts["fmt"]

        os.makedirs(outdir, exist_ok=True)
        now = timezone.now()
        start = now - timedelta(days=days)
        target_start = now - timedelta(days=tgt)

        # ---------- enrollments ----------
        enr = list(LanguageEnrollment.objects.select_related("user","language").values(
            "id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"
        ))
        df_enr = pd.DataFrame(enr) if enr else pd.DataFrame(columns=[
            "id","user_id","language_id","level","total_xp","streak_days","last_practiced","created_at"
        ])
        df_enr.rename(columns={"id":"enrollment_id"}, inplace=True)

        # ---------- daily xp (30d) ----------
        dx = list(DailyXP.objects.filter(date__gte=(now - timedelta(days=30)).date()).values("user_id","date","xp"))
        df_dx = pd.DataFrame(dx) if dx else pd.DataFrame(columns=["user_id","date","xp"])
        if not df_dx.empty:
            df_dx["date"] = pd.to_datetime(df_dx["date"])
        dx7 = (df_dx[df_dx["date"] >= (now - timedelta(days=7)).date()]
               .groupby("user_id", as_index=False)["xp"].sum().rename(columns={"xp":"xp_7d"})) if not df_dx.empty else pd.DataFrame(columns=["user_id","xp_7d"])
        dx30 = (df_dx.groupby("user_id",as_index=False)["xp"].sum().rename(columns={"xp":"xp_30d"})) if not df_dx.empty else pd.DataFrame(columns=["user_id","xp_30d"])

        # ---------- lesson sessions ----------
        sess = list(LessonSession.objects.filter(started_at__gte=start).values(
            "enrollment_id","status","started_at","completed_at","duration_seconds","correct_answers","incorrect_answers","total_questions","xp_earned"
        ))
        df_sess = pd.DataFrame(sess) if sess else pd.DataFrame(columns=[
            "enrollment_id","status","started_at","completed_at","duration_seconds","correct_answers","incorrect_answers","total_questions","xp_earned"
        ])
        if not df_sess.empty:
            for c in ["started_at","completed_at"]:
                if c in df_sess: df_sess[c] = pd.to_datetime(df_sess[c])
        # label: có completed trong 7 ngày gần đây?
        if not df_sess.empty and "completed_at" in df_sess:
            recent = df_sess[df_sess["completed_at"].notna() & (df_sess["completed_at"] >= target_start)]
            y = (recent.groupby("enrollment_id", as_index=False).size()
                      .rename(columns={"size":"any_completed"}))
            y["gt_target_completed"] = (y["any_completed"] > 0).astype("int8")
            df_y = y[["enrollment_id","gt_target_completed"]]
        else:
            df_y = pd.DataFrame(columns=["enrollment_id","gt_target_completed"])

        # aggregates 7d/30d cho session
        if not df_sess.empty:
            s7 = df_sess[df_sess["completed_at"].notna() & (df_sess["completed_at"] >= now - timedelta(days=7))]
            s7_agg = (s7.groupby("enrollment_id", as_index=False)
                        .agg(sessions_7d=("status","size"),
                             sess7_dur_sum=("duration_seconds","sum"),
                             sess7_xp_sum=("xp_earned","sum")))
        else:
            s7_agg = pd.DataFrame(columns=["enrollment_id","sessions_7d","sess7_dur_sum","sess7_xp_sum"])

        # ---------- known words ----------
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

        # ---------- skill proficiency ----------
        from languages.models import UserSkillStats
        st = list(UserSkillStats.objects.values("enrollment_id","proficiency_score"))
        df_st = pd.DataFrame(st) if st else pd.DataFrame(columns=["enrollment_id","proficiency_score"])
        prof = (df_st.groupby("enrollment_id",as_index=False)["proficiency_score"].mean()
                      .rename(columns={"proficiency_score":"prof_mean"})) if not df_st.empty else pd.DataFrame(columns=["enrollment_id","prof_mean"])

        # ---------- interactions 30d/7d ----------
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
            last_li = (df_li.groupby("enrollment_id",as_index=False)["created_at"].max()
                           .rename(columns={"created_at":"last_li_ts"}))
            if not last_li.empty:
                last_li["li_days_since_last"] = (now - last_li["last_li_ts"]).dt.total_seconds()/86400.0
                last_li = last_li[["enrollment_id","li_days_since_last"]]
        else:
            li30 = pd.DataFrame(columns=["enrollment_id","li_30_count","li_30_dur_sum","li_30_xp_sum","li_30_success_rate"])
            li7_agg = pd.DataFrame(columns=["enrollment_id","li_7_count","li_7_dur_sum","li_7_xp_sum","li_7_success_rate"])
            piv_li = pd.DataFrame(columns=["enrollment_id","li_7_action_start_lesson","li_7_action_complete_lesson","li_7_action_review_word","li_7_action_practice_skill"])
            last_li = pd.DataFrame(columns=["enrollment_id","li_days_since_last"])

        # ---------- mistakes 30d/7d ----------
        mk = list(Mistake.objects.filter(timestamp__gte=now - timedelta(days=30)).values("enrollment_id","source","score","timestamp"))
        df_mk = pd.DataFrame(mk) if mk else pd.DataFrame(columns=["enrollment_id","source","score","timestamp"])
        if not df_mk.empty:
            df_mk["timestamp"] = pd.to_datetime(df_mk["timestamp"])
            mk30 = (df_mk.groupby("enrollment_id",as_index=False)
                        .agg(mk_30_count=("source","size"),
                             mk_30_score_mean=("score","mean")))
            mk7 = df_mk[df_mk["timestamp"] >= now - timedelta(days=7)]
            mk7_agg = (mk7.groupby("enrollment_id",as_index=False)
                          .agg(mk_7_count=("source","size"),
                               mk_7_score_mean=("score","mean"))) if not mk7.empty else pd.DataFrame(columns=["enrollment_id","mk_7_count","mk_7_score_mean"])
            piv_mk = (mk7.assign(cnt=1).pivot_table(index="enrollment_id",columns="source",values="cnt",aggfunc="sum",fill_value=0).reset_index()) if not mk7.empty else pd.DataFrame()
            if not piv_mk.empty:
                piv_mk.columns = ["enrollment_id"] + [f"mk_7_src_{c}" for c in piv_mk.columns if c!="enrollment_id"]
            last_mk = (df_mk.groupby("enrollment_id",as_index=False)["timestamp"].max()
                           .rename(columns={"timestamp":"last_mk_ts"}))
            if not last_mk.empty:
                last_mk["mk_days_since_last"] = (now - last_mk["last_mk_ts"]).dt.total_seconds()/86400.0
                last_mk = last_mk[["enrollment_id","mk_days_since_last"]]
        else:
            mk30 = pd.DataFrame(columns=["enrollment_id","mk_30_count","mk_30_score_mean"])
            mk7_agg = pd.DataFrame(columns=["enrollment_id","mk_7_count","mk_7_score_mean"])
            piv_mk = pd.DataFrame(columns=["enrollment_id","mk_7_src_pronunciation","mk_7_src_grammar","mk_7_src_vocab","mk_7_src_listening","mk_7_src_spelling"])
            last_mk = pd.DataFrame(columns=["enrollment_id","mk_days_since_last"])

        # ---------- merge full eval ----------
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

        fill_zero = [
            "xp_7d","xp_30d","sessions_7d","sess7_dur_sum","sess7_xp_sum","prof_mean",
            "kw_count","kw_mastered","ease_mean",
            "li_30_count","li_30_dur_sum","li_30_xp_sum","li_30_success_rate",
            "li_7_count","li_7_dur_sum","li_7_xp_sum","li_7_success_rate",
            "li_7_action_start_lesson","li_7_action_complete_lesson","li_7_action_review_word","li_7_action_practice_skill",
            "li_days_since_last",
            "mk_30_count","mk_30_score_mean","mk_7_count","mk_7_score_mean",
            "mk_7_src_pronunciation","mk_7_src_grammar","mk_7_src_vocab","mk_7_src_listening","mk_7_src_spelling",
            "mk_days_since_last",
            "gt_target_completed",
        ]
        for c in fill_zero:
            if c in df_eval.columns:
                df_eval[c] = df_eval[c].fillna(0)

        # ---------- save ----------
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(outdir, f"learning_eval_{stamp}")
        if fmt == "parquet":
            df_eval.to_parquet(base + ".parquet", index=False)
        else:
            df_eval.to_csv(base + ".csv", index=False)

        self.stdout.write(self.style.SUCCESS(f"Exported eval data to {base}.{fmt}"))
        self.stdout.write(f"Rows: {len(df_eval)}, positive rate: {float(df_eval['gt_target_completed'].mean()) if 'gt_target_completed' in df_eval else 0:.3f}")
