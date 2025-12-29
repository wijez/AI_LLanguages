from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import XPEvent, DailyXP

def grant_xp(user, amount, source_type, source_id, enrollment=None):
    """
    - user: User nhận thưởng
    - amount: Số XP
    - source_type: Loại nguồn (VD: 'lesson', 'quest', 'daily_login')
    - source_id: ID của nguồn (VD: ID của bài học)
    - enrollment: (Optional) Object LanguageEnrollment để cộng tích lũy
    
    Returns: True nếu cộng thành công, False nếu đã cộng trước đó (trùng lặp).
    """
    if amount <= 0:
        return False

    with transaction.atomic():
        
        # BƯỚC 1: Tạo XPEvent (Chốt chặn chống spam/duplicate)
        # get_or_create sẽ kiểm tra unique constraint (user, source_type, source_id)
        event, created = XPEvent.objects.get_or_create(
            user=user,
            source_type=source_type,
            source_id=str(source_id),
            defaults={
                'amount': amount,
                'created_at': timezone.now()
            }
        )

        # Nếu event đã tồn tại (created = False) => User này đã nhận điểm bài này rồi
        if not created:
            return False

        # BƯỚC 2: Cộng vào DailyXP (Thống kê ngày)
        # Sử dụng F() để tránh Race Condition (khi user làm 2 việc cùng lúc cực nhanh)
        today = timezone.localdate()
        daily_xp, _ = DailyXP.objects.get_or_create(user=user, date=today)
        daily_xp.xp = F('xp') + amount
        daily_xp.save()

        # BƯỚC 3: Cộng trực tiếp vào LanguageEnrollment (Tiến độ học)
        if enrollment:
            enrollment.xp = F('xp') + amount
            enrollment.save()
            
            # (Tuỳ chọn) Logic kiểm tra lên cấp (Level Up) có thể đặt ở đây
            check_level_up(enrollment) 

        return True