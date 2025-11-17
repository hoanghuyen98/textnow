from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import PhoneAccount, Customer
from .utils import run_curl
from datetime import timedelta
from logzero import logger
import random, string
from django.contrib.auth.models import User

@shared_task
def check_phone_all_batches():
    now = timezone.now()
    live_expired_time = now - timedelta(hours=72)

    total = 0
    success = 0
    failed = 0
    locked = 0
    died = 0
    logs = []
    logger.info("-22222222222222222222222222222222222222")
    phone_qs = PhoneAccount.objects.exclude(
        status__in=["die", "lock"]
    )

    logger.info(f"🔍 Bắt đầu kiểm tra {phone_qs.count()} tài khoản khả dụng...")

    for phone in phone_qs:
        total += 1
        curl_text = phone.batch

        # =============================
        # 1) Không có batch → die
        # =============================
        if not curl_text or not curl_text.strip():
            phone.status = "die"
            phone.updated_at = now
            phone.save()

            died += 1

            msg = "❌ Không có batch → Đánh die"
            logs.append({
                "phone": phone.phone,
                "status": "die",
                "message": msg,
                "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            })
            logger.info(f"[{phone.phone}] {msg}")
            continue

        # =============================
        # 2) Có batch → chạy curl
        # =============================
        result = run_curl(curl_text)
        now = timezone.now()

        if "error" in result:
            phone.status = "die_use"
            failed += 1
            msg = f"Lỗi: {result['error']}"
            logger.info(f"[{phone.phone}] ❌ {msg}")

        elif isinstance(result.get("status"), int) and result["status"] >= 400:
            phone.status = "die_use"
            failed += 1
            msg = f"Lỗi HTTP {result['status']}"
            logger.info(f"[{phone.phone}] ⚠️ {msg}")

        else:
            phone.status = "live"
            success += 1
            msg = "Kết nối OK (reset 24h)"
            logger.info(f"[{phone.phone}] ✅ {msg}")

        phone.updated_at = now

        # =============================
        # 3) LIVE > 72h → lock
        # =============================
        if phone.status == "live" and phone.customer is not None:

            customer_created_time = phone.customer.created_at  # <-- dùng created_at của Customer

            if customer_created_time and customer_created_time < live_expired_time:
                phone.status = "lock"
                locked += 1

                logs.append({
                    "phone": phone.phone,
                    "status": "lock",
                    "message": "🔒 Locked (customer tạo > 72h)"
                })

                logger.info(f"[{phone.phone}] 🔒 Locked: customer tạo > 72h")

                phone.save(update_fields=["status"])
                continue

        phone.save()

        # =============================
        # 4) TẠO CUSTOMER NẾU LIVE & CHƯA GÁN USER
        # =============================
        if phone.status == "live" and phone.customer is None:
            try:
                with transaction.atomic():
                    # Format username theo chuẩn bạn đang dùng
                    username = phone.name
                    password = ''.join(random.choices(
                        string.ascii_letters + string.digits, k=12
                    ))

                    # Tạo User
                    user = User.objects.create_user(
                        username=username,
                        password=password
                    )

                    # Tạo Customer
                    customer = Customer.objects.create(
                        user=user,
                        raw_password=password,
                        phone_assigned_count=1
                    )

                    # Update lại phone
                    phone.customer = customer
                    phone.save(update_fields=["customer"])

                    logger.info(f"[{phone.phone}] 👤 Auto-created customer: {username}")

                    logs.append({
                        "phone": phone.phone,
                        "status": "live",
                        "message": f"Tạo customer auto: {username}",
                        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    })

            except Exception as e:
                logger.error(f"[{phone.phone}] ❌ Lỗi tạo customer auto: {e}")


        logs.append({
            "phone": phone.phone,
            "status": phone.status,
            "message": msg,
            "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        })

    summary = {
        "total_checked": total,
        "live": success,
        "die": died,
        "die_use": failed,
        "locked": locked,
        "logs": logs,
    }

    logger.info(
        f"✅ Done checking {total} accounts: "
        f"{success} live, {failed} failed, {locked} locked, {died} die."
    )
    return summary

@shared_task
def check_all_batches():
    logger.info("🔥 Task check_all_batches đang chạy...")
    # ví dụ logic thật của bạn
    return {"result": "OK"}