from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sideline.settings')

app = Celery('staging-sideline')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')



app.conf.beat_schedule = {
    "check-phone-batches-every-10-min": {
        "task": "app.tasks.check_phone_all_batches",   # Đường dẫn đến task
        "schedule": 1800,  # 600 giây = 10 phút
    },
}
