from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import PhoneAccount
from .utils import run_curl  # hoặc import đúng đường dẫn bạn đang dùng
from django.utils import timezone
from datetime import timedelta

@shared_task
def check_phone_all_batches():
    """
    Kiểm tra toàn bộ batch trong PhoneAccount.
    - Bỏ qua các số die, die_use, lock
    - Nếu status = live quá 24h → chuyển sang lock
    - Nếu run_curl lỗi → status = die_use
    - Nếu thành công → status = live (reset thời gian sống)
    - Cập nhật DB + trả log chi tiết
    """
    now = timezone.now()
    live_expired_time = now - timedelta(hours=24)

    total = 0
    success = 0
    failed = 0
    locked = 0
    logs = []

    # ✅ chỉ lấy các số còn khả dụng (không bị die, die_use, lock)
    phone_qs = PhoneAccount.objects.exclude(status__in=["die", "die_use", "lock"])
    print(f"🔍 Bắt đầu kiểm tra {phone_qs.count()} tài khoản khả dụng...")

    for phone in phone_qs:


        total += 1
        curl_text = phone.batch
        if not curl_text:
            logs.append({
                "phone": phone.phone,
                "status": "skip",
                "message": "⚪ Không có batch để kiểm tra"
            })
            continue

        result = run_curl(curl_text)
        now = timezone.now()

        # Phân loại kết quả curl
        if "error" in result:
            phone.status = "die_use"
            failed += 1
            msg = f"Lỗi: {result['error']}"
            print(f"[{phone.phone}] ❌ {msg}")

        elif isinstance(result.get("status"), int) and result["status"] >= 400:
            phone.status = "die_use"
            failed += 1
            msg = f"Lỗi HTTP {result['status']}"
            print(f"[{phone.phone}] ⚠️ {msg}")

        else:
            phone.status = "live"
            success += 1
            msg = "Kết nối OK (reset 24h)"
            print(f"[{phone.phone}] ✅ {msg}")

        phone.updated_at = now

        # Nếu số đang live và đã “sống” quá 24h kể từ khi tạo → lock lại
        if phone.status == "live" and phone.created_at < live_expired_time:
            phone.status = "lock"
            locked += 1
            logs.append({
                "phone": phone.phone,
                "status": "lock",
                "message": "🔒 Locked (đã sống quá 24h kể từ khi tạo)"
            })
            print(f"[{phone.phone}] 🔒 Locked (đã sống quá 24h kể từ khi tạo)")
            continue
            
        phone.save()

        logs.append({
            "phone": phone.phone,
            "status": phone.status,
            "message": msg,
            "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        })

    summary = {
        "total_checked": total,
        "live": success,
        "die_use": failed,
        "locked": locked,
        "logs": logs,
    }

    print(f"✅ Done checking {total} accounts: {success} live, {failed} failed.")
    print(f"Summary: {summary}")
    return summary

@shared_task
def check_all_batches():
    print("🔥 Task check_all_batches đang chạy...")
    # ví dụ logic thật của bạn
    return {"result": "OK"}