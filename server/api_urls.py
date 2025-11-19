from ntpath import basename
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from users.views import *
from social.views import * 
from languages.views import *
from progress.views import * 
from vocabulary.views import * 
from learning.views import * 


router = DefaultRouter()

# User
router.register(r'users', UserViewset) 
router.register(r'settings', AccountSettingViewset)
router.register(r'switchaccount', AccountSwitchViewset)

# Language
router.register(r'languages', LanguageViewSet)
router.register(r'enrollments', LanguageEnrollmentViewSet, basename='language-enrollment')
router.register(r'lessons', LessonViewSet)
router.register(r'topics', TopicViewSet, basename='topic')
router.register(r'skills', SkillViewSet, basename='skill')
router.register(r'progress', TopicProgressViewSet)
router.register(r'user-skill-stats', UserSkillStatsViewSet, basename='user-skill-stats')
router.register(r"skill-stats", SkillStatsViewSet, basename="skill-stats")
router.register(r'roleplay-scenario',RoleplayScenarioViewSet, basename='roleplay-scenario')
router.register(r'roleplay-block',  RoleplayBlockViewSet, basename='roleplay-block')
router.register(r'roleplay-session', RoleplaySessionViewSet, basename='roleplay-session')

#Learning
router.register(r'learning/sessions', LessonSessionViewSet, basename='learning-session')
router.register(r'skill_sessions', SkillSessionViewSet, basename='skill-session')


# Vocabulary

router.register(r'known-words', KnownWordViewSet, basename='knownword')
router.register(r'translations', TranslationViewSet, basename='translation')
router.register(r'words', WordViewSet, basename='word')
router.register(r'mistake', MistakeViewSet, basename='mistake' )
router.register('learning-interaction', LearningInteractionViewSet, basename='learninginteraction')

#Progress 
router.register(r'daily-xp', DailyXPViewSet)

#Social 
router.register(r'friends', FriendViewSet, basename='friend')
router.register(r'calendar-events', CalendarEventViewSet, basename='calendarevent')
router.register(r'leaderboard-entries', LeaderboardEntryViewSet, basename='leaderboardentry')
router.register(r'badges', BadgeViewSet, basename='badge')
router.register(r'my-badges', UserBadgeViewSet, basename='user-badge')
router.register(r'notifications', NotificationViewSet, basename='notification')



urlpatterns = router.urls + [
    path("export/chat_training.jsonl", export_chat_training, name="export_chat_training"),
    path('leaderboard', LeaderboardAllView.as_view()),
    path('practice/overview', practice_overview, name="practice-overview")
] 

