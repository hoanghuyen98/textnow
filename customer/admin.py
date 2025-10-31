from django.contrib import admin
from .models import PhoneAccount, Employee, Customer


admin.site.register(Employee)
admin.site.register(Customer)
admin.site.register(PhoneAccount)