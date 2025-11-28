from celery import shared_task
from django.db import transaction
from django.utils import timezone
import json
from .models import PhoneAccount, Customer, MessageHistoryLog
from .utils import run_curl
from datetime import timedelta
from logzero import logger
import random, string
from django.contrib.auth.models import User
from django.core.cache import cache
import secrets
from django.contrib.auth.hashers import make_password
from .utils import run_curl_with_retry
import logging
from celery import group

task_logger = logging.getLogger("task_error")


@shared_task
def check_single_phone(phone_id):
    phone = PhoneAccount.objects.get(id=phone_id)

    curl_text = phone.batch
    result = run_curl(curl_text)

    now = timezone.now()
    live_expired_time = now - timedelta(days=7)
    msg = ""

    if result["status"] != "success":
        logger.info(result["message"])
        phone.status = "die_use"
        phone.save(update_fields=["status"])

        msg = f"Lỗi: {result['message']}"
        logger.info(f"[{phone.phone}] ❌ {msg}")
    else:
        phone.status = "live"
        phone.save(update_fields=["status"])

        msg = "Kết nối OK (reset 24h)"
        logger.info(f"[{phone.phone}] ✅ {msg}")

        # Redis TTL
        REDIS_TTL = 42 * 60 * 60
        redis_key = f"message_history:{phone.phone}"
        cache.set(redis_key, json.dumps(result), timeout=REDIS_TTL)
        logger.info('đã lưu vào redis')

    if phone.status == "live" and phone.customer is not None:

        customer_created_time = phone.customer.date_use  

        if customer_created_time and customer_created_time < live_expired_time:
            phone.status = "lock"
            phone.save(update_fields=["status"])

            logs.append({
                "phone": phone.phone,
                "status": "lock",
                "message": "🔒 Locked (customer tạo > 72h)"
            })

            logger.info(f"[{phone.phone}] 🔒 Locked: customer tạo > 72h")

    return {
        "phone": phone.phone,
        "status": phone.status,
        "message": msg,
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

@shared_task
def check_phone_all_batches():

    logger.info("-22222222222222222222222222222222222222")
    phone_ids = list(
        PhoneAccount.objects
        .exclude(status__in=["die", "lock", "die_use"])
        .values_list("id", flat=True)
    )

    jobs = group(check_single_phone.s(pid) for pid in phone_ids)
    result = jobs.apply_async()

    return {"task_group_id": result.id, "total": len(phone_ids)}

@shared_task
def check_all_batches():
    logger.info("🔥 Task check_all_batches đang chạy...")
    # ví dụ logic thật của bạn
    return {"result": "OK"}

@shared_task
def check_celery():
    logger.info("🔥 Task check_all_batches đang chạy...")
    # ví dụ logic thật của bạn
    return {"result": "OK"}

@shared_task()
def bulk_reset_password_task(customer_ids):
    customers = Customer.objects.select_related("user").filter(id__in=customer_ids)
    logger.info("task bulk_reset_password_task")
    if not customers.exists():
        return {"status": "error", "message": "No customers found"}

    reset_data = []
    updated_users = []
    updated_customers = []

    with transaction.atomic():
        for cus in customers:
            new_pass = secrets.token_hex(5)

            hashed = make_password(new_pass)
            cus.raw_password = new_pass
            updated_customers.append(cus)

            user = cus.user
            user.password = hashed
            updated_users.append(user)

            reset_data.append({
                "customer_id": cus.id,
                "username": cus.user.username,
                "new_password": new_pass,
            })

        User.objects.bulk_update(updated_users, ["password"])
        Customer.objects.bulk_update(updated_customers, ["raw_password"])

    return {
        "status": "success",
        "data": reset_data
    }

@shared_task
def process_phoneaccount_background(phone_name):
    try:
        logger.info(phone_name)
        phone_obj = PhoneAccount.objects.get(name=phone_name)
        logger.info(phone_obj)
        purchased_mail = phone_obj.purchased_mail

        # --- Check xem số live hay die ---
        is_live = run_curl_with_retry(phone_obj.batch, retries=2)
        logger.info(is_live)
        if is_live:
            phone_obj.status = "live"
            password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

            # --- Tạo User ---
            user = User.objects.create_user(username=phone_obj.name, password=password)

            # --- Tạo Customer ---
            customer = Customer.objects.create(
                user=user,
                raw_password=password,
                phone_assigned_count=1
            )

            phone_obj.customer = customer

        else:
            phone_obj.status = "die"

        # --- Save changes ---
        phone_obj.save(update_fields=["status", "customer"])

        # Mark mail used
        purchased_mail.is_used = True
        purchased_mail.save(update_fields=["is_used"])
        logger.info("đã xong")
        return {"status": "success", "phone": phone_obj.phone}

    except Exception as e:
        import traceback
        logger.error(f"[{self.request.id}] Task FAILED: {e}")
        logger.error(traceback.format_exc())
        raise e
        return {"status": "error", "message": "Có lỗi xảy ra trong quá trình tạo phone, vui lòng tạo lại"}