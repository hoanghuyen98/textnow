# chat/views.py
import random
import string
import calendar
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
import requests, json, time, logging
from rest_framework import status, viewsets, permissions, serializers
from django.contrib.auth import authenticate, login, logout
from rest_framework.decorators import action
from .serializers import PhoneAccountSerializer, CustomerSerializer, PurchasedMailSerializer, EmployeeGroupSerializer, EmployeeSerializer, GetAuthCodeSerializer, PurchasedMailSerializer,CreatePhoneAccountSerializer, MailCategoriesViewSerializer, CustomerAutoCreateSerializer, AppleMailProxySerializer, CustomerAssignHistorySerializer
from rest_framework.response import Response
from django.db.models import Count, Q, OuterRef, Subquery, Min
from rest_framework.decorators import api_view, permission_classes
import base64
from .models import PhoneAccount, PurchasedMail, AppleMailProxy, TextNowAccount, Employee, EmployeeGroup, Customer, MailTransaction, AppleMailProxy, CustomerAssignHistory, MessageHistoryLog
from rest_framework.permissions import IsAuthenticated, AllowAny
from .utils import run_curl, parse_curl, strip_proxy, send_pinger_message, normalize_phone_number, parse_time, to_utc_isoformat, run_curl_with_retry, upload_pinger_media
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth.models import User
import re
from rest_framework.pagination import PageNumberPagination
from .permissions import RoleRequiredPermission
from rest_framework.views import APIView
from django.db import IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from .service import fetch_categories, buy_mail_dongvan, buy_mail_sellmmo, get_auth_code
from functools import wraps
from drf_yasg.utils import swagger_auto_schema
from django.db import transaction
from datetime import datetime, date
from .tasks import check_phone_all_batches, bulk_reset_password_task, check_celery, process_phoneaccount_background
from rest_framework.throttling import ScopedRateThrottle
from drf_yasg import openapi
from .response_messages import PHONE_MESSAGES, INBOX_MESSAGES, SEND_MESSAGE_MESSAGES, SEND_MEDIA_MESSAGES
import subprocess
from collections import OrderedDict
from logzero import logger
from .exceptions import BadRequest, Unauthorized, NotFound
import secrets
from concurrent.futures import ThreadPoolExecutor
from celery.result import AsyncResult
from django.core.cache import cache

# from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger(__name__)

def customer_home(request):
    return render(request, "customer.html")

class TestThrottleView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def get(self, request):
        return Response({"message": "OK"})


class CheckStatusView(APIView):
    """
    POST: Tạo task kiểm tra toàn bộ batch
    GET: Kiểm tra trạng thái task (qua task_id)
    """

    def post(self, request):
        task = check_phone_all_batches.delay()
        return Response({
            "task_id": task.id,
            "status": "queued"
        }, status=status.HTTP_202_ACCEPTED)


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        if hasattr(user, "employee_profile"):
            token["role"] = user.employee_profile.role
        elif hasattr(user, "customer_profile"):
            token["role"] = "customer"
        else:
            token["role"] = "guest"
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        if hasattr(user, "employee_profile"):
            role = user.employee_profile.role
        elif hasattr(user, "customer_profile"):
            role = "customer"
        else:
            role = "guest"
        data["role"] = role
        data["username"] = user.username
        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        # Bọc super().validate để chặn lỗi người dùng không tồn tại / token lỗi
        try:
            data = super().validate(attrs)
        except Exception:
            # refresh token không hợp lệ
            raise Unauthorized("Refresh token không hợp lệ hoặc đã hết hạn.")

        # Parse access mới để gắn role/username
        access = AccessToken(data["access"])
        user_id = access.get("user_id")
        user = User.objects.filter(id=user_id).first()
        if not user:
            # Giờ trả về string thuần, không bị list
            raise NotFound("Tài khoản không tồn tại hoặc đã bị xoá.")

        if hasattr(user, "employee_profile"):
            role = user.employee_profile.role
        elif hasattr(user, "customer_profile"):
            role = "customer"
        else:
            role = "guest"

        data["role"] = role
        data["username"] = user.username
        return data


class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = CustomTokenRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "token_refresh"


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "logout"
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"success": "Logout successful"}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"error: {str(e)}")
            return Response({"error": "logout fail"}, status=status.HTTP_400_BAD_REQUEST)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 1000  # tùy bạn
    
    def get_paginated_response(self, data):
        return Response({
            "count": self.page.paginator.count,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": {
                "status": "success",
                "message": "Lấy danh sách khách hàng thành công.",
                "data": data
            }
        })


class AppleMailProxyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API CRUD cho AppleMailProxy
    - GET /api/applemail/ : lấy danh sách proxy mail
    - POST /api/applemail/ : thêm mới
    - GET /api/applemail/{id}/ : xem chi tiết
    - PUT/PATCH /api/applemail/{id}/ : cập nhật
    - DELETE /api/applemail/{id}/ : xóa
    """
    queryset = AppleMailProxy.objects.all().select_related("employee").order_by("-created_at")
    serializer_class = AppleMailProxySerializer
    allowed_roles = ["admin", "staff"]
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "medium"

    def list(self, request, *args, **kwargs):
        user = request.user
        employee = getattr(user, "employee_profile", None)
        # Nếu nhân viên thuộc role staff → chỉ trả bản ghi của chính họ
        if employee:
            if employee.role == "staff":
                record = AppleMailProxy.objects.filter(employee=employee).order_by("-created_at").first()

                if not record:
                    return Response(
                        {
                            "status": "error",
                            "message": "Nhân viên chưa có bản ghi AppleMailProxy nào",
                            "data": None,
                        },
                        status=status.HTTP_200_OK
                    )

                serializer = self.get_serializer(record)
                return Response(
                    {
                        "status": "success",
                        "message": "Lấy bản ghi AppleMailProxy thành công.",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK
                )

            # Nếu admin → lấy bản ghi mới nhất toàn hệ thống
            latest_record = self.get_queryset().first()
            if not latest_record:
                return Response(
                    {
                        "status": "error",
                        "message": "Không có bản ghi nào trong AppleMailProxy.",
                        "data": None,
                    },
                    status=status.HTTP_200_OK
                )

            serializer = self.get_serializer(latest_record)
            return Response(
                {
                    "status": "success",
                    "message": "Lấy bản ghi AppleMailProxy mới nhất thành công.",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK
            )
        return Response(
            {
                "status": "error",
                "message": "User không tồn tại.",
                "data": None,
            },
            status=status.HTTP_200_OK
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user
        employee = getattr(user, "employee_profile", None)

        if employee and employee.role == "staff":
            if instance.employee != employee:
                return Response(
                    {
                        "status": "error",
                        "message": "Bạn không có quyền xem bản ghi này.",
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        serializer = self.get_serializer(instance)
        return Response(
            {
                "status": "success",
                "message": "Lấy chi tiết AppleMailProxy thành công.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK
        )


class EmployeeGroupViewSet(viewsets.ModelViewSet):
    queryset = EmployeeGroup.objects.all()
    serializer_class = EmployeeGroupSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "staff"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "medium"

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response({
                "status": "success",
                "message": "Lấy thông tin nhóm nhân viên thành công.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        except EmployeeGroup.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy nhóm nhân viên."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Lỗi khi lấy thông tin nhóm: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin nhóm"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                group = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Tạo nhóm nhân viên thành công.",
                    "data": serializer.data
                }, status=status.HTTP_201_CREATED)
        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            logger.info(f'message: {message}')
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Lỗi khi tạo nhóm: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi tạo nhóm"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                partial = kwargs.pop('partial', False)
                instance = self.get_object()
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                serializer.is_valid(raise_exception=True)
                group = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Cập nhật nhóm nhân viên thành công.",
                    "data": serializer.data
                }, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật nhóm: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật nhóm"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            name = instance.name
            instance.delete()
            return Response({
                "status": "success",
                "message": f"Đã xóa nhóm nhân viên '{name}' thành công."
            }, status=status.HTTP_200_OK)
        except EmployeeGroup.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy nhóm nhân viên để xóa."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Lỗi khi xóa nhóm nhân viên: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi xóa nhóm nhân viên"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related('user', 'group').filter(role="staff")
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    pagination_class = StandardResultsSetPagination
    allowed_roles = ["admin", "staff"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset().order_by('user__username'))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)

            return Response({
                "count": self.paginator.page.paginator.count,
                "next": self.paginator.get_next_link(),
                "previous": self.paginator.get_previous_link(),
                "results": {
                    "status": "success",
                    "message": "Lấy danh sách nhân viên thành công.",
                    "data": serializer.data
                }
            })

        # không phân trang
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "status": "success",
            "message": "Lấy danh sách nhân viên thành công.",
            "data": serializer.data
        })

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():  # đảm bảo rollback nếu lỗi
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                employee = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Tạo nhân viên thành công.",
                    "data": {
                        "id": employee.id,
                        "username": employee.user.username,
                        "group": employee.group.name if employee.group else None,
                        "role": employee.role,
                    }
                }, status=status.HTTP_201_CREATED)

        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            logger.info(f'message: {message}')
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Lỗi không xác định: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi không xác định"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response({
                "status": "success",
                "message": "Lấy thông tin nhân viên thành công.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        except Employee.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy nhân viên."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Lỗi khi lấy thông tin: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                partial = kwargs.pop('partial', False)
                instance = self.get_object()
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                serializer.is_valid(raise_exception=True)
                employee = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Cập nhật thông tin nhân viên thành công.",
                    "data": self.get_serializer(employee).data
                }, status=status.HTTP_200_OK)
        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()

            # Giữ lại thông tin trước khi xoá để phản hồi cho đẹp
            username = instance.user.username if instance.user else None
            group_name = instance.group.name if instance.group else None

            instance.delete()

            return Response({
                "status": "success",
                "message": f"Đã xoá nhân viên '{username}' khỏi nhóm '{group_name}' thành công."
                if group_name else f"Đã xoá nhân viên '{username}' thành công."
            }, status=status.HTTP_200_OK)

        except Employee.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy nhân viên cần xoá."
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Lỗi khi xoá nhân viên: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi xoá nhân viên"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AutoCreateCustomerView(APIView):
    """
    POST: Truyền vào phone_count → Tự động tạo tài khoản Customer
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def post(self, request):
        serializer = CustomerAutoCreateSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            result = serializer.save()  # result đã là dict gồm status, message, data

            # Tự chọn mã HTTP theo status trả về
            http_status = status.HTTP_200_OK
            if result["status"] == "error":
                http_status = status.HTTP_400_BAD_REQUEST
            elif result["status"] == "warning":
                http_status = status.HTTP_206_PARTIAL_CONTENT  # 206: partial success

            return Response(result, status=http_status)

        return Response({
            "status": "error",
            "message": "Dữ liệu không hợp lệ.",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class CustomerAssignHistoryLatestView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def get(self, request):
        latest_obj = (
            CustomerAssignHistory.objects
            .select_related("creator")
            .order_by("-created_at")
            .first()
        )

        if not latest_obj:
            return Response({
                "status": "error",
                "message": "Không có lịch sử cấp số."
            }, status=404)

        serializer = CustomerAssignHistorySerializer(latest_obj)

        return Response({
            "status": "success",
            "message": "Lấy bản ghi lịch sử mới nhất thành công.",
            "data": serializer.data
        })


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.select_related("user").all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    pagination_class = StandardResultsSetPagination
    allowed_roles = ["admin", "staff"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def list(self, request, *args, **kwargs):

        oldest_phone = PhoneAccount.objects.filter(
            customer=OuterRef("pk")
        ).order_by("created_at")

        queryset = self.get_queryset().annotate(
            oldest_phone_created_at=Subquery(
                oldest_phone.values("created_at")[:1]
            )
        ).order_by("oldest_phone_created_at")

        queryset = self.filter_queryset(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "status": "success",
            "message": "Lấy danh sách khách hàng thành công.",
            "data": serializer.data
        })

    def retrieve(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response({
                "status": "success",
                "message": "Lấy thông tin khách hàng thành công.",
                "data": serializer.data
            }, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy khách hàng."
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Lỗi khi lấy thông tin khách hàng: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin khách hàng"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                customer = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Tạo khách hàng thành công.",
                    "data": serializer.data
                }, status=status.HTTP_201_CREATED)

        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Lỗi khi tạo khách hàng: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi tạo khách hàng"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                partial = kwargs.pop('partial', False)
                instance = self.get_object()
                serializer = self.get_serializer(instance, data=request.data, partial=partial)
                serializer.is_valid(raise_exception=True)
                customer = serializer.save()

                return Response({
                    "status": "success",
                    "message": "Cập nhật thông tin khách hàng thành công.",
                    "data": serializer.data
                }, status=status.HTTP_200_OK)

        except serializers.ValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                message = "; ".join(
                    [f"{k}: {', '.join(v)}" if isinstance(v, list) else f"{k}: {v}" for k, v in detail.items()]
                )
            else:
                message = str(detail)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Lỗi khi cập nhật khách hàng: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật khách hàng"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    def destroy(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            username = instance.user.username if instance.user else instance.name
            instance.delete()
            return Response({
                "status": "success",
                "message": f"Đã xóa khách hàng '{username}' thành công."
            }, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Không tìm thấy khách hàng để xóa."
            }, status=status.HTTP_404_NOT_FOUND)
        # except Exception as e:
            logger.error(f"Lỗi khi xóa khách hàng: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi xóa khách hàng"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CustomerInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "customer"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def get(self, request):
        user = request.user
        customer = user.customer_profile
        serializer = CustomerSerializer(customer)

        phones = PhoneAccount.objects.filter(customer=customer)
        stats = {
            "total_phones": phones.count(),
            "live": phones.filter(status="live").count(),
            "die": phones.filter(status=["die", "die_use", "lock"]).count(),
        }

        return Response({
            "status": "success",
            "customer": serializer.data,
            "stats": stats
        }, status=status.HTTP_200_OK)


class CreatePhoneAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "medium"

    @swagger_auto_schema(
        request_body=CreatePhoneAccountSerializer,
        responses={201: "Phone created successfully", 400: "Validation failed"}
    )
    def post(self, request):
        try:
            data = request.data.copy()
            data["creator"] = request.user.id

            employee = request.user.employee_profile
            email = data.get("mail") or data.get("email")

            if not email:
                return Response(
                    {"status": "error", "message": "Thiếu email để gán cho PhoneAccount."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Kiểm tra mail purchased ---
            purchased_mail = PurchasedMail.objects.filter(
                email=email, purchase__employee=employee
            ).first()

            if not purchased_mail:
                return Response(
                    {
                        "status": "error",
                        "message": f"Email '{email}' chưa được mua hoặc không thuộc về nhân viên này."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            if purchased_mail.is_used:
                return Response(
                    {
                        "status": "error",
                        "message": f"Email '{email}' đã được sử dụng cho tài khoản khác."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Decode base64 field ---
            for field in ["batch", "message", "media"]:
                if field in data and data[field]:
                    try:
                        decoded = base64.b64decode(data[field]).decode("utf-8")
                        data[field] = strip_proxy(decoded)
                    except:
                        data[field] = strip_proxy(data[field])

            # --- Validate serializer ---
            serializer = PhoneAccountSerializer(data=data)
            if not serializer.is_valid():
                return Response(
                    {"status": "fail", "detail": serializer.errors, "message": "Dữ liệu đã tồn tại"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # --- Save phone_obj ---
            phone_obj = serializer.save(
                creator=employee,
                purchased_mail=purchased_mail
            )
            print("phone_obj: ", phone_obj.name)
            task = process_phoneaccount_background.delay(phone_obj.name)

            return Response({
                "status": "success",
                "task_id": task.id
            })

        except Exception as e:
            logger.error(f"Lỗi khi tạo PhoneAccount: {e}")
            return Response(
                {"status": "error", "message": "Lỗi hệ thống khi tạo PhoneAccount."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class RefreshInboxView(APIView):
    """
    ✅ API: Lấy danh sách tin nhắn đến/đi từ số điện thoại cụ thể.
    - Truyền query param: ?phone=xxxxxxxxxx
    - Trả về danh sách contact + hội thoại tương ứng
    - Chỉ role staff, admin mới được phép truy cập
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["customer", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "light"

    def get(self, request):
        phone = request.query_params.get("phone")
        if not phone:
            return Response(
                {"status": "error", "message": INBOX_MESSAGES["missing_phone"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Fetch PhoneAccount ---
        obj = get_object_or_404(PhoneAccount, name=phone)

        if not obj.batch:
            return Response(
                {
                    "status": "error",
                    "message": INBOX_MESSAGES["missing_batch"]
                },
                status=status.HTTP_404_NOT_FOUND
            )

        if obj.status != "live":
            print("so dien thoai die roi:(())")
            redis_key = f"message_history:{obj.phone}"
            raw = cache.get(redis_key)
            raw_result = json.loads(raw)
            print('raw_result: ', raw_result)
            if not raw_result:
                return Response(
                    {"status": "error", "message": "Không có lịch sử trong cache"},
                    status=status.HTTP_404_NOT_FOUND
                )
            # raw_result = json.loads(raw)

        else:
            # --- Call cURL ---
            print("ko vao dây")
            raw_result = run_curl(obj.batch)
            print('raw_result; ', raw_result)
            if raw_result.get("status") == "error":
                obj.status = "die_use"
                obj.save(update_fields=["status"])

                return Response(
                    {
                        "status": "error",
                        "message": raw_result.get("message"),
                        "detail": raw_result,
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        body = raw_result.get("body")

        # --- Extract Messages ---
        contacts = {}
        conversations = {}

        try:
            for item in body.get("result", []):
                if "body" not in item:
                    continue

                try:
                    sub_body = json.loads(item["body"])
                except Exception:
                    continue

                new_comms = sub_body.get("result", {}).get("newCommunications", [])

                for msg in new_comms:
                    direction = msg.get("direction")
                    text = msg.get("text", "")
                    is_new_conversation = msg.get("isNewConversation")
                    my_status = msg.get("myStatus")
                    media = msg.get("media", {}).get("image") if msg.get("media") else None
                    time_created = to_utc_isoformat(msg.get("timeCreated"))

                    # Determine "other" side
                    if direction == "out":
                        other_info = msg.get("to", [{}])[0]
                    else:
                        other_info = msg.get("from", {})

                    other_number = other_info.get("TN")
                    other_name = other_info.get("name")

                    if not other_number:
                        continue

                    # Auto format name if missing
                    if not other_name:
                        other_name = f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"

                    # Update contacts with better names
                    if other_number not in contacts:
                        contacts[other_number] = other_name
                    else:
                        prev_name = contacts[other_number]
                        default_format = f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"
                        if prev_name in [other_number, default_format] and other_name not in [other_number, default_format]:
                            contacts[other_number] = other_name

                    # Save message into conversation
                    conversations.setdefault(other_number, []).append({
                        "direction": direction,
                        "text": text,
                        "my_status": my_status,
                        "image": media,
                        "time": time_created,
                        "is_new_conversation": is_new_conversation
                    })

            # --- Prepare final result ---
            contact_list = [{"phone": p, "name": n} for p, n in contacts.items()]

            return Response({
                "status": "success",
                "message": INBOX_MESSAGES["success"],
                "results": {
                    "contacts": contact_list,
                    "conversations": conversations
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error processing inbox data: {str(e)}")
            return Response(
                {
                    "status": "error",
                    "message": INBOX_MESSAGES["processing_error"],
                    "raw": body
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SendMessageView(APIView):
    """
    ✅ API: Gửi tin nhắn văn bản từ số Pinger/TextFree
    - Yêu cầu: phone, to, text
    - Chỉ role staff hoặc admin được phép gửi
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["customer", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'
    
    def post(self, request):
        phone = request.data.get("phone")
        to_raw = request.data.get("to")
        text = request.data.get("text")

        to_number, name = normalize_phone_number(to_raw)

        # === Validate input ===
        if not all([phone, to_number, text]):
            return Response(
                {"status": "error", "message": SEND_MESSAGE_MESSAGES["missing_fields"]},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Ensure number begins with 1
        if not to_number.startswith("1"):
            to_number = "1" + to_number

        try:
            # === Fetch PhoneAccount config ===
            obj = get_object_or_404(PhoneAccount, name=phone)

            if obj.status != "live":
                return Response(
                    {
                        "status": "error",
                        "message": SEND_MESSAGE_MESSAGES["invalid_phone"]
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            curl_text = obj.message
            if not curl_text:
                return Response(
                    {
                        "status": "error",
                        "message": SEND_MESSAGE_MESSAGES["missing_curl"]
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

            # === Remove media from existing cURL ===
            curl_text = re.sub(r',?\s*"media"\s*:\s*\{[^}]*\}', '', curl_text)

            # === Replace payload body ===
            new_body = {
                "text": text,
                "to": [{"name": name, "TN": to_number}]
            }
            body_str = json.dumps(new_body, ensure_ascii=False)

            updated_curl = re.sub(
                r'(--data-raw\s*\')[^\']*(\')',
                f"--data-raw '{body_str}'",
                curl_text
            )

            logger.info(f"Updated cURL: {updated_curl}", )

            # === Send actual message ===
            result = send_pinger_message(
                message_curl=updated_curl,
                to_number=to_number,
                text=text,
                name=name
            )

            status_code = result.get("status_code", 200)
            response_data = result.get("response", {})

            # errNo from Pinger → error
            if isinstance(response_data, dict) and "errNo" in response_data:
                status_code = 400

            return Response(
                {
                    "status": "success" if status_code == 200 else "error",
                    "message": SEND_MESSAGE_MESSAGES["success"] if status_code == 200 else SEND_MESSAGE_MESSAGES["send_failed"],
                    "sent_to": to_number,
                    "sent_to_name": name,
                    "text": text,
                    "status_code": status_code,
                    "response": response_data
                },
                status=status_code
            )

        except Exception as e:
            logger.error("Error sending message: %s", str(e))
            return Response(
                {
                    "status": "error",
                    "message": SEND_MESSAGE_MESSAGES["send_failed"]
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class SendMediaView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["customer", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'

    def post(self, request):
        phone = request.data.get("phone")
        to_raw = request.data.get("to")
        to_number, name = normalize_phone_number(to_raw)
        file = request.FILES.get("file")

        if not to_number.startswith("1"):
            to_number = "1" + to_number

        if not all([phone, to_number, file]):
            return Response({
                "status": "error",
                "message": SEND_MEDIA_MESSAGES["missing_fields"],
            }, status=400)

        obj = get_object_or_404(PhoneAccount, name=phone)

        if obj.status != "live":
            return Response({
                "status": "error",
                "message": SEND_MEDIA_MESSAGES["invalid_phone"],
            }, status=400)

        # -------------------------
        # STEP 1 — UPLOAD MEDIA
        # -------------------------
        uploaded_url, err = upload_pinger_media(obj.media, file)

        if err == "upload_failed":
            return Response({
                "status": "error",
                "message": SEND_MEDIA_MESSAGES["upload_error"],
            }, status=500)

        if err == "invalid_url":
            return Response({
                "status": "error",
                "message": SEND_MEDIA_MESSAGES["invalid_upload_url"],
            }, status=400)

        # -------------------------
        # STEP 2 — SEND MESSAGE
        # -------------------------
        send_result = send_pinger_message(
            message_curl=obj.message,
            to_number=to_number,
            text=" ",
            media_url=uploaded_url,
            name=name
        )

        status_code = send_result.get("status_code", 200)
        response_data = send_result.get("response", {})

        if "errNo" in response_data:
            status_code = 400

        return Response({
            "status": "success" if status_code == 200 else "error",
            "message": SEND_MEDIA_MESSAGES["success"] if status_code == 200 else SEND_MEDIA_MESSAGES["send_failed"],
            "sent_to": to_number,
            "uploaded_image_url": uploaded_url,
            "status_code": status_code,
            "response": response_data
        }, status=status_code)


class MailCategoriesView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'medium'
    @swagger_auto_schema(
        operation_description="Lấy danh sách categories mail từ provider (ví dụ: sellmmo, dongvan).",
        manual_parameters=[
            openapi.Parameter(
                "provider",
                openapi.IN_QUERY,
                description="Tên provider (sellmmo, dongvan, shopgmail, ...)",
                type=openapi.TYPE_STRING,
                required=True
            )
        ],
        responses={
            200: openapi.Response("Danh sách categories mail trả về thành công."),
            400: "Thiếu tham số hoặc dữ liệu không hợp lệ.",
            500: "Lỗi khi gọi API provider."
        }
    )

    def get(self, request):
        provider = request.query_params.get("provider")
        logger.info(f'provider: {provider}')
        if not provider:
            return Response(
                {"status": "error", "message": "Thiếu tham số 'provider'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        provider = provider.lower().strip()
        result = fetch_categories(provider)

        if result.get("status") == "error":
            return Response(
                {"status": "error", "message": result.get("error", "Không thể lấy danh sách mail.")},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        if result.get("status") == "success":
            return Response(
                {"status": "success", "provider": provider, "categories": result.get("categories", result)},
                status=status.HTTP_200_OK
            )

        else:
            return Response(
                {"status": "error", "message": "Lỗi hệ thống"},
                status=status.HTTP_200_OK
            )

            
class BuyMailView(APIView):
    """
    ✅ API: Mua mail từ provider (SellMMO hoặc DongVan)
    - Body JSON:
      {
        "provider": "sellmmo",
        "product_id": "1782",
        "amount": 2,
        "coupon": ""
      }
    - Chỉ role staff & admin được phép mua
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'

    def post(self, request):
        user = getattr(request.user, "employee_profile", None)
        provider = request.data.get("provider", "").lower().strip()
        logger.info(f"provider: {provider}")
        if not provider:
            return Response(
                {"status": "error", "message": "Thiếu provider."},
                status=status.HTTP_400_BAD_REQUEST
            )

        product_id = request.data.get("product_id")
        if not product_id:
            return Response(
                {"status": "error", "message": "Thiếu product_id."},
                status=status.HTTP_400_BAD_REQUEST
            )

        quality = int(request.data.get("quality", 0))
        logger.info(f"quality= {quality}")
        coupon = request.data.get("coupon", "")

        try:
            if provider == "sellmmo":
                result = buy_mail_sellmmo(employee=user, product_id=product_id, amount=quality, coupon=coupon)
                logger.info(f'result: {result}')
            elif provider == "dongvan":
                result = buy_mail_dongvan(employee=user, account_type=product_id, quality=quality)

            else:
                return Response(
                    {"status": "error", "message": f"Provider '{provider}' không được hỗ trợ."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            return Response(
                {
                    "status": result.get("status"),
                    "message": result.get("message"),
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            logger.error(f"Lỗi khi gọi API {provider}: {str(e)}")
            return Response(
                {"status": "error", "message": f"Lỗi khi gọi API {provider}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    
class GetAuthCodeView(APIView):
    """
    ✅ API: Lấy Auth Code của mail (OAuth2)
    - Body JSON:
      {
        "email": "example@hotmail.com"
      }
    - Hệ thống tự tra trong PurchasedMail để lấy refresh_token, client_id.
    - Chỉ role staff hoặc admin được phép thực hiện.
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'

    @swagger_auto_schema(
        request_body=GetAuthCodeSerializer,
        responses={200: "Auth code retrieval result"}
    )
    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response(
                {"status": "error", "message": "Thiếu trường 'email'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        mail_obj = PurchasedMail.objects.filter(email__iexact=email.strip()).first()
        if not mail_obj:
            return Response(
                {"status": "error", "message": f"Không tìm thấy thông tin mail '{email}' trong hệ thống."},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            result = get_auth_code(
                email=mail_obj.email,
                refresh_token=mail_obj.refresh_token,
                client_id=mail_obj.client_id
            )
        except Exception as e:
            logger.error( f"Lỗi khi gọi get_auth_code: {str(e)}")
            return Response(
                {"status": "error", "message": f"Lỗi khi gọi get_auth_code"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(result, status=status.HTTP_200_OK)


class ListPurchasedMailsView(APIView):
    """
    ✅ API: Lấy danh sách tất cả mail mà nhân viên hiện tại đã mua.
    - Tự động xác định nhân viên từ token.
    - Chỉ role staff hoặc admin được phép truy cập.
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def get(self, request):
        user = request.user
        employee = getattr(user, "employee_profile", None)
        if not employee:
            return Response(
                {"status": "error", "message": "Tài khoản hiện tại không phải nhân viên."},
                status=status.HTTP_403_FORBIDDEN
            )

        mails = (
            PurchasedMail.objects.filter(purchase__employee=employee, is_delete=False)
            .select_related("purchase", "purchase__provider")
            .order_by("-created_at")
        )

        serializer = PurchasedMailSerializer(mails, many=True)

        return Response({
            "status": "success",
            "employee": employee.user.username,
            "count": len(serializer.data),
            "mails": serializer.data
        }, status=status.HTTP_200_OK)


class SaveAppleMailView(APIView):
    """
    ✅ API: Lưu hoặc cập nhật Apple Mail & Proxy
    - Nếu mail đã tồn tại thì chỉ cập nhật proxy_ip và nhân viên.
    - Chỉ role `staff` và `admin` được phép thực hiện.
    - Body JSON:
      {
        "mail": "example@icloud.com",
        "proxy": "123.45.67.89:8000"
      }
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'

    def post(self, request):
        mail = request.data.get("mail")
        proxy_ip = request.data.get("proxy")

        if not mail or not proxy_ip:
            return Response(
                {"status": "error", "message": "Thiếu mail hoặc proxy."},
                status=status.HTTP_400_BAD_REQUEST
            )

        employee = getattr(request.user, "employee_profile", None)

        try:
            # 🧹 Nếu nhân viên đã có bản ghi cũ thì xóa đi
            existing_record = AppleMailProxy.objects.filter(employee=employee).first()
            if existing_record:
                existing_record.delete()

            # 🆕 Sau đó tạo mới
            record = AppleMailProxy.objects.create(
                mail=mail.strip().lower(),
                proxy_ip=proxy_ip.strip(),
                employee=employee,
            )

            return Response({
                "status": "success",
                "message": f"Mail '{mail}' đã được lưu mới cho nhân viên {employee.user.username}.",
                "data": {
                    "mail": record.mail,
                    "proxy": record.proxy_ip,
                    "created_at": record.created_at,
                    "employee": employee.user.username
                }
            }, status=status.HTTP_201_CREATED)

        except IntegrityError as e:
            logger.error(f"Lỗi trùng mail: {str(e)}")
            return Response({
                "status": "error",
                "message": "Mail này đã tồn tại trong hệ thống."
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Lỗi hệ thống: {str(e)}")
            return Response({
                "status": "error",
                "message": "Lỗi hệ thống khi lưu Apple Mail Proxy."
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SaveTextNowAccountView(APIView):
    """
    ✅ API: Lưu hoặc cập nhật tài khoản TextNow
    - Nếu email đã tồn tại → cập nhật thay vì tạo mới
    - Chỉ `staff` và `admin` có quyền thực hiện
    - Ghi nhận thông tin nhân viên thao tác gần nhất
    - Body JSON:
      {
        "email": "example@gmail.com",
        "password": "123456",
        "is_textnow": true,
        "api_key": "abc123"
      }
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'heavy'

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        # ✅ Validate input
        if not email or not password:
            return Response(
                {"status": "error", "message": "Thiếu email hoặc mật khẩu."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🧩 Lấy thông tin nhân viên đăng nhập
        employee = getattr(request.user, "employee_profile", None)

        try:
            # 🧱 Tìm hoặc tạo mới tài khoản
            account, created = TextNowAccount.objects.get_or_create(
                email=email.strip().lower(),
                defaults={
                    "employee": employee,
                    "password": password.strip()
                }
            )

            if not created:
                account.password = password.strip()
                account.employee = employee
                account.updated_at = timezone.now()
                account.save()

                return Response({
                    "status": "success",
                    "message": f"Tài khoản '{email}' đã được cập nhật thành công.",
                    "data": {
                        "email": account.email,
                        "employee": employee.user.username
                    }
                }, status=status.HTTP_200_OK)

            return Response({
                "status": "success",
                "message": f"Tài khoản '{email}' đã được thêm mới thành công.",
                "data": {
                    "email": account.email,
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Lỗi hệ thống: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi hệ thống"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EmployeePhoneSummaryView(APIView):
    """
    ✅ API: Thống kê số lượng PhoneAccount mà nhân viên đã tạo (Pinger, TextNow)
    - Chỉ nhân viên (`staff`, `admin`) được phép xem.
    - Tính:
        • Số điện thoại Pinger tạo hôm nay
        • Số live / die trong ngày
        • Tổng số Pinger trong tháng
        • Tổng số tài khoản TextNow toàn hệ thống
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def get(self, request):
        user = request.user
        employee = getattr(user, "employee_profile", None)

        if not employee:
            return Response({
                "status": "error",
                "message": "Tài khoản này không có hồ sơ nhân viên."
            }, status=status.HTTP_400_BAD_REQUEST)

        today = date.today()
        first_day_of_month = today.replace(day=1)

        try:
            # ---- Thống kê số điện thoại Pinger ----
            pinger_today_qs = PhoneAccount.objects.filter(
                provider="Pinger/Textfree",
                creator=employee,
                created_at__date=today
            )
            pinger_today = pinger_today_qs.count()
            pinger_today_live = pinger_today_qs.filter(status="live").count()
            pinger_today_die = pinger_today_qs.filter(
                Q(status="die") | Q(status="die_use") | Q(status="lock")
            ).count()
            
            pinger_month = PhoneAccount.objects.filter(
                provider="Pinger/Textfree",
                creator=employee,
                created_at__date__gte=first_day_of_month
            ).count()

            # ---- Thống kê TextNow ----
            textnow_total = TextNowAccount.objects.filter(employee=employee).count()

            # ---- Kết quả ----
            return Response({
                "status": "success",
                "message": f"Thống kê số điện thoại của nhân viên '{employee.user.username}'",
                "data": {
                    "employee": employee.user.username,
                    "pinger_today": pinger_today,
                    "pinger_today_live": pinger_today_live,
                    "pinger_today_die": pinger_today_die,
                    "pinger_month": pinger_month,
                    "textnow_total": textnow_total
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Lỗi hệ thống khi thống kê: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi hệ thống khi thống kê"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PurchasedMailViewSet(viewsets.ModelViewSet):
    serializer_class = PurchasedMailSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "staff"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def get_queryset(self):
        user = self.request.user
        employee = getattr(user, "employee_profile", None)

        if not employee:
            return PurchasedMail.objects.none()

        if employee.role == "admin":
            return PurchasedMail.objects.select_related("purchase", "purchase__employee").all()

        # 🔒 Staff chỉ thấy mail của chính mình
        return PurchasedMail.objects.select_related("purchase", "purchase__employee").filter(
            purchase__employee=employee
        )

    @transaction.atomic
    def destroy(self, request, pk=None):
        user = request.user
        employee = getattr(user, "employee_profile", None)

        if not employee:
            return Response(
                {"status": "error", "message": "Chỉ nhân viên mới có quyền xóa mail."},
                status=status.HTTP_403_FORBIDDEN,
            )

        mail_obj = get_object_or_404(
            PurchasedMail.objects.select_related("purchase", "purchase__employee"),
            pk=pk,
        )

        # 🔒 Staff chỉ được xóa mail của mình
        if employee.role != "admin" and (
            not mail_obj.purchase or mail_obj.purchase.employee != employee
        ):
            return Response(
                {"status": "error", "message": "Bạn không có quyền xóa mail này."},
                status=status.HTTP_403_FORBIDDEN,
            )

        mail_purchase = mail_obj.purchase
        mail_obj.delete()

        # 🧩 Nếu là mail cuối cùng → xoá luôn MailTransaction
        if mail_purchase and not MailTransaction.mails.exists():
            mail_purchase_id = mail_purchase.id
            mail_purchase.delete()
            return Response(
                {
                    "status": "success",
                    "message": f"Đã xoá mail {pk} và đơn mua #{mail_purchase_id} vì không còn mail nào.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"status": "success", "message": f"Đã xoá mail {pk} thành công."},
            status=status.HTTP_200_OK,
        )


class PurchasedMailBulkDeleteView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "staff"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    @transaction.atomic
    def delete(self, request):
        user = request.user
        employee = getattr(user, "employee_profile", None)

        # Chỉ lấy mail do nhân viên này đã mua (không lấy mail đã xóa)
        qs = PurchasedMail.objects.filter(
            purchase__employee=employee,
            is_delete=False
        )

        if not qs.exists():
            return Response(
                {
                    "status": "success",
                    "message": "Không có mail nào để xoá.",
                    "data": {"deleted_mails": 0, "deleted_purchases": 0},
                },
                status=status.HTTP_200_OK,
            )

        # Lưu lại các đơn mua bị ảnh hưởng
        purchase_ids = list(qs.values_list("purchase_id", flat=True).distinct())

        deleted_mails = qs.update(is_delete=True)


        return Response(
            {
                "status": "success",
                "message": f"Đã xoá {deleted_mails} mail do bạn mua. ",
                "data": {
                    "deleted_mails": deleted_mails,
                },
            },
            status=status.HTTP_200_OK,
        )

class PhoneReportByEmployeeView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    pagination_class = StandardResultsSetPagination
    throttle_scope = 'light'

    def paginate(self, request, queryset):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator, page
    
    def get(self, request):
        start = request.query_params.get("start_date")
        end = request.query_params.get("end_date")

        if not start or not end:
            return Response({
                "status": "error",
                "message": "Thiếu start_date hoặc end_date."
            }, status=400)

        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return Response({
                "status": "error",
                "message": "Sai định dạng ngày, dùng YYYY-MM-DD"
            }, status=400)

        queryset = PhoneAccount.objects.filter(
            created_at__date__range=[start_date, end_date]
        )

        by_employee = (
            queryset.values("creator__user__username", "created_at__date")
            .annotate(
                total_sdt=Count("id"),
                healthy=Count("id", filter=Q(status="live")),
                total_disabled=Count("id", filter=Q(status__in=["die", "lock", "die_use"])),
                lock_phone=Count("id", filter=Q(status="lock")),
                disabled_import=Count("id", filter=Q(status="die")),
                disabled_after=Count("id", filter=Q(status__in=["lock", "die_use"])),
            )
            .order_by("-created_at__date", "creator__user__username")  # 🔥 mới nhất → cũ nhất
        )

        records = []
        for item in by_employee:
            records.append({
                "nhan_vien": item["creator__user__username"],
                "ngay": item["created_at__date"],
                "tong_sdt": item["total_sdt"],
                "healthy": item["healthy"],
                "tong_disabled": item["total_disabled"],
                "total_lock_phone": item["lock_phone"],
                "disabled_luc_nhap": item["disabled_import"],
                "disabled_sau_khi_dung": item["disabled_after"],
            })

        summary = {
            "total_sdt": sum(e["tong_sdt"] for e in records),
            "healthy": sum(e["healthy"] for e in records),
            "total_disabled": sum(e["tong_disabled"] for e in records),
            "total_lock_phone": sum(e["total_lock_phone"] for e in records),
            "disabled_at_import": sum(e["disabled_luc_nhap"] for e in records),
            "disabled_after_use": sum(e["disabled_sau_khi_dung"] for e in records),
        }

        # 👉 PAGINATION HERE
        paginator, page = self.paginate(request, records)

        return paginator.get_paginated_response({
            "records": page,
            "summary": summary
        })


class PhoneReportByGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    pagination_class = StandardResultsSetPagination
    throttle_scope = 'light'

    def get(self, request):
        start = request.query_params.get("start_date")
        end = request.query_params.get("end_date")

        if not start or not end:
            return Response({"status": "error", "message": "Thiếu start_date hoặc end_date."}, status=400)

        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return Response({"status": "error", "message": "Sai định dạng ngày."}, status=400)

        queryset = PhoneAccount.objects.filter(
            created_at__date__range=[start_date, end_date]
        )

        all_groups = EmployeeGroup.objects.order_by("name")

        by_group = queryset.values("creator__group__name").annotate(
            total_sdt=Count("id"),
            healthy=Count("id", filter=Q(status="live")),
            total_disabled=Count("id", filter=Q(status__in=["die", "lock", "die_use"])),
            disabled_at_import=Count("id", filter=Q(status="die")),
            lock_phone_account=Count("id", filter=Q(status="lock")),
            disabled_after_use=Count("id", filter=Q(status__in=["lock", "die_use"])),
        )

        stats_group = {g["creator__group__name"]: g for g in by_group}
        total_phone_in_db = PhoneAccount.objects.count() or 1

        records = []
        for grp in all_groups:
            gname = grp.name
            data = stats_group.get(gname)

            created_count = data["total_sdt"] if data else 0

            records.append({
                "nhom": gname,
                "tong_sdt": created_count,
                "healthy": data["healthy"] if data else 0,
                "tong_disabled": data["total_disabled"] if data else 0,
                "total_lock_phone": data["lock_phone_account"] if data else 0,
                "disabled_luc_nhap": data["disabled_at_import"] if data else 0,
                "disabled_sau_khi_dung": data["disabled_after_use"] if data else 0,
                "ty_le": round((created_count / total_phone_in_db) * 100, 1),
            })

        summary = {
            "total_sdt": sum(g["tong_sdt"] for g in records),
            "healthy": sum(g["healthy"] for g in records),
            "total_disabled": sum(g["tong_disabled"] for g in records),
            "total_lock_phone": sum(g["total_lock_phone"] for g in records),
            "disabled_at_import": sum(g["disabled_luc_nhap"] for g in records),
            "disabled_after_use": sum(g["disabled_sau_khi_dung"] for g in records),
        }

        return Response({
            "status": "success",
            "message": "Thống kê theo nhóm.",
            "data": {"records": records, "summary": summary}
        })


class PhoneReportByGroupSoldView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    pagination_class = StandardResultsSetPagination
    throttle_scope = 'light'

    def get(self, request):
        start = request.query_params.get("start_date")
        end = request.query_params.get("end_date")

        if not start or not end:
            return Response({"status": "error", "message": "Thiếu start_date hoặc end_date."}, status=400)

        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return Response({"status": "error", "message": "Sai định dạng ngày."}, status=400)

        queryset = PhoneAccount.objects.filter(
            created_at__date__range=[start_date, end_date]
        )

        all_groups = EmployeeGroup.objects.order_by("name")
        sold_queryset = queryset.filter(is_used=True, customer__isnull=False)

        by_group_sold = sold_queryset.values("creator__group__name").annotate(
            sdt_da_cap=Count("id")
        )

        stats_group_sold = {g["creator__group__name"]: g for g in by_group_sold}
        total_all_phone = queryset.filter(is_used=True, customer__isnull=False).count() or 1

        records = []
        for grp in all_groups:
            gname = grp.name
            data = stats_group_sold.get(gname)
            sdt_da_cap = data["sdt_da_cap"] if data else 0

            records.append({
                "nhom": gname,
                "sdt_da_cap": sdt_da_cap,
                "ty_le": round((sdt_da_cap / total_all_phone) * 100, 1),
            })

        summary = {
            "tong_da_cap": sum(g["sdt_da_cap"] for g in records),
            "tong_tat_ca_sdt": total_all_phone,
        }

        return Response({
            "status": "success",
            "message": "Thống kê nhóm đã cấp.",
            "data": {"records": records, "summary": summary}
        })

class PhoneOverviewView(APIView):
    """
    ✅ API: Thống kê tổng quan hệ thống số điện thoại
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def get(self, request):
        try:
            total_sdt = PhoneAccount.objects.count()
            healthy_sdt = PhoneAccount.objects.filter(status="live").count()
            disabled_sdt = PhoneAccount.objects.filter(~Q(status="live")).count()
            sold_sdt = PhoneAccount.objects.filter(is_used=True, customer__isnull=False).count()
      
            waiting_sdt = PhoneAccount.objects.filter(
                is_used=False, status="live", customer__isnull=False
            ).count()

            data = {
                "tong_sdt": total_sdt,
                "healthy_sdt": healthy_sdt,
                "disabled_sdt": disabled_sdt,
                "da_cap_cho_user": sold_sdt,
                "dang_cho_cap": waiting_sdt,
            }

            return Response({
                "status": "success",
                "message": "Thống kê tổng quan số điện thoại thành công.",
                "data": data
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Lỗi khi lấy thống kê: {str(e)}")
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thống kê"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class BulkResetPasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'light'

    def post(self, request):
        customer_ids = request.data.get("customer_ids", [])
        if not customer_ids:
            return Response({"status": "error", "message": "customer_ids required"}, status=400)

        task = bulk_reset_password_task.delay(customer_ids)

        return Response({
            "status": "success",
            "task_id": task.id
        })
        
class TaskStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    allowed_roles = ["staff", "admin"]
    throttle_scope = 'light'

    def get(self, request, task_id):
        result = AsyncResult(task_id)
        print("status: ", result.status)
        print("result: ", result.result)
        print("traceback: ", result.traceback)
        print('task_id: ', task_id)

        if result.state == "PENDING":
            return Response({"status": "pending"})

        if result.state == "STARTED":
            return Response({"status": "running"})

        if result.state == "FAILURE":
            return Response({
                "status": "error",
                "message": str(result.result)
            })

        if result.state == "SUCCESS":
            return Response({
                "status": "success",
                "data": result.result.get("data", [])
            })

        return Response({"status": result.state.lower()})

def healthz(request):
    return HttpResponse("OK")
