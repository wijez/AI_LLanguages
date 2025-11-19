
from .celery import app as celery_app

# Đảm bảo app được nạp
__all__ = ('celery_app',)