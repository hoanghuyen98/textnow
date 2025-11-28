from django.db import models
import hashlib
from django.contrib.auth.models import User
import uuid

def gen_uuid():
    return str(uuid.uuid4())

class EmployeeGroup(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return self.name


class Employee(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="employee_profile"
    )
    role = models.CharField(
        max_length=50,
        choices=[
            ('admin', 'Quản trị viên'),
            ('staff', 'Nhân viên'),
        ],
        default='staff'
    )
    group = models.ForeignKey(
        EmployeeGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="employees"
    )

    raw_password = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


    def delete(self, *args, **kwargs):
        if self.user:
            self.user.delete()
        super().delete(*args, **kwargs)


class CustomerAssignHistory(models.Model):
    phone_count = models.PositiveIntegerField()
    created_list = models.JSONField()   # Lưu list JSON
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    reset_count = models.PositiveIntegerField(default=0)
    # Ai thực hiện cấp (admin/staff)
    creator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assign_histories"
    )

    class Meta:
        db_table = "customer_assign_history"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Lần cấp {self.phone_count} số - {self.created_at}"


class MessageHistoryLog(models.Model):
    message_id = models.CharField(default=gen_uuid, editable=False, null=True, blank=True, max_length=255)
    # ⬇ mỗi log gắn với 1 customer (1 khách → nhiều log)
    phone = models.ForeignKey(
        "PhoneAccount",
        on_delete=models.CASCADE,
        related_name="phone_logs",
        null=True,
        blank=True
    )

    data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.phone} - {self.last_text}"


class Customer(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="customer_profile"
    )
    raw_password = models.TextField(blank=True, null=True)
    phone_assigned_count = models.PositiveIntegerField(default=0)
    date_use = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username}"

    def delete(self, *args, **kwargs):
        """
        Khi xóa Customer:
        - Gỡ liên kết khỏi các PhoneAccount
        - Đặt lại is_used=False để có thể tái sử dụng
        - Xóa luôn User tương ứng
        """
        # ✅ Gỡ liên kết các phone trước khi xóa Customer
        for phone in self.phones.all():
            phone.customer = None
            phone.save(update_fields=['customer'])

        # ✅ Xóa user
        if self.user:
            self.user.delete()

        # ✅ Xóa customer (không xóa phone)
        super().delete(*args, **kwargs)


class PhoneAccount(models.Model):

    STATUS_CHOICES = [
        ("live", "Live"),
        ("die_use", "Dead (When In Use)"),
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
        on_delete=models.SET_NULL,
        related_name='phones',
        null=True,
        blank=True
    )

    purchased_mail = models.ForeignKey(
        'PurchasedMail',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='used_by_phones'
    )

    name = models.CharField(max_length=20, null=True)
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    mail = models.EmailField(blank=True, null=True)
    provider = models.CharField(max_length=30, default="Pinger/Textfree")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="live")
    is_used = models.BooleanField(default=False)
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
        return f"{self.phone}"


class MailProvider(models.Model):
    name = models.CharField(max_length=100, unique=True,  null=True, blank=True)
    base_url = models.URLField()
    api_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)

    def __str__(self): return self.name


class MailTransaction(models.Model):
    provider = models.ForeignKey(MailProvider, on_delete=models.PROTECT,  null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True)
    product_id = models.CharField(max_length=50, null=True, blank=True)
    product_name = models.CharField(max_length=255, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    trans_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, default="success")
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self): return f"{self.provider} - {self.product_name} ({self.quantity})"


class PurchasedMail(models.Model):
    purchase = models.ForeignKey(
        MailTransaction, on_delete=models.CASCADE, related_name="mails", blank=True, null=True
    )
    email = models.EmailField(blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    refresh_token = models.TextField(blank=True, null=True)
    client_id = models.CharField(max_length=100, blank=True, null=True)
    provider = models.CharField(max_length=50, blank=True, null=True)
    is_used = models.BooleanField(default=False)
    is_delete = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("purchase", "email")
        db_table = "purchased_mail"

    def __str__(self):
        return f"{self.email} ({self.provider or 'unknown'})"


class AppleMailProxy(models.Model):
    employee = models.ForeignKey(
        "Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="apple_mail_entries"
    )
    mail = models.EmailField(unique=True)
    proxy_ip = models.CharField(max_length=50, blank=True, null=True)
    note = models.CharField(max_length=255, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = "apple_mail_proxy"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.mail} ({self.proxy_ip})"

class TextNowAccount(models.Model):
    employee = models.ForeignKey(
        "Employee", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="textnow_accounts"
    )
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "textnow_account"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email}"
