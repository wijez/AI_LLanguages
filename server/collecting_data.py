import pandas as pd
from users.models import User
from languages.models import LanguageEnrollment, Lesson, Skill, TopicProgress, UserSkillStats
from vocabulary.models import KnownWord, Mistake, LearningInteraction
from progress.models import DailyXP

def collect_training_data():
    # enrollment info
    enrollments = LanguageEnrollment.objects.all().values(
        "id", "user_id", "language_id", "level", "total_xp", "streak_days"
    )
    df_enroll = pd.DataFrame(list(enrollments))

    # skill stats
    skills = UserSkillStats.objects.all().values(
        "enrollment_id", "skill_id", "xp", "proficiency_score"
    )
    df_skills = pd.DataFrame(list(skills))

    # known words
    known = KnownWord.objects.all().values(
        "enrollment_id", "word_id", "score"
    )
    df_known = pd.DataFrame(list(known))

    # mistakes
    mistakes = Mistake.objects.all().values(
        "user_id", "enrollment_id", "source", "score", "timestamp"
    )
    df_mistakes = pd.DataFrame(list(mistakes))

    # interactions
    interactions = LearningInteraction.objects.all().values(
        "user_id", "enrollment_id", "lesson_id", "action", "success", "xp_earned", "duration_seconds", "created_at"
    )
    df_interactions = pd.DataFrame(list(interactions))

    # daily xp
    xp = DailyXP.objects.all().values("user_id", "date", "xp")
    df_xp = pd.DataFrame(list(xp))

    return {
        "enrollments": df_enroll,
        "skills": df_skills,
        "known_words": df_known,
        "mistakes": df_mistakes,
        "interactions": df_interactions,
        "daily_xp": df_xp
    }
