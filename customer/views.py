# chat/views.py
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
import requests, json, time, logging
from rest_framework import status, viewsets, permissions, serializers
from django.contrib.auth import authenticate, login, logout
from rest_framework.decorators import action
from .serializers import PhoneAccountSerializer, CustomerSerializer, PurchasedMailSerializer, EmployeeGroupSerializer, EmployeeSerializer, GetAuthCodeSerializer, PurchasedMailSerializer,CreatePhoneAccountSerializer, MailCategoriesViewSerializer
from rest_framework.response import Response
from django.db.models import Count, Q
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
import base64
from .models import PhoneAccount, PurchasedMail, AppleMailProxy, TextNowAccount, Employee, EmployeeGroup, Customer
from rest_framework.permissions import IsAuthenticated, AllowAny
from .utils import run_curl, parse_curl, strip_proxy, send_pinger_message, normalize_phone_number
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
from datetime import date
from .service import fetch_categories, buy_mail_dongvan, buy_mail_sellmmo, get_auth_code
from functools import wraps
from drf_yasg.utils import swagger_auto_schema
from django.db import transaction
from datetime import datetime
from .tasks import check_phone_all_batches
from drf_yasg import openapi
logger = logging.getLogger(__name__)

# ===== Views =====
def customer_home(request):
    return render(request, "customer.html")

class CheckStatusView(APIView):
    """
    POST: Tạo task kiểm tra toàn bộ batch
    GET: Kiểm tra trạng thái task (qua task_id)
    """

    def post(self, request):
        print('---------------')
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

class CustomTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        print('data: ')
        try:
            access = AccessToken(data["access"])
            print('access: ', access)
            user = User.objects.get(id=access["user_id"])
        except Exception:
            return data

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


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is missing"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"success": "Logout successful"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


