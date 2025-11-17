from django.core.management.base import BaseCommand
from app.models import PhoneAccount
from app.utils import inject_proxy  # nếu để utils
from django.db import transaction

PROXY_US = "http://myuser:mypass@104.25.34.12:12233"


class Command(BaseCommand):
    help = "Inject proxy vào các CURL batch/message/media của PhoneAccount"

    def handle(self, *args, **kwargs):
        accounts = PhoneAccount.objects.all()
        count = accounts.count()

        self.stdout.write(self.style.NOTICE(f"🔍 Processing {count} PhoneAccount..."))

        with transaction.atomic():
            for acc in accounts:
                updated = False

                if acc.batch:
                    acc.batch = inject_proxy(acc.batch, PROXY_US)
                    updated = True

                if acc.message:
                    acc.message = inject_proxy(acc.message, PROXY_US)
                    updated = True

                if acc.media:
                    acc.media = inject_proxy(acc.media, PROXY_US)
                    updated = True

                if updated:
                    acc.save(update_fields=["batch", "message", "media"])

        self.stdout.write(self.style.SUCCESS("✅ DONE — all proxies injected."))
