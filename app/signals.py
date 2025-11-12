from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import Customer

@receiver(post_delete, sender=Customer)
def delete_user_when_customer_deleted(sender, instance, **kwargs):
    try:
        user = getattr(instance, "user", None)
        if user and getattr(user, "id", None):
            user.delete()
    except Exception as e:
        # Không để lỗi này làm fail API
        print(f"[Signal Warning] Không thể xóa user liên quan: {e}")