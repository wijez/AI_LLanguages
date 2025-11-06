from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from languages.models import LanguageEnrollment
from social.serializers import (
    CalendarEventSerializer, FriendSerializer, LeaderboardEntrySerializer
)
from social.models import (
    Friend, CalendarEvent, LeaderboardEntry
)
from django.db.models import Sum, F, Q
from django.db.models.functions import Rank
from django.db.models import Window
from rest_framework.response import Response
from rest_framework.views import APIView
from users.models import User


class FriendViewSet(viewsets.ModelViewSet):
    queryset = Friend.objects.all()
    serializer_class = FriendSerializer


class CalendarEventViewSet(viewsets.ModelViewSet):
    queryset = CalendarEvent.objects.all()
    serializer_class = CalendarEventSerializer


class LeaderboardEntryViewSet(viewsets.ModelViewSet):
    serializer_class = LeaderboardEntrySerializer

    def get_queryset(self):
        qs = (LeaderboardEntry.objects
              .select_related('user', 'language')
              .all())

        abbr = self.request.query_params.get('abbreviation')

        lang_param = self.request.query_params.get('language')

        if abbr:
            qs = qs.filter(language__abbreviation__iexact=abbr)
        elif lang_param:
            if lang_param.isdigit():
                qs = qs.filter(language_id=lang_param)
            else:
                qs = qs.filter(language__abbreviation__iexact=lang_param)
        date = self.request.query_params.get('date')
        if date:
            qs = qs.filter(date=date)
        return qs.order_by('-xp', 'rank', 'id')


class LeaderboardAllView(APIView):
    permission_classes = [AllowAny] 

    def get(self, request):
        limit = int(request.query_params.get('limit', 50))
        friends_only = request.query_params.get('friends_only') == '1'

        # [LOGIC MỚI]
        # Lấy "toàn bộ kinh nghiệm" từ LanguageEnrollment.total_xp
        base = (
            LanguageEnrollment.objects
            .values('user')  # Nhóm theo User
            .annotate(
                # Tính tổng XP của user trên TẤT CẢ ngôn ngữ họ đã học
                total_xp=Sum('total_xp') 
            )
            .annotate(
                # Xếp hạng dựa trên tổng XP đó
                rank=Window(
                    expression=Rank(),
                    order_by=[F('total_xp').desc()]
                )
            )
            .order_by('rank') # Sắp xếp theo hạng
            .filter(total_xp__gt=0) # Chỉ lấy user có XP
        )

        if friends_only and request.user.is_authenticated:
            # danh sách bạn đã accepted (2 chiều)
            friend_ids = Friend.objects.filter(accepted=True).filter(
                Q(from_user=request.user) | Q(to_user=request.user)
            ).values_list('from_user_id', 'to_user_id')

            ids = set([request.user.id]) # Bao gồm cả chính mình
            uid = request.user.id
            for a, b in friend_ids:
                ids.add(b if a == uid else a)

            base = base.filter(user__in=list(ids))

        rows = list(base[:limit])

        # Gắn thông tin user
        users = {u.id: u for u in User.objects.filter(id__in=[r['user'] for r in rows])}
        data = [{
            'user': {
                'id': r['user'],
                'username': getattr(users.get(r['user']), 'username', 'User'),
                'avatar': getattr(users.get(r['user']), 'avatar', None) if users.get(r['user']) else None,
            },
            'rank': r['rank'],
            'xp': r['total_xp'],
            'period_label': 'All-time',
        } for r in rows]

        return Response(data)