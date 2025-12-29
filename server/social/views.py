from django.shortcuts import render
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from languages.models import LanguageEnrollment
from utils.permissions import CanMarkOwnNotificationRead, IsAdminOrSuperAdmin
from utils.send_mail import send_user_email
from social.serializers import *
from social.models import (
    Friend, CalendarEvent, LeaderboardEntry
)
from django.db.models import Sum, F, Q
from django.db.models.functions import Rank
from django.db.models import Window
from rest_framework.response import Response
from rest_framework.views import APIView
from users.models import User
from social.services import recalc_badges_for_user
import logging

logger = logging.getLogger(__name__)


class FriendViewSet(viewsets.ModelViewSet):
    """
    /friends/:
      - POST: gửi lời mời (from_user = request.user, accepted=False)
      - GET:  xem tất cả quan hệ (chỉ các quan hệ có liên quan đến request.user)
    /friends/{id}/accept/: chỉ user là to_user mới được accept
    """
    serializer_class = FriendSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        u = self.request.user
        return Friend.objects.filter(Q(from_user=u) | Q(to_user=u)).select_related("from_user", "to_user")

    def perform_create(self, serializer):
        to_user = serializer.validated_data.get("to_user")
        me = self.request.user
        if not to_user or to_user == me:
            raise serializers.ValidationError({"to_user": "to_user không hợp lệ."})

        # Chặn trùng 2 chiều (A->B hoặc B->A, pending/accepted)
        exists = Friend.objects.filter(
            (Q(from_user=me, to_user=to_user) | Q(from_user=to_user, to_user=me))
        ).exists()
        if exists:
            raise serializers.ValidationError({"detail": "Quan hệ/bạn bè đã tồn tại hoặc đang chờ."})

        fr = serializer.save(from_user=me, accepted=False)
        try:
            from_name = (
                (getattr(me, "get_full_name", None) or (lambda: ""))()
                or getattr(me, "username", "")
                or me.email
            )
            send_user_email(
                to_user,
                template_key="friend_request",
                subject="[Aivory] Bạn có lời mời kết bạn mới",
                from_username=from_name,
            )
        except Exception as e:
            logger.warning("Send friend request email failed: %s", e)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        """
        Chỉ người nhận (to_user) mới được accept.
        """
        try:
            fr = self.get_queryset().get(pk=pk)
        except Friend.DoesNotExist:
            return Response({"detail": "Không tìm thấy lời mời."}, status=status.HTTP_404_NOT_FOUND)

        if fr.to_user != request.user:
            return Response({"detail": "Bạn không có quyền chấp nhận lời mời này."}, status=status.HTTP_403_FORBIDDEN)

        if fr.accepted:
            return Response({"detail": "Đã là bạn bè."}, status=status.HTTP_400_BAD_REQUEST)

        fr.accepted = True
        fr.save(update_fields=["accepted", "updated_at"])

        try:
            recalc_badges_for_user(fr.from_user, limit_types=["friend_count"])
            recalc_badges_for_user(fr.to_user,   limit_types=["friend_count"])
        except Exception as e:
            print("[badges] recalc after friend accept failed:", e)

        return Response(FriendSerializer(fr).data, status=status.HTTP_200_OK)



class CalendarEventViewSet(viewsets.ModelViewSet):
    queryset = CalendarEvent.objects.all()
    serializer_class = CalendarEventSerializer
    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        # Các hành động create, update, delete, patch yêu cầu quyền Admin/SuperAdmin
        return [ IsAdminOrSuperAdmin()] 

    def get_queryset(self):
        user = self.request.user
        
        if user.is_staff or user.is_superuser:
            return CalendarEvent.objects.all().order_by("-start")

        return CalendarEvent.objects.filter(
            Q(user__is_staff=True) | 
            Q(user__is_superuser=True) | 
            Q(participants=user)
        ).distinct().order_by("start")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    


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


class BadgeViewSet(viewsets.ModelViewSet):
    queryset = Badge.objects.all()
    serializer_class = BadgeSerializer
    permission_classes = [IsAuthenticated]

class UserBadgeViewSet(viewsets.ModelViewSet):
    serializer_class = UserBadgeSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return UserBadge.objects.filter(user=self.request.user)

class NotificationViewSet(viewsets.ModelViewSet):
    serializer_class = NotificationSerializer
    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsAuthenticated()]
        if self.action == "mark_read":
            return [IsAuthenticated(), CanMarkOwnNotificationRead()]
        return [IsAuthenticated(), IsAdminOrSuperAdmin()]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff or user.is_superuser:
            # admin có thể xem tất cả
            return Notification.objects.all().order_by("-created_at")
        # user chỉ xem thông báo của chính họ
        return Notification.objects.filter(user=user).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        if isinstance(instance, list):
            data = NotificationSerializer(instance, many=True).data
            return Response(data, status=status.HTTP_201_CREATED)
        data = NotificationSerializer(instance).data
        return Response(data, status=status.HTTP_201_CREATED)
    
    @action(
    detail=True,
    methods=["patch"],
    url_path="read"
    )
    def mark_read(self, request, pk=None):
        notification = self.get_object()

        if notification.read_at:
            return Response({"status": "already_read"})

        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])

        return Response({
            "status": "ok",
            "id": notification.id,
            "read_at": notification.read_at,
        })
    @action(
    detail=False,
    methods=["patch"],
    url_path="read-all",
    permission_classes=[IsAuthenticated],
    )
    def mark_all_read(self, request):
        user = request.user

        qs = Notification.objects.filter(
            user=user,
            read_at__isnull=True
        )

        updated_count = qs.update(read_at=timezone.now())

        return Response(
            {
                "status": "ok",
                "marked": updated_count,
            },
            status=status.HTTP_200_OK,
        )