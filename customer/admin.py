from django.contrib import admin
from .models import PhoneAccount, Employee, Customer, MailProvider, MailTransaction, PurchasedMail, EmployeeGroup, TextNowAccount, AppleMailProxy


admin.site.register(Employee)
admin.site.register(Customer)
admin.site.register(PhoneAccount)
admin.site.register(MailProvider)
admin.site.register(MailTransaction)
admin.site.register(PurchasedMail)
admin.site.register(EmployeeGroup)
admin.site.register(TextNowAccount)
admin.site.register(AppleMailProxy)
