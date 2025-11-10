from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import Customer

@receiver(post_delete, sender=Customer)
def delete_user_when_customer_deleted(sender, instance, **kwargs):
    """
    Khi Customer bị xóa -> tự động xóa luôn User tương ứng
    """
    if instance.user:
        instance.user.delete()