class EmployeeGroupViewSet(viewsets.ModelViewSet):
    queryset = EmployeeGroup.objects.all()
    serializer_class = EmployeeGroupSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "staff"]

    # ---------------------------
    # ✅ GET DETAIL
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin nhóm: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ CREATE (POST)
    # ---------------------------
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
            print('message: ', message)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "status": "error",
                "message": f"Lỗi khi tạo nhóm: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ UPDATE (PUT/PATCH)
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật nhóm: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ DELETE
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi xóa nhóm nhân viên: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.select_related('user', 'group').filter(role="staff")
    serializer_class = EmployeeSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    pagination_class = StandardResultsSetPagination
    allowed_roles = ["admin", "staff"]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset().order_by('user__username'))

        # áp dụng phân trang
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response({
                "status": "success",
                "message": "Lấy danh sách nhân viên thành công.",
                "data": serializer.data
            })

    
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "status": "success",
            "message": "Lấy danh sách nhân viên thành công.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)

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
            print('message: ', message)
            return Response({
                "status": "error",
                "message": message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "status": "error",
                "message": f"Lỗi không xác định: {str(e)}"
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin: {str(e)}"
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật: {str(e)}"
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi xoá nhân viên: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.select_related("user").all()
    serializer_class = CustomerSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    pagination_class = StandardResultsSetPagination
    allowed_roles = ["admin", "staff"]

    def list(self, request, *args, **kwargs):
        # Sắp xếp theo tên user hoặc cột fullname, tùy model bạn có
        queryset = self.filter_queryset(self.get_queryset().order_by("user__username"))

        # Áp dụng phân trang
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response({
                "status": "success",
                "message": "Lấy danh sách khách hàng thành công.",
                "data": serializer.data
            })

        # Nếu không phân trang (trả full list)
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            "status": "success",
            "message": "Lấy danh sách khách hàng thành công.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    # ---------------------------
    # ✅ GET DETAIL
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi lấy thông tin khách hàng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ CREATE (POST)
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi tạo khách hàng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ UPDATE (PUT/PATCH)
    # ---------------------------
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
            return Response({
                "status": "error",
                "message": f"Lỗi khi cập nhật khách hàng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ---------------------------
    # ✅ DELETE
    # ---------------------------
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
        except Exception as e:
            return Response({
                "status": "error",
                "message": f"Lỗi khi xóa khách hàng: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class CustomerInfoView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "customer"]

    def get(self, request):
        user = request.user

        customer = user.customer_profile
        serializer = CustomerSerializer(customer)

        phones = PhoneAccount.objects.filter(customer=customer)
        stats = {
            "total_phones": phones.count(),
            "alive": phones.filter(status="live").count(),
            "die": phones.filter(status="die").count(),
        }

        return Response({
            "status": "success",
            "customer": serializer.data,
            "stats": stats
        }, status=status.HTTP_200_OK)


class CreatePhoneAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]
    @swagger_auto_schema(
        request_body=CreatePhoneAccountSerializer,
        responses={201: "Phone created successfully", 400: "Validation failed"}
    )
    def post(self, request):
        data = request.data.copy()
        data["creator"] = request.user.id
        print('request.user.id: ', request.user.id)
        email = data.get("mail") or data.get("email")
        employee = request.user.employee_profile
        print('emplpyee: ', employee)
        if not email:
            return Response(
                {"status": "error", "message": "Thiếu email để gán cho PhoneAccount."},
                status=status.HTTP_400_BAD_REQUEST
            )
        purchased_mail = PurchasedMail.objects.filter(email=email, purchase__employee=employee).first()

        print('purchased_mail: ', purchased_mail)
        if purchased_mail:
            if purchased_mail.is_used:
              return Response(
                  {"status": "error", "message": f"Email '{email}' đã được sử dụng cho tài khoản khác."},
                  status=status.HTTP_400_BAD_REQUEST
              )
        # --- Giải mã base64 cho batch/message/media ---
        for field in ["batch", "message", "media"]:
            if field in data and data[field]:
                try:
                    decoded = base64.b64decode(data[field]).decode("utf-8")
                    data[field] = decoded
                except Exception:
                    pass
                data[field] = strip_proxy(data[field])

        # --- Validate serializer ---
        serializer = PhoneAccountSerializer(data=data)
        if not serializer.is_valid():
            return Response(
                {"status": "fail", "detail": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        phone_obj = serializer.save()

        try:
            result = run_curl(phone_obj.batch)
            if "error" in result or result.get("status", 0) >= 400:
                phone_obj.status = "die"
            else:
                phone_obj.status = "alive"
        except Exception as e:
            print("Exception while testing curl:", e)
            phone_obj.status = "die"

        phone_obj.save(update_fields=["status"])

        return Response(
            {
                "status": "success",
                "message": f"Tạo Phone thành công (trạng thái: {phone_obj.status})",
                "phone": phone_obj.phone,
                "email": email,
                "mail_status": "marked_used",
                "creator": request.user.username
            },
            status=status.HTTP_201_CREATED
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

    def get(self, request):
        phone = request.query_params.get("phone")
        print('(629) 234-3458: ', phone)
        if not phone:
            return Response(
                {"status": "error", "message": "Thiếu tham số phone trong query string"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # --- Lấy thông tin phone ---
        obj = get_object_or_404(PhoneAccount, phone=phone)
        if obj.status != "live":
            return Response(
                {
                    "status": "error",
                    "message": f"Số {phone} không hợp lệ, không thể load tin nhắn."
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        if not obj.batch:
            return Response(
                {"status": "error", "message": f"Không có batch script cho số {phone}"},
                status=status.HTTP_404_NOT_FOUND
            )

        # --- Gọi cURL để lấy dữ liệu tin nhắn ---
        raw_result = run_curl(obj.batch)
        if (
            not raw_result
            or raw_result.get("error")
            or raw_result.get("status") != 200
        ):
            obj.status = "die_use"
            obj.save(update_fields=["status"])

            return Response(
                {
                    "status": "error",
                    "message": "Không thể lấy dữ liệu tin nhắn, đã đổi trạng thái sang 'die_use'.",
                    "detail": raw_result,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
            
        body = raw_result.get("body")

        # --- Parse JSON nếu cần ---
        if not isinstance(body, (dict, list)):
            try:
                body = json.loads(body)
            except Exception:
                obj.status = "die_use"
                obj.save(update_fields=["status"])
                return Response(
                    {
                        "status": "error",
                        "message": "Không parse được dữ liệu trả về",
                        "raw": body,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        contacts = {}
        conversations = {}

        try:
            for item in body.get("result", []):
                if "body" not in item:
                    continue

                body_str = item["body"]
                try:
                    sub_body = json.loads(body_str)
                except Exception:
                    continue

                new_comms = sub_body.get("result", {}).get("newCommunications", [])

                for msg in new_comms:
                    direction = msg.get("direction")
                    text = msg.get("text", "")
                    media = msg.get("media", {}).get("image") if msg.get("media") else None
                    time_created = msg.get("timeCreated")

                    if direction == "out":
                        other_info = msg.get("to", [{}])[0]
                    else:
                        other_info = msg.get("from", {})

                    other_number = other_info.get("TN")
                    other_name = other_info.get("name")

                    if not other_number:
                        continue

                    # Format tên nếu thiếu
                    if not other_name:
                        other_name = f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"

                    # Cập nhật contact
                    if other_number not in contacts:
                        contacts[other_number] = other_name
                    else:
                        prev_name = contacts[other_number]
                        # Nếu tên cũ chỉ là số, cập nhật tên mới đẹp hơn
                        if prev_name == other_number or prev_name == f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}":
                            if other_name not in [other_number, f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"]:
                                contacts[other_number] = other_name

                    # Lưu tin nhắn hội thoại
                    conversations.setdefault(other_number, []).append({
                        "direction": direction,
                        "text": text,
                        "image": media,
                        "time": time_created
                    })

            # --- Chuẩn hóa kết quả ---
            contact_list = [{"phone": p, "name": n} for p, n in contacts.items()]

            return Response({
                "status": "success",
                "message": "Lấy lịch sử thành công",
                "results": {
                    "contacts": contact_list,
                    "conversations": conversations
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": f"Lỗi khi xử lý dữ liệu: {str(e)}",
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

    def post(self, request):
        phone = request.data.get("phone")
        to_raw = request.data.get("to")
        text = request.data.get("text")
        to_number, name = normalize_phone_number(to_raw)
        # 🧩 Kiểm tra dữ liệu đầu vào
        if not all([phone, to_number, text]):
            return Response(
                {"status": "error", "message": "Thiếu các trường bắt buộc: phone / to / text"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Chuẩn hóa đầu số (phải bắt đầu bằng 1)
        if not to_number.startswith("1"):
            to_number = "1" + to_number

        try:
            # 🔍 Lấy cấu hình cURL từ DB
            obj = get_object_or_404(PhoneAccount, phone=phone)
            if obj.status != "live":
              return Response(
                  {
                      "status": "error",
                      "message": f"Số {phone} không hợp lệ, không thể gửi tin nhắn."
                  },
                  status=status.HTTP_400_BAD_REQUEST
              )
            curl_text = obj.message
            if not curl_text:
                return Response(
                    {"status": "error", "message": f"Không có message cURL cho số {phone}"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 🧹 Xóa phần "media": {...} trong cURL (nếu có)
            curl_text = re.sub(r',?\s*"media"\s*:\s*\{[^}]*\}', '', curl_text)

            # 🧱 Body mới (thay text/to)
            new_body = {
                "text": text,
                "to": [
                    {
                        "name": name,
                        "TN": to_number
                    }
                ]
            }
            body_str = json.dumps(new_body, ensure_ascii=False)

            # 🧩 Thay body cũ trong cURL bằng body mới
            updated_curl = re.sub(
                r'(--data-raw\s*\')[^\']*(\')',
                f"--data-raw '{body_str}'",
                curl_text
            )

            print("✅ Updated cURL:\n", updated_curl)

            # 📨 Gửi tin nhắn thật qua Pinger API
            result = send_pinger_message(
                message_curl=updated_curl,
                to_number=to_number,
                text=text,
                name=name
            )
            print("📬 Result:", result)

            status_code = result.get("status_code", 200)
            response_data = result.get("response", {})

            # Nếu có lỗi errNo từ server → chuyển sang lỗi 400
            if isinstance(response_data, dict) and "errNo" in response_data:
                status_code = 400

            return Response({
                "status": "success" if status_code == 200 else "error",
                "sent_to": to_number,
                "sent_to_name": name,
                "text": text,
                "status_code": status_code,
                "response": response_data
            }, status=status_code)

        except Exception as e:
            print("Lỗi khi gửi tin nhắn:", str(e))
            return Response({
                "status": "error",
                "message": f"Không gửi được tin nhắn"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class SendMediaView(APIView):
    """
    ✅ API: Gửi tin nhắn có hình ảnh (media) qua Pinger/TextFree
    - Upload ảnh qua cURL media, sau đó gửi qua message API
    - Chỉ role staff hoặc admin được phép gửi
    - Body (multipart/form-data):
        phone: số Pinger/TextFree
        to: số người nhận
        file: file ảnh (jpg/png)
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["customer", "admin"]

    def post(self, request):
        print("---------------------")
        phone = request.data.get("phone")
        to_raw = request.data.get("to")
        to_number, name = normalize_phone_number(to_raw)

        file = request.FILES.get("file")

        # Chuẩn hóa đầu số (phải bắt đầu bằng 1)
        if not to_number.startswith("1"):
            to_number = "1" + to_number

        # 🧩 Kiểm tra dữ liệu đầu vào
        if not all([phone, to_number, file]):
            return Response(
                {"status": "error", "message": "Thiếu các trường bắt buộc: phone / to / file"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 🔍 Lấy tài khoản Pinger tương ứng
            obj = get_object_or_404(PhoneAccount, phone=phone)
            if obj.status != "live":
                return Response(
                    {
                        "status": "error",
                        "message": f"Số {phone} không hợp lệ, không thể gửi tin nhắn."
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            curl_text = obj.media
            if not curl_text:
                return Response(
                    {"status": "error", "message": f"Không có media cURL cho số {phone}"},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 🧹 Parse lại cURL & chuẩn bị headers upload
            parsed = parse_curl(strip_proxy(curl_text))
            url = parsed.get("url")
            headers = parsed.get("headers", {}) or {}
            headers.pop("Host", None)

            mime_type = file.content_type or "application/octet-stream"
            headers.update({
                "Content-Type": mime_type,
                "Upload-Incomplete": "?0",
                "Upload-Draft-Interop-Version": "3",
                "Content-Encoding": "binary",
                "Accept": "*/*"
            })
            for h in ["Accept-Encoding", "Transfer-Encoding", "Content-Length"]:
                headers.pop(h, None)

            # 🧾 Bước 1: Upload ảnh
            try:
                resp = requests.post(url, headers=headers, data=file.file, timeout=60)
                upload_text = resp.text
                print('upload_text: ' , upload_text)
                resp.raise_for_status()

            except Exception as e:
                print("Lỗi upload ảnh:", str(e))
                return Response({
                    "status": "error",
                    "sent_to": to_number,
                    "uploaded_image_url": "(upload_failed)",
                    "status_code": 500,
                    "message": "Lỗi khi upload ảnh."
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 🧾 Bước 2: Parse phản hồi upload
            try:
                upload_json = resp.json()
            except Exception:
                upload_json = {}

            uploaded_image_url = (
                upload_json.get("url")
                or upload_json.get("result", {}).get("url")
                or upload_json.get("result", {}).get("image")
                or upload_json.get("result", {}).get("media", {}).get("url")
            )

            if not uploaded_image_url or not str(uploaded_image_url).startswith("http"):
                return Response({
                    "status": "error",
                    "sent_to": to_number,
                    "uploaded_image_url": "(upload_failed)",
                    "status_code": 500,
                    "message": "Upload response không có URL hợp lệ."
                }, status=status.HTTP_400_BAD_REQUEST)

            # 📨 Bước 3: Gửi ảnh qua message API
            try:
                send_result = send_pinger_message(
                    message_curl=obj.message,
                    to_number=to_number,
                    text=" ",  # bắt buộc phải có text field
                    media_url=uploaded_image_url,
                    name=name,
                )
            except Exception as e:
                print("Lỗi khi gửi ảnh:", str(e))
                return Response({
                    "status": "error",
                    "message": f"Không thể gửi ảnh: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # 🧩 Bước 4: Phản hồi kết quả
            response_data = send_result.get("response", {})
            status_code = send_result.get("status_code", 200)
            if isinstance(response_data, dict) and "errNo" in response_data:
                status_code = 400

            return Response({
                "status": "success" if status_code == 200 else "error",
                "sent_to": to_number,
                "uploaded_image_url": uploaded_image_url,
                "status_code": status_code,
                "response": response_data
            }, status=status_code)

        except Exception as e:
       
            print("Lỗi không xác định trong quá trình gửi media:", str(e))
            return Response({
                "status": "error",
                "message": f"Không gửi được tin nhắn có hình ảnh: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MailCategoriesView(APIView):
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]

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
        if not provider:
            return Response(
                {"status": "error", "message": "Thiếu tham số 'provider'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        provider = provider.lower().strip()
        result = fetch_categories(provider)

        if not result.get("success"):
            return Response(
                {"status": "error", "message": result.get("error", "Không thể lấy danh sách mail."), "data": result},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {"status": "success", "provider": provider, "categories": result.get("categories", result)},
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

    def post(self, request):
        user = getattr(request.user, "employee_profile", None)
        provider = request.data.get("provider", "").lower().strip()

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

        amount = int(request.data.get("amount", 1))
        coupon = request.data.get("coupon", "")

        try:
            if provider == "sellmmo":
                result = buy_mail_sellmmo(employee=user, product_id=product_id, amount=amount, coupon=coupon)
                print('result: ', result)
            elif provider == "dongvan":
                result = buy_mail_dongvan(employee=user, account_type=product_id, quality=amount)

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
            return Response(
                {"status": "error", "message": f"Lỗi khi gọi API {provider}: {str(e)}"},
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
            return Response(
                {"status": "error", "message": f"Lỗi khi gọi get_auth_code: {str(e)}"},
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

    def get(self, request):
        user = request.user
        employee = getattr(user, "employee_profile", None)
        if not employee:
            return Response(
                {"status": "error", "message": "Tài khoản hiện tại không phải nhân viên."},
                status=status.HTTP_403_FORBIDDEN
            )

        mails = (
            PurchasedMail.objects.filter(purchase__employee=employee)
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

    def post(self, request):
        mail = request.data.get("mail")
        proxy_ip = request.data.get("proxy")

        # ✅ Kiểm tra đầu vào
        if not mail or not proxy_ip:
            return Response(
                {"status": "error", "message": "Thiếu mail hoặc proxy."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🧩 Xác định nhân viên đang thao tác
        employee = getattr(request.user, "employee_profile", None)
        if not employee:
            return Response(
                {"status": "error", "message": "Chỉ nhân viên mới có quyền lưu mail Apple."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            # 🧱 Tìm hoặc tạo mới
            record, created = AppleMailProxy.objects.get_or_create(
                mail=mail.strip().lower(),
                defaults={
                    "proxy_ip": proxy_ip.strip(),
                    "employee": employee
                }
            )

            if not created:
                # 🔁 Cập nhật proxy + nhân viên thao tác mới nhất
                record.proxy_ip = proxy_ip.strip()
                record.employee = employee
                record.updated_at = timezone.now()
                record.save()

                return Response({
                    "status": "success",
                    "message": f"Đã cập nhật proxy cho mail '{mail}'.",
                    "data": {
                        "mail": record.mail,
                        "proxy": record.proxy_ip,
                        "updated_at": record.updated_at,
                        "employee": employee.user.username
                    }
                }, status=status.HTTP_200_OK)

            # 🆕 Nếu là bản ghi mới
            return Response({
                "status": "success",
                "message": f"Mail '{mail}' đã được thêm mới.",
                "data": {
                    "mail": record.mail,
                    "proxy": record.proxy_ip,
                    "created_at": record.created_at,
                    "employee": employee.user.username
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                "status": "error",
                "message": f"Lỗi hệ thống: {str(e)}"
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
            return Response({
                "status": "error",
                "message": f"Lỗi hệ thống: {str(e)}"
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
                provider="pinger",
                creator=employee,
                created_at__date=today
            )

            pinger_today = pinger_today_qs.count()
            pinger_today_live = pinger_today_qs.filter(status="live").count()
            pinger_today_die = pinger_today_qs.filter(status="die").count()

            pinger_month = PhoneAccount.objects.filter(
                provider="pinger",
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
            return Response({
                "status": "error",
                "message": f"Lỗi hệ thống khi thống kê: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PurchasedMailViewSet(viewsets.ModelViewSet):
    serializer_class = PurchasedMailSerializer
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["admin", "staff"]

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

    @action(detail=False, methods=["delete"], url_path="delete-all")
    @transaction.atomic
    def delete_all(self, request):
        """DELETE /api/v1/purchased-mails/delete-all/"""
        user = request.user
        employee = getattr(user, "employee_profile", None)
        if not employee:
            return Response(
                {"status": "error", "message": "Chỉ nhân viên mới có quyền xoá mail."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Lấy đúng phạm vi theo role (admin = tất cả, staff = của mình)
        qs = self.get_queryset().only("id", "purchase_id")

        if not qs.exists():
            return Response(
                {"status": "success", "message": "Không có mail nào để xoá.", "data": {"deleted_mails": 0, "deleted_purchases": 0}},
                status=status.HTTP_200_OK,
            )

        # Lưu lại các purchase bị ảnh hưởng
        purchase_ids = list(qs.values_list("purchase_id", flat=True).distinct())

        # Xoá toàn bộ mails trong phạm vi
        deleted_mails, _ = qs.delete()

        # Xoá MailTransaction không còn mail nào
        deleted_purchases, _ = (
            MailTransaction.objects.filter(id__in=purchase_ids)
            .annotate(cnt=Count("mails"))
            .filter(cnt=0)
            .delete()
        )

        return Response(
            {
                "status": "success",
                "message": f"Đã xoá {deleted_mails} mail. Đã xoá {deleted_purchases} đơn mua không còn mail.",
                "data": {
                    "deleted_mails": deleted_mails,
                    "deleted_purchases": deleted_purchases,
                },
            },
            status=status.HTTP_200_OK,
        )


class PhoneReportView(APIView):
    """
    ✅ API: Báo cáo tổng hợp số điện thoại theo ngày nhập
    - Query params: ?start=YYYY-MM-DD&end=YYYY-MM-DD
    - Chỉ staff/admin được phép truy cập
    """
    permission_classes = [permissions.IsAuthenticated, RoleRequiredPermission]
    allowed_roles = ["staff", "admin"]

    def get(self, request):
        start = request.query_params.get("start_date")
        end = request.query_params.get("end_date")
        print('start: ', start)
        if not start or not end:
            return Response(
                {"error": "Thiếu tham số start hoặc end (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return Response(
                {"error": "Sai định dạng ngày. Dùng YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        print("-0---")
        # Lọc dữ liệu trong khoảng thời gian
        queryset = PhoneAccount.objects.filter(
            created_at__date__range=[start_date, end_date]
        )
        print('queryset---------: ', queryset)
        # Gộp theo nhân viên tạo
        grouped = (
            queryset.values("creator__user__username")
            .annotate(
                total_sdt=Count("id"),
                healthy=Count("id", filter=Q(status="live")),
                total_disabled=Count("id", filter=~Q(status__in=["live", "lock"])),
                disabled_at_import=Count("id", filter=Q(status="die", is_used=False)),
                disabled_after_use=Count("id", filter=Q(status="lock", is_used=True)),
            )
            .order_by("creator__user__username")
        )


        print('grouped: ', grouped)
        # Tổng hợp cuối bảng
        summary = {
            "total_sdt": sum(item["total_sdt"] for item in grouped),
            "healthy": sum(item["healthy"] for item in grouped),
            "total_disabled": sum(item["total_disabled"] for item in grouped),
            "disabled_at_import": sum(item["disabled_at_import"] for item in grouped),
            "disabled_after_use": sum(item["disabled_after_use"] for item in grouped),
        }

        # Định dạng dữ liệu trả về
        records = [
            {
                "nhan_vien": g["creator__user__username"] or "Không rõ",
                "tong_sdt": g["total_sdt"],
                "healthy": g["healthy"],
                "tong_disabled": g["total_disabled"],
                "disabled_luc_nhap": g["disabled_at_import"],
                "disabled_sau_khi_dung": g["disabled_after_use"],
            }
            for g in grouped
        ]

        return Response({
            "records": records,
            "summary": summary
        }, status=status.HTTP_200_OK)
