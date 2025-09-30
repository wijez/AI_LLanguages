from django.shortcuts import render
from rest_framework import viewsets
from languages.models import ( 
    Language, Lesson, LanguageEnrollment, Topic, 
    TopicProgress, Skill,
    SuggestedLesson, UserSkillStats
)
from languages.serializers import (
    LanguageSerializer, LanguageEnrollmentSerializer, TopicProgressSerializer, TopicSerializer,
    SkillSerializer, LessonSerializer, SuggestedLessonSerializer, UserSkillStatsSerializer
)

class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer


class LanguageEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = LanguageEnrollment.objects.all()
    serializer_class = LanguageEnrollmentSerializer


class LessonViewSet(viewsets.ModelViewSet):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer


class TopicViewSet(viewsets.ModelViewSet):
    queryset = Topic.objects.all()
    serializer_class = TopicSerializer


class TopicProgressViewSet(viewsets.ModelViewSet):
    queryset = TopicProgress.objects.all()
    serializer_class = TopicProgressSerializer


class SkillViewSet(viewsets.ModelViewSet):
    queryset = Skill.objects.all()
    serializer_class = SkillSerializer


class SuggestedLessonViewSet(viewsets.ModelViewSet):
    queryset = SuggestedLesson.objects.all()
    serializer_class = SuggestedLessonSerializer


class UserSkillStatsViewSet(viewsets.ModelViewSet):
    queryset = UserSkillStats.objects.all()
    serializer_class = UserSkillStatsSerializer