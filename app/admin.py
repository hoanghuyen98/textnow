from django.contrib import admin
from django.contrib.admin import DateFieldListFilter
from .models import (
    PhoneAccount, Employee, Customer, MailProvider, MailTransaction,
    PurchasedMail, EmployeeGroup, TextNowAccount, AppleMailProxy,
    CustomerAssignHistory
)

@admin.register(PhoneAccount)
class PhoneAccountAdmin(admin.ModelAdmin):

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


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
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


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
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


@admin.register(MailProvider)
class MailProviderAdmin(admin.ModelAdmin):
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


@admin.register(MailTransaction)
class MailTransactionAdmin(admin.ModelAdmin):
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


@admin.register(PurchasedMail)
class PurchasedMailAdmin(admin.ModelAdmin):
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


@admin.register(EmployeeGroup)
class EmployeeGroupAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at", "updated_at")

    readonly_fields = ("created_at", "updated_at")

    list_filter = (
        ("created_at", DateFieldListFilter),
        ("updated_at", DateFieldListFilter),
    )

    search_fields = ("name",)

    ordering = ("-created_at",)


@admin.register(TextNowAccount)
class TextNowAccountAdmin(admin.ModelAdmin):
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


@admin.register(AppleMailProxy)
class AppleMailProxyAdmin(admin.ModelAdmin):
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


@admin.register(CustomerAssignHistory)
class CustomerAssignHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "phone_count",
        "creator",
        "reset_count",
        "is_revoke",
        "created_at",
        "updated_at"
    )

    readonly_fields = ("created_at", "updated_at", )

    list_filter = (
        "is_revoke",
        ("created_at", DateFieldListFilter),
    )

    search_fields = ("creator__username",)

    ordering = ("-created_at",)

