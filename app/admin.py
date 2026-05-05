from django.contrib import admin
from django.contrib.admin import DateFieldListFilter
from import_export.admin import ExportMixin

from .models import (
    PhoneAccount,
    Employee,
    Customer,
    MailProvider,
    MailTransaction,
    PurchasedMail,
    EmployeeGroup,
    TextNowAccount,
    AppleMailProxy,
    CustomerAssignHistory,
    ProxySetting,
)


# ==============================
# BASE ADMIN: EXPORT FOR ALL
# ==============================
class BaseExportAdmin(ExportMixin, admin.ModelAdmin):
    """
    Base admin cho toàn hệ thống
    - Có Export (csv / xlsx / json)
    - Ăn theo filter + search
    - Chỉ superuser được export
    """

    def has_export_permission(self, request):
        return request.user.is_superuser


# ==============================
# PHONE ACCOUNT
# ==============================
@admin.register(PhoneAccount)
class PhoneAccountAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "phone",
        "name",
        "batch",
        "creator_name",
        "customer_name",
        "mail",
        "provider",
        "status",
        "is_used",
        "purchased_mail",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        "status",
        "is_used",
        "creator",
        "provider",
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = (
        "phone",
        "name",
        "mail",
        "batch",
        "creator__user__username",
        "customer__user__username",
    )

    ordering = ("-created_at",)

    def creator_name(self, obj):
        return obj.creator.user.username if obj.creator else "-"
    creator_name.short_description = "Nhân viên tạo"

    def customer_name(self, obj):
        return obj.customer.user.username if obj.customer else "-"
    customer_name.short_description = "Khách hàng dùng"


# ==============================
# CUSTOMER
# ==============================
@admin.register(Customer)
class CustomerAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "user",
        "raw_password",
        "phone_assigned_count",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("user__username",)

    ordering = ("-created_at",)


# ==============================
# EMPLOYEE
# ==============================
@admin.register(Employee)
class EmployeeAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "user",
        "role",
        "group",
        "raw_password",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        "role",
        "group",
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("user__username", "role")

    ordering = ("-created_at",)


# ==============================
# MAIL PROVIDER
# ==============================
@admin.register(MailProvider)
class MailProviderAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "name",
        "base_url",
        "api_key",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("name", "base_url")

    ordering = ("-created_at",)


# ==============================
# MAIL TRANSACTION
# ==============================
@admin.register(MailTransaction)
class MailTransactionAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "provider",
        "employee",
        "product_id",
        "product_name",
        "quantity",
        "total_price",
        "trans_id",
        "status",
        "created_at",
    )

    readonly_fields = ("created_at",)

    list_filter = (
        "provider",
        "employee",
        "status",
        ("created_at", DateFieldListFilter),
    )

    search_fields = ("product_name", "trans_id")

    ordering = ("-created_at",)


# ==============================
# PURCHASED MAIL
# ==============================
@admin.register(PurchasedMail)
class PurchasedMailAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "purchase",
        "email",
        "password",
        "provider",
        "is_used",
        "is_delete",
        "created_at",
    )

    readonly_fields = ("created_at",)

    list_filter = (
        "provider",
        "is_used",
        "is_delete",
        ("created_at", DateFieldListFilter),
    )

    search_fields = ("email", "provider")

    ordering = ("-created_at",)


# ==============================
# EMPLOYEE GROUP
# ==============================
@admin.register(EmployeeGroup)
class EmployeeGroupAdmin(BaseExportAdmin):

    list_display = ("id", "name", "created_at", "updated_at")

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("name",)

    ordering = ("-created_at",)


# ==============================
# TEXTNOW ACCOUNT
# ==============================
@admin.register(TextNowAccount)
class TextNowAccountAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "employee",
        "email",
        "password",
        "is_active",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        "employee",
        "is_active",
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("email",)

    ordering = ("-created_at",)


# ==============================
# APPLE MAIL PROXY
# ==============================
@admin.register(AppleMailProxy)
class AppleMailProxyAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "employee",
        "mail",
        "proxy_ip",
        "note",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        "employee",
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("mail", "proxy_ip")

    ordering = ("-created_at",)


# ==============================
# CUSTOMER ASSIGN HISTORY
# ==============================
@admin.register(CustomerAssignHistory)
class CustomerAssignHistoryAdmin(BaseExportAdmin):

    list_display = (
        "id",
        "phone_count",
        "creator",
        "reset_count",
        "is_revoke",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        "is_revoke",
        ("created_at", DateFieldListFilter),
    )

    search_fields = ("creator__username",)

    ordering = ("-created_at",)


# ==============================
# PROXY SETTING
# ==============================
@admin.register(ProxySetting)
class ProxySettingAdmin(admin.ModelAdmin):
    list_display = ("id", "proxy_us", "updated_at")
    readonly_fields = ("updated_at",)
