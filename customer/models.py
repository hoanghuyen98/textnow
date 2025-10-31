from django.db import models
import hashlib
from django.contrib.auth.models import User


class Customer(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="customer_profile"
    )

    company_name = models.CharField(max_length=255, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Đang hoạt động'),
            ('inactive', 'Ngưng hoạt động'),
            ('blacklist', 'Danh sách đen'),
        ],
        default='active'
    )

    def __str__(self):
        return f"{self.user.username} ({self.company_name or 'Cá nhân'})"
        

class Employee(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee_profile"
    )

    department = models.CharField(max_length=100, null=True, blank=True)
    role = models.CharField(
        max_length=50,
        choices=[
            ('admin', 'Quản trị viên'),
            ('staff', 'Nhân viên'),
            ('manager', 'Trưởng nhóm'),
        ],
        default='staff'
    )

    def __str__(self):
        return f"{self.user.username} ({self.role})"

class PhoneAccount(models.Model):
    PROVIDER_CHOICES = [
        ("pinger", "Pinger"),
        ("textnow", "TextNow"),
        ("sideline", "Sideline"),
        ("googlevoice", "Google Voice"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("live", "Live"),
        ("lock", "Locked"),
        ("die", "Dead"),
    ]
    creator = models.ForeignKey(
        'Employee',
        on_delete=models.CASCADE,
        related_name='created_phones',
        null=True,
        blank=True
    )

    customer = models.ForeignKey(
        'Customer',
        on_delete=models.CASCADE,
        related_name='phones',
        null=True,
        blank=True
    )

    name = models.CharField(max_length=20, null=True)
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    mail = models.EmailField(blank=True, null=True)
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES, default="pinger")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="live")

    # --- Lưu nội dung curl ---
    batch = models.TextField(blank=True, null=True)
    message = models.TextField(blank=True, null=True)
    media = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "phone_account"
        ordering = ["phone"]

    def __str__(self):
        return f"{self.phone} ({self.get_provider_display()} - {self.get_status_display()})"

    # Tự động cập nhật hash trước khi lưu
    def save(self, *args, **kwargs):
        def hash_text(text):
            return hashlib.sha256(text.strip().encode("utf-8")).hexdigest() if text else None

        self.batch_hash = hash_text(self.batch)
        self.message_hash = hash_text(self.message)
        self.media_hash = hash_text(self.media)
        super().save(*args, **kwargs)
