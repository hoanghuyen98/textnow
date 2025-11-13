from django.contrib import admin
from .models import PhoneAccount, Employee, Customer, MailProvider, MailTransaction, PurchasedMail, EmployeeGroup, TextNowAccount, AppleMailProxy



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
        "created_at",
    )

    # Bộ lọc bên phải
    list_filter = ("status", "is_used", "creator", "customer")

    # Cho phép tìm kiếm nhanh
    search_fields = ("phone", "name", "mail", "creator__user__username", "customer__user__username")

    # Sắp xếp mặc định
    ordering = ("-created_at",)

    # Hiển thị tên thay cho object
    def creator_name(self, obj):
        return obj.creator.user.username if obj.creator and obj.creator.user else "-"
    creator_name.short_description = "Nhân viên tạo"

    def customer_name(self, obj):
        return obj.customer.user.username if obj.customer and obj.customer.user else "-"
    customer_name.short_description = "Khách hàng dùng"

admin.site.register(Employee)
admin.site.register(Customer)
admin.site.register(MailProvider)
admin.site.register(MailTransaction)
admin.site.register(PurchasedMail)
admin.site.register(EmployeeGroup)
admin.site.register(TextNowAccount)
admin.site.register(AppleMailProxy)
