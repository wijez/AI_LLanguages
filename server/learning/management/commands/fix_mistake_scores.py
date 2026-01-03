import time
from django.core.management.base import BaseCommand
from django.db import transaction
from difflib import SequenceMatcher
import unicodedata
import re

from vocabulary.models import Mistake

class Command(BaseCommand):
    help = 'Tính toán lại score và confidence cho toàn bộ dữ liệu Mistake cũ'

    def _normalize(self, text):
        """Chuẩn hóa chuỗi để so sánh (lowercase, bỏ dấu, bỏ ký tự lạ)"""
        if not text:
            return ""
        # Chuyển về lowercase
        text = str(text).lower().strip()
        # Bỏ dấu tiếng Việt (nếu cần so sánh lỏng lẻo)
        # text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
        # Bỏ ký tự đặc biệt, giữ lại chữ và số
        text = re.sub(r'[^\w\s]', '', text)
        return text

    def _calculate_similarity(self, a, b):
        """Tính độ giống nhau từ 0.0 đến 1.0"""
        return SequenceMatcher(None, self._normalize(a), self._normalize(b)).ratio()

    def handle(self, *args, **kwargs):
        self.stdout.write("Bắt đầu cập nhật Score và Confidence cho Mistake...")
        
        # Lấy tất cả Mistake, hoặc lọc những cái score=0/null tuỳ ý
        # Ở đây ta quét tất cả để đảm bảo đồng bộ
        mistakes = Mistake.objects.all().iterator(chunk_size=1000)
        
        count = 0
        updated_count = 0
        
        # Batch update list
        batch = []
        BATCH_SIZE = 500

        start_time = time.time()

        for m in mistakes:
            original_score = m.score
            original_conf = m.confidence

            if not m.user_answer or not str(m.user_answer).strip():
                new_score = 0.0
            else:
                new_score = self._calculate_similarity(m.user_answer, m.expected)

            # 2. Tính toán CONFIDENCE
            new_confidence = 1.0 if (m.user_answer and str(m.user_answer).strip()) else 0.0

            # Gán giá trị mới
            m.score = round(new_score, 4)
            m.confidence = new_confidence
            
            # --- ĐOẠN SỬA LỖI TẠI ĐÂY ---
            # Kiểm tra xem có cần update không. 
            # Nếu giá trị cũ là None thì mặc định là CẦN update.
            score_changed = (original_score is None) or (abs(original_score - m.score) > 0.001)
            conf_changed = (original_conf is None) or (abs(original_conf - m.confidence) > 0.001)

            if score_changed or conf_changed:
                batch.append(m)
                updated_count += 1

            count += 1
            if count % 100 == 0:
                self.stdout.write(f"Processed {count} items...", ending='\r')

            if len(batch) >= BATCH_SIZE:
                Mistake.objects.bulk_update(batch, ['score', 'confidence'])
                batch = []
        if batch:
            Mistake.objects.bulk_update(batch, ['score', 'confidence'])

        duration = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f"\nHoàn tất! Đã xử lý {count} bản ghi."
            f"\nĐã cập nhật {updated_count} bản ghi."
            f"\nThời gian: {duration:.2f}s"
        ))