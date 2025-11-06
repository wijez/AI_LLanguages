from django.db import transaction, models
from django.db.models import F
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from progress.models import XPEvent, DailyXP
from social.models import Friend

# Phát sự kiện để FE refetch ngay
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
    source_id: khoá duy nhất đại diện cho lần hoàn thành (nên dùng session_id).
    """
    # 1) Ghi event (bắt lỗi trùng — không cộng lại)
    created = False
    try:
        XPEvent.objects.create(user=user, source_type="lesson", source_id=str(source_id), amount=amount)
        created = True
    except Exception:
        created = False

    if not created:
        return {"ok": True, "awarded": False, "reason": "already_awarded"}

    # 2) Cộng DailyXP theo ngày
    today = timezone.localdate()
    DailyXP.objects.update_or_create(
        user=user, date=today,
        defaults={"xp": F("xp") + amount}
    )

    # 3) Phát WS để FE refetch
    _emit_leaderboard_changed(user.id)
    return {"ok": True, "awarded": True, "amount": amount}


