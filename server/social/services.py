from django.db import transaction, models, IntegrityError
from django.db.models import F, Q, Max, Sum
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from progress.models import XPEvent, DailyXP
from languages.models import LanguageEnrollment, Skill
from social.models import Badge, Friend, Notification, UserBadge
from learning.models import LessonSession, SkillSession

# engine
BADGE_TYPE_LESSONS = "lessons_completed"
BADGE_TYPE_SPEAK   = "speaking_sessions"
BADGE_TYPE_FRIENDS = "friend_count"
BADGE_TYPE_TOTAL_XP = "total_xp"
BADGE_TYPE_STREAK  = "streak_days"

def _emit_leaderboard_changed(user_id: int):
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)("lb.all", {"type": "lb.changed_all"})

    # Bạn bè của user này
    friend_ids = set()
    qs = Friend.objects.filter(accepted=True).filter(
        models.Q(from_user_id=user_id) | models.Q(to_user_id=user_id)
    ).values_list("from_user_id", "to_user_id")
    for a, b in qs:
        friend_ids.add(a); friend_ids.add(b)
    friend_ids.discard(user_id)
    for fid in friend_ids:
        async_to_sync(layer.group_send)(f"lb.friends.{fid}", {"type": "lb.changed_friends"})

@transaction.atomic
def award_xp_from_lesson(*, user, source_id: str, amount: int):
    """Cộng XP cho user khi hoàn thành một lesson/session.
    Idempotent nhờ UniqueConstraint trên XPEvent.
    source_id: khoá duy nhất đại diện cho lần hoàn thành .
    """
    amount = int(amount or 0)
    if amount <= 0:
        return {"ok": True, "awarded": False, "reason": "non_positive_amount"}
    created = False
    try:
        XPEvent.objects.create(
            user=user,
            source_type="lesson",
            source_id=str(source_id),
            amount=amount,
        )
    except IntegrityError:
        return {"ok": True, "awarded": False, "reason": "already_awarded"}

    # 2) Cộng DailyXP (get_or_create + UPDATE bằng F(); không dùng F() trong INSERT)
    today = timezone.localdate()
    obj, _ = DailyXP.objects.select_for_update().get_or_create(
        user=user,
        date=today,
        defaults={"xp": 0},  # đảm bảo INSERT có giá trị số cụ thể
    )
    DailyXP.objects.filter(pk=obj.pk).update(xp=F("xp") + amount)
    obj.refresh_from_db(fields=["xp"])

    # 3) Phát WS để FE refetch
    _emit_leaderboard_changed(user.id)
    return {"ok": True, "awarded": True, "amount": amount, "xp_today": obj.xp}


def _compute_metric(user, metric_type: str) -> int:
    """
    Tính giá trị metric hiện tại cho user theo từng loại badge.
    """
    if metric_type == BADGE_TYPE_LESSONS:
        # Đếm số lesson đã hoàn thành (distinct lesson_id)
        return (
            LessonSession.objects
            .filter(user=user, status="completed")
            .values("lesson_id")
            .distinct()
            .count()
        )

    if metric_type == BADGE_TYPE_SPEAK:
        # Đếm số SkillSession completed cho skill type = pron/speaking
        speak_types = [Skill.SkillType.PRON, Skill.SkillType.SPEAKING]
        return (
            SkillSession.objects
            .filter(user=user, status="completed", skill__type__in=speak_types)
            .count()
        )

    if metric_type == BADGE_TYPE_FRIENDS:
        # Đếm số bạn bè đã accepted
        return (
            Friend.objects
            .filter(accepted=True)
            .filter(Q(from_user=user) | Q(to_user=user))
            .count()
        )

    if metric_type == BADGE_TYPE_TOTAL_XP:
        # Tổng XP trên tất cả LanguageEnrollment
        agg = (
            LanguageEnrollment.objects
            .filter(user=user)
            .aggregate(total=Sum("total_xp"))
        )
        return int(agg["total"] or 0)

    if metric_type == BADGE_TYPE_STREAK:
        # Lấy streak cao nhất trên các enrollment
        agg = (
            LanguageEnrollment.objects
            .filter(user=user)
            .aggregate(max_streak=Max("streak_days"))
        )
        return int(agg["max_streak"] or 0)

    return 0


@transaction.atomic
def recalc_badges_for_user(user, limit_types=None):
    """
    Re-calc progress cho tất cả Badge (hoặc chỉ các loại trong limit_types)
    rồi cập nhật/award UserBadge tương ứng.
    """
    qs = Badge.objects.filter(is_active=True)
    if limit_types:
        qs = qs.filter(criteria__type__in=list(limit_types))

    badges = list(qs)
    if not badges:
        return []

    updated_ids = []

    for badge in badges:
        crit = badge.criteria or {}
        mtype = crit.get("type")
        if not mtype:
            continue
        if limit_types and mtype not in limit_types:
            continue

        # Giá trị hiện tại (progress thực tế)
        value = _compute_metric(user, mtype)

        # Target của badge
        target = (
            crit.get("lessons")
            or crit.get("count")
            or crit.get("xp")
            or crit.get("days")
            or 0
        )
        target = int(target or 0)

        ub, created = UserBadge.objects.get_or_create(
            user=user,
            badge=badge,
            defaults={"progress": value, "meta": {}},
        )
        old_progress = ub.progress

        if not created and ub.progress != value:
            ub.progress = value
            ub.save(update_fields=["progress"])

        # Check lần đầu vượt mốc target -> đánh dấu completed + gửi Notification
        meta = ub.meta or {}
        completed_before = bool(meta.get("completed"))
        completed_now = bool(target) and value >= target

        if completed_now and not completed_before:
            meta["completed"] = True
            ub.meta = meta
            ub.save(update_fields=["meta"])

            Notification.objects.create(
                user=user,
                type="system",
                title="Huy hiệu mới!",
                body=f"Bạn vừa mở khóa huy hiệu '{badge.name}'.",
                payload={"badge_id": badge.id, "slug": badge.slug},
            )

        updated_ids.append(ub.id)

    return updated_ids


def push_notification(notification):
    from social.serializers import NotificationSerializer
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"user_{notification.user_id}",
        {
            "type": "notify",
            "data": NotificationSerializer(notification).data,
        }
    )