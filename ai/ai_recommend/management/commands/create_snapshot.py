import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from ai_recommend.services.exporter import export_snapshot

class Command(BaseCommand):
    help = 'Tạo snapshot dữ liệu (Parquet) từ Database để train AI'

    def add_arguments(self, parser):
        parser.add_argument(
            '--snapshot_id', 
            type=str, 
            help='Tùy chọn ID cho snapshot (mặc định sẽ dùng timestamp hiện tại)'
        )

    def handle(self, *args, **options):
        # 1. Tạo ID cho snapshot
        snapshot_id = options['snapshot_id']
        if not snapshot_id:
            # ID dạng: snap_1704067200 (timestamp)
            snapshot_id = f"snap_{int(time.time())}"

        self.stdout.write(f"Đang tạo snapshot: {snapshot_id} ...")
        
        try:
            # 2. Gọi service Exporter
            # Hàm này sẽ lấy data từ Mistake (đã fix score) -> tính features -> upload lên MinIO
            result = export_snapshot(snapshot_id)
            
            if result:
                self.stdout.write(self.style.SUCCESS(f"Thành công! Snapshot ID: {snapshot_id}"))
                self.stdout.write(f"Features: {result.get('features_uri')}")
                self.stdout.write(f"Labels:   {result.get('labels_uri')}")
                self.stdout.write("\nBây giờ bạn có thể dùng ID này để train model:")
                self.stdout.write(self.style.WARNING(f"python manage.py train_ai --snapshot_id={snapshot_id}"))
            else:
                self.stdout.write(self.style.WARNING("Không có dữ liệu để export."))
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Lỗi khi tạo snapshot: {e}"))