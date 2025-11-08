"""
URL configuration for sideline project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.views.static import serve
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


schema_view = get_schema_view(
    openapi.Info(
        title="PhoneChat API",
        default_version='v1',
        description="📱 API quản lý hệ thống Phone Chat, bao gồm Pinger, DongVan, SellMMO, ...",
        contact=openapi.Contact(email="support@your-company.com"),
    ),
    public=True,
    # permission_classes=[IsAuthenticated, ],
    permission_classes=[permissions.AllowAny],
    url="https://divisibly-pelagic-roosevelt.ngrok-free.dev"
)

urlpatterns = [
    path('admin/', admin.site.urls),          
    path('api/v1/', include('customer.urls')),
    path('auth/', include('django.contrib.auth.urls')),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    # re_path(r'^(?P<path>.*)$', serve),         # ⚠️ dòng catch-all phải để CUỐI CÙNG

]