from django.core.management.base import BaseCommand
from django.utils import timezone
from app.models import PhoneAccount
from logzero import logger

class Command(BaseCommand):
    help = "Đặt toàn bộ phone về trạng thái chưa sử dụng (is_used=False)"

    def handle(self, *args, **kwargs):
        now = timezone.now()

        updated = PhoneAccount.objects.update(
            is_used=False,
            status='live',
            updated_at=now
        )

        logger.info(f"Đã cập nhật {updated} phone → is_used=False")
        self.stdout.write(self.style.SUCCESS(f"Đã reset {updated} phone."))
