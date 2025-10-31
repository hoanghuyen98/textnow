from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,  # login
    TokenRefreshView,     # refresh token
)
from . import views

urlpatterns = [
    path('', views.customer_home, name='chat_home'),
    path('refresh_inbox/', views.refresh_inbox, name='refresh_inbox'),
    path('send_message/', views.send_message, name='send_message'),
    path("send_media/", views.send_media_api, name="send_media_api"),
  
    # nhân viên
    path("phone_add/", views.create_phone_account, name="create_phone"),

    # khách hàng
    path("customer_info/", views.customer_info, name="customer_info"),

    # login/logout
    path('login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', views.logout_view, name='logout'),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
