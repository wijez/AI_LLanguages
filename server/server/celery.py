import os
from celery import Celery

# Đặt biến môi trường mặc định cho Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'server.settings')

app = Celery('server')


app.config_from_object('django.conf:settings', namespace='CELERY')


app.autodiscover_tasks()