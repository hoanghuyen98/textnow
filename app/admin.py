from django.contrib import admin
from .models import PhoneAccount, Employee, Customer, MailProvider, MailTransaction, PurchasedMail, EmployeeGroup, TextNowAccount, AppleMailProxy, CustomerAssignHistory



@admin.register(PhoneAccount)
class PhoneAccountAdmin(admin.ModelAdmin):

    # Các cột hiển thị trong danh sách
    list_display = (
        "phone",
        "name",
        "creator_name",
        "customer_name",
        "status",
        "is_used",
        "provider",
        "created_at",     # 🔥 sẽ hiển thị
        "updated_at",     # 🔥 thêm để hiển thị
    )

    # Không cho sửa 2 field này trong trang edit
    readonly_fields = ("created_at", "updated_at")   # 🔥 bắt buộc phải có

    # Bộ lọc bên phải
    list_filter = ("status", "is_used", "creator", "customer")

    # Tìm kiếm
    search_fields = (
        "phone",
        "name",
        "mail",
        "creator__user__username",
        "customer__user__username"
    )

    # Sắp xếp mặc định
    ordering = ("-created_at",)

    # Hiển thị tên creator
    def creator_name(self, obj):
        return obj.creator.user.username if obj.creator and obj.creator.user else "-"
    creator_name.short_description = "Nhân viên tạo"

    # Hiển thị tên customer
    def customer_name(self, obj):
        return obj.customer.user.username if obj.customer and obj.customer.user else "-"
    customer_name.short_description = "Khách hàng dùng"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "phone_assigned_count",
        "created_at",
        "updated_at",
    )

    fields = (
        "user",
        "raw_password",
        "phone_assigned_count",
        "created_at",
        "updated_at",
    )

    readonly_fields = ("created_at", "updated_at")

admin.site.register(Employee)

admin.site.register(MailProvider)
admin.site.register(MailTransaction)
admin.site.register(PurchasedMail)
admin.site.register(EmployeeGroup)
admin.site.register(TextNowAccount)
admin.site.register(AppleMailProxy)
admin.site.register(CustomerAssignHistory)
