from celery import shared_task
from django.utils import timezone
from django.db import models
from django.db.models import Sum
from .models import LeaderboardEntry
from learning.models import LessonSession  


@shared_task(name="social.update_daily_leaderboard")
def update_daily_leaderboard():
    """
    Tính toán tổng XP kiếm được TRONG NGÀY HÔM NAY cho mỗi user/ngôn ngữ
    và cập nhật vào bảng LeaderboardEntry.
    """
    today = timezone.now().date()

    # 1. Lấy tất cả session ĐÃ HOÀN THÀNH trong hôm nay
    sessions_today = (
        LessonSession.objects
        .filter(status='completed', completed_at__date=today)
        # [SỬA 1] Sửa đường dẫn join
        .select_related('user', 'lesson__topic__language') 
    )

    # 2. Nhóm theo user VÀ ngôn ngữ, sau đó tính tổng XP kiếm được
    xp_today_by_user_lang = (
        sessions_today
        .values(
            'user', 
            'lesson__topic__language'  # [SỬA 2] Sửa trường để group by
        ) 
        .annotate(daily_xp=Sum('xp_earned')) # Tính tổng XP kiếm được
        .filter(daily_xp__gt=0) # Chỉ lấy ai có XP
    )

    entries_updated = 0
    entries_created = 0

    # 3. Cập nhật hoặc Tạo mới (Update or Create) bản ghi cho ngày hôm nay
    for item in xp_today_by_user_lang:
        user_id = item['user']
        # [SỬA 3] Sửa tên key để lấy ID ngôn ngữ
        language_id = item['lesson__topic__language'] 
        total_xp_today = item['daily_xp']

        if not user_id or not language_id:
            continue

        # Dùng UniqueConstraint(fields=['user','language','date'])
        _, created = LeaderboardEntry.objects.update_or_create(
            user_id=user_id,
            language_id=language_id,
            date=today,
            defaults={
                'xp': total_xp_today,
                'rank': 0 # Rank sẽ được tính bởi View khi đọc
            }
        )
        if created:
            entries_created += 1
        else:
            entries_updated += 1
            
    return f"Leaderboard for {today}: Updated {entries_updated}, Created {entries_created}."