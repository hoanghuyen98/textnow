from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,  # login
    TokenRefreshView,     # refresh token

)
from . import views

router = DefaultRouter()

router.register(r'employee_group', views.EmployeeGroupViewSet, basename='employee_group')
router.register(r'employees', views.EmployeeViewSet, basename='employee')
router.register(r"customers", views.CustomerViewSet, basename="customer")
router.register(r"purchased-mails", views.PurchasedMailViewSet, basename="purchased-mail")
router.register(r"applemail", views.AppleMailProxyViewSet, basename="applemail")

urlpatterns = [
    path("test-throttle/", views.TestThrottleView.as_view()),
    path("check_status/", views.CheckStatusView.as_view(), name="check_status"),
    # Message
    path('', views.customer_home, name='chat_home'),
    path('refresh_inbox/', views.RefreshInboxView.as_view(), name='refresh_inbox'),
    path('send_message/', views.SendMessageView.as_view(), name='send_message'),
    path("send_media/", views.SendMediaView.as_view(), name="send_media_api"),
  
    # nhân viên
    path("phone_add/",  views.CreatePhoneAccountView.as_view(), name="create_phone"),
    path("employee_phone_summary/", views.EmployeePhoneSummaryView.as_view(), name="employee_phone_summary"),

    # khách hàng
    path('customer_info/',views.CustomerInfoView.as_view(), name='customer_info'),
    path('auto_create_customers/',views.AutoCreateCustomerView.as_view(), name='auto_create_customers'),
    path('reset_password/', views.BulkResetPasswordView.as_view(), name='reset_password'),
    path("task_status/<str:task_id>/", views.TaskStatusView.as_view()),

    # login/logout
    path("login/", views.CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", views.CustomTokenRefreshView.as_view(), name="token_refresh"),
    path('logout/', views.LogoutView.as_view(), name='logout'),

    # Mail 
    path("mail_categories/", views.MailCategoriesView.as_view(), name="mail_categories"),
    path("delete_all_mails/", views.PurchasedMailBulkDeleteView.as_view(), name="delete_all_mails"),
    
    path("buy_mail/", views.BuyMailView.as_view(), name="buy_mail"),
    path("get_auth_code/", views.GetAuthCodeView.as_view(), name="get_auth_code"),
    path("purchased_mails/", views.ListPurchasedMailsView.as_view(), name="purchased_mails"),
    path("save_apple_mail/", views.SaveAppleMailView.as_view(), name="save_apple_mail"),
    path("save_textnow/", views.SaveTextNowAccountView.as_view(), name="save_textnow"),

    # thống kê
    path("report_by_employee/", views.PhoneReportByEmployeeView.as_view()),
    path("report_by_group/", views.PhoneReportByGroupView.as_view()),
    path("report_by_group_sold/", views.PhoneReportByGroupSoldView.as_view()),
    path("reports_overview/", views.PhoneOverviewView.as_view(), name="phone_overview"),
    path("customer_assign_history/", views.CustomerAssignHistoryLatestView.as_view(), name="customer_assign_history"),

] + router.urls

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
