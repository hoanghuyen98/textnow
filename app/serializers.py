import re
import hashlib
from rest_framework import serializers
from .models import PhoneAccount, Customer, PurchasedMail, EmployeeGroup, Employee
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db.models import Q
from django.db import transaction
from .models import PhoneAccount, AppleMailProxy  # tránh circular import
from logzero import logger
import random, string

class AppleMailProxySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.user.username", read_only=True)

    class Meta:
        model = AppleMailProxy
        fields = [
            "id",
            "employee",
            "employee_name",
            "mail",
            "proxy_ip",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

class EmployeeGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeGroup
        fields = "__all__"

    def validate_name(self, value):
        instance = getattr(self, "instance", None)
        qs = EmployeeGroup.objects.filter(name__iexact=value.strip())
        if instance:
            qs = qs.exclude(id=instance.id)
        if qs.exists():
            # ⚠️ Thay đổi ở đây — ép message về string
            raise serializers.ValidationError(str(f"Tên nhóm '{value}' đã tồn tại."), code="invalid")
        return value


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ["id", "username", "password"]


class EmployeeGroupSimpleSerializer(serializers.ModelSerializer):
    """Serializer rút gọn của group: chỉ lấy id và name"""
    class Meta:
        model = EmployeeGroup
        fields = ["id", "name"]


class EmployeeSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", required=False)
    password = serializers.CharField(source="user.password", required=False)
    group_id = serializers.IntegerField(source="group.id", read_only=True, required=False)
    group_name = serializers.CharField(source="group.name", allow_null=True, required=False, allow_blank=True)
    raw_password = serializers.CharField(read_only=True, required=False)
    role = serializers.CharField(read_only=True)
    class Meta:
        model = Employee
        fields = [
            "id",
            "username",
            "password",
            "role",
            "group_id",
            "group_name",
            "raw_password",
        ]

    # ----------------------------
    # ✅ CREATE
    # ----------------------------
    def create(self, validated_data):
        print('---------------------')
        print('validated_data: ', validated_data)
        user_data = validated_data.pop("user", {})
        username = user_data.get("username")
        password = user_data.get("password")
        group = validated_data.pop("group", None)

        
        # 🔍 Kiểm tra trùng username
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save()
        else:
            raise serializers.ValidationError(
                {"username": f"Tên đăng nhập '{username}' đã tồn tại."}
            )
        group_ob = None

        if group and group.get("name"):
            group_name = group["name"].strip()
            if group_name:  # chỉ khi không rỗng
                group_ob = EmployeeGroup.objects.filter(name=group_name).first()
                if not group_ob:
                    raise serializers.ValidationError(
                        {"group_name": f"Nhóm '{group_name}' không tồn tại."}
                    )
        employee = Employee.objects.create(
            user=user,
            group=group_ob,
            raw_password=password,
            **validated_data
        )
        return employee
    # ----------------------------
    # ✅ UPDATE
    # ----------------------------
    def update(self, instance, validated_data):
        print('validated_data:', validated_data)

        # --- Lấy thông tin user ---
        user_data = validated_data.pop("user", {})
        username = user_data.get("username")
        password = user_data.get("password")
        group_data = validated_data.pop("group", None)

        user = instance.user


        if password:
            user.set_password(password)
            user.save()
            instance.raw_password = password


        if group_data and group_data.get("name"):
            group_name = group_data["name"].strip()
            if group_name:
                group_obj = EmployeeGroup.objects.filter(name=group_name).first()
                if not group_obj:
                    raise serializers.ValidationError(
                        {"group_name": f"Nhóm '{group_name}' không tồn tại."}
                    )
                instance.group = group_obj

        instance.save()
        return instance

class PhoneAccountSerializer(serializers.ModelSerializer):
    creator = serializers.StringRelatedField(read_only=True)
    phone_validator = RegexValidator(
        regex=r'^\(\d{3}\)\s?\d{3}-\d{4}$',
        message="Số điện thoại phải có dạng (234) 123-1234."
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[phone_validator],
    )
    class Meta:
        model = PhoneAccount
        fields = [
            "id", "name", "phone", "mail", "provider", "status", "creator",
            "batch", "message", "media", "created_at", "updated_at"
        ]

    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # ✅ Chuẩn hoá tên — loại bỏ ký tự đặc biệt, chỉ giữ chữ và số
    def normalize_phone(self, text: str) -> str:
        if not text:
            return ""
        # Giữ lại chỉ chữ và số, bỏ ký tự đặc biệt và khoảng trắng
        return re.sub(r"[^A-Za-z0-9]", "", text)

    # ✅ Chuẩn hoá số điện thoại sang dạng (XXX) XXX-XXXX nếu nhập thô
    def normalize_name(self, text: str) -> str:
        if not text:
            return ""
        digits = re.sub(r"\D", "", text)
        if len(digits) == 10:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        return text  # nếu không đủ 10 số, giữ nguyên

        
    def extract_oauth_fields(self, curl_text: str):
      """Trích xuất 4 giá trị OAuth từ chuỗi curl, trả về (fields, curl_text)."""
      if not curl_text:
          return {}, None

      auth_match = re.search(r"-H\s+'Authorization:\s*([^']+)'", curl_text)
      auth_str = auth_match.group(1).strip() if auth_match else None

      fields = {}
      if auth_str:
          for field in ["oauth_consumer_key", "oauth_timestamp", "oauth_signature", "oauth_nonce"]:
              match = re.search(rf'{field}="([^"]+)"', auth_str)
              if match:
                  fields[field] = match.group(1)

      return fields, curl_text.strip()


    def check_duplicate_in_db(self, field_name, field_values):
        """
        Kiểm tra field OAuth trùng trong DB.
        Trả về list các key bị trùng (nếu có)
        """
        print("field_name: ", field_name)
        if field_values:
            # dùng icontains để tránh lỗi None
            print(PhoneAccount.objects.filter(**{f"{field_name}": field_values}).first())
            if PhoneAccount.objects.filter(**{f"{field_name}": field_values}).exists():
                print("flkdsjflkdsj")
                return True
            print("chua ton tai")
        return False


    def validate(self, data):
        errors = {}
        raw_name = data.get("name") 
        normalize_name = self.normalize_name(raw_name)
        normalize_phone = self.normalize_phone(raw_name)
        logger.info('normalize_name: ', normalize_name)
        logger.info('normalize_phone: ', normalize_phone)
        data["name"] = normalize_name
        data["phone"] = normalize_phone

        # Nếu không có hoặc không đúng định dạng (XXX) XXX-XXXX
        if not normalize_name:
            errors["phone"] = "Thiếu số điện thoại hoặc không hợp lệ."
        elif not re.match(r'^\(\d{3}\)\s?\d{3}-\d{4}$', normalize_name):
            errors["phone"] = "Số điện thoại phải có dạng (234) 123-1234."

        # =====================================================
        # 🔹 Trích xuất OAuth fields từ 3 loại curl
        # =====================================================
        batch_fields, batch_text = self.extract_oauth_fields(data.get("batch"))
        message_fields, message_text = self.extract_oauth_fields(data.get("message"))
        media_fields, media_text = self.extract_oauth_fields(data.get("media"))
 
        # =====================================================
        # 🔹 Kiểm tra trùng lặp OAuth key trong DB
        # =====================================================
        batch_dupes = self.check_duplicate_in_db("batch", batch_text)
        message_dupes = self.check_duplicate_in_db("message", message_text)
        media_dupes = self.check_duplicate_in_db("media", media_text)

        if batch_dupes:
            errors["batch"] = "API batch này đã tồn tại trong hệ thống."
        if message_dupes:
            errors["message"] = "API message này đã tồn tại trong hệ thống."
        if media_dupes:
            errors["media"] = "API media này đã tồn tại trong hệ thống."

        # =====================================================
        # 🔹 Kiểm tra trùng số điện thoại trong DB
        # =====================================================
        if normalize_phone and PhoneAccount.objects.filter(phone=normalize_phone).exists():
            errors["phone"] = "Số điện thoại này đã tồn tại trong hệ thống."

        # =====================================================
        # 🔹 Trả lỗi nếu có
        # =====================================================
        if errors:
            raise serializers.ValidationError(errors)

        return data

class PhoneOfCustomerSimpleSerializer(serializers.ModelSerializer):
    """Serializer rút gọn của group: chỉ lấy id và name"""
    status  = serializers.CharField(source="get_status_display", read_only=True)
    class Meta:
        model = PhoneAccount
        fields = ["id", "name", "phone", "status"]


class CustomerAutoCreateSerializer(serializers.Serializer):
    phone_count = serializers.IntegerField(min_value=1, required=True)

    def format_phone(self, phone: str) -> str:
        """
        Chuẩn hóa số điện thoại dạng 10 chữ số sang format: (289) 205-3372
        """
        # Lấy các ký tự số
        digits = re.sub(r'\D', '', phone)

        # Nếu có 10 số, định dạng theo chuẩn (XXX) XXX-XXXX
        if len(digits) == 10:
            return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
        return phone  # fallback nếu không đủ 10 số

    def create(self, validated_data):
        phone_count = validated_data["phone_count"]
        logger.info(phone_count)
        logger.info("check")
        all_obj = PhoneAccount.objects.all()
        all_obj = PhoneAccount.objects.all()

        for obj in all_obj:
            print(f"id={obj.id}, phone={obj.phone}, status='{obj.status}', is_used={obj.is_used}")
        logger.info(all_obj)

        available_phones = (
            PhoneAccount.objects.filter(status="live", is_used=False)
            .order_by("created_at")[: phone_count * 2]
        )
        logger.info(available_phones)

        
        if available_phones.count() == 0:
            return {
                "status": "error",
                "message": "Không có số điện thoại khả dụng (live & chưa dùng).",
                "data": None
            }

        created_accounts = []
        created_count = 0

        with transaction.atomic():
            for phone in available_phones:
                if created_count >= phone_count:
                    break

                formatted_phone = self.format_phone(phone.phone)
                username = formatted_phone

                # Nếu user đã tồn tại thì bỏ qua
                if User.objects.filter(username=username).exists():
                    continue

                password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

                # 🔹 Tạo user
                user = User.objects.create_user(username=username, password=password)

                # 🔹 Tạo customer
                customer = Customer.objects.create(
                    user=user,
                    raw_password=password,
                    phone_assigned_count=1
                )

                # 🔹 Gán số điện thoại
                phone.customer = customer
                phone.is_used = True
                phone.save()

                created_accounts.append({
                    "username": username,
                    "password": password,
                })
                created_count += 1

            if created_count < phone_count:
                return {
                    "status": "warning",
                    "message": f"Chỉ tạo được {created_count}/{phone_count} tài khoản (do trùng username hoặc thiếu số khả dụng).",
                    "data": created_accounts
                }

        return {
            "status": "success",
            "message": f"Tạo thành công {created_count} tài khoản khách hàng.",
            "data": created_accounts
        }


class CustomerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", required=False)
    password = serializers.CharField(source="user.password", required=False)
    phone_assigned_count = serializers.IntegerField()
    phones = serializers.SerializerMethodField()
    raw_password = serializers.CharField(read_only=True, required=False)
    class Meta:
        model = Customer
        fields = ["id", "username", "password", "raw_password", "phone_assigned_count", "phones"]


    def get_phones(self, obj):
        # ✅ Chỉ lấy các PhoneAccount có customer = obj
        phones = PhoneAccount.objects.filter(customer=obj)
        return PhoneOfCustomerSimpleSerializer(phones, many=True).data

    def create(self, validated_data):
        print('-------')
        print('validated_data:sss ', validated_data)
        user_data = validated_data.pop("user", {})
        username = user_data.get("username")
        password = user_data.get("password")
        phone_count = validated_data.pop("phone_assigned_count")
        print('phone_count: ', phone_count)

        if User.objects.filter(username=username).exists():
                    raise serializers.ValidationError(
                        {"username": f"Tên đăng nhập '{username}' đã tồn tại."}
                    )
        user = User.objects.create_user(username=username, password=password)
        
        customer = Customer.objects.create(user=user, **validated_data)
        customer.raw_password = password
        customer.save()
        customer.refresh_from_db()

        # Gán số điện thoại nếu có
        if phone_count > 0:
            print('phone_count: ', phone_count)
            available_phones = (
                PhoneAccount.objects.filter(status="live", is_used=False)
                .order_by("created_at")[:phone_count]
            )
            print('available_phones: ', available_phones)
            if available_phones.count() < phone_count:
                raise serializers.ValidationError(
                    {"phone_count": "Không đủ số điện thoại khả dụng (live & chưa dùng)."}
                )
            for phone in available_phones:
                phone.customer = customer
                phone.is_used = True
                phone.save()
            customer.phone_assigned_count += phone_count
            customer.save()

        return customer

    def update(self, instance, validated_data):
        print('-------')
        print('validated_data:sss ', validated_data)
        user_data = validated_data.pop("user", {})
        username = user_data.get("username")
        password = user_data.get("password")
        phone_count = validated_data.pop("phone_assigned_count", 0)
        print("-------------------------: ", phone_count)
        user = instance.user

        if password:
            user.set_password(password)
            instance.password = password
            instance.raw_password = password
        user.save()
        print('----------------')
        instance.save()

        if phone_count > 0:
            available_phones = (
                PhoneAccount.objects.filter(status="live", is_used=False)
                .order_by("created_at")[:phone_count]
            )
            print('available_phones: ', available_phones)
            if available_phones.count() < phone_count:
                raise serializers.ValidationError(
                    {"phone_count": "Không đủ số điện thoại khả dụng (live & chưa dùng)."}
                )
            for phone in available_phones:
                print("???")
                phone.customer = instance
                phone.is_used = True
                phone.save()
            instance.phone_assigned_count += phone_count
            print("djkshadjksah")
            instance.save()
        return instance

    def get_plain_password(self, obj):
        return getattr(obj, "_raw_password", None)


class PhoneAccountMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneAccount
        fields = ["name", "phone", "status"]  # chỉ 2 trường


class PurchasedMailSerializer(serializers.ModelSerializer):
    purchase_id = serializers.IntegerField(source="purchase.id", read_only=True)
    purchase_employee = serializers.CharField(
        source="purchase.employee.user.username", read_only=True
    )

    class Meta:
        model = PurchasedMail
        fields = [
            "id",
            "email",
            "password",
            "provider",
            "is_used",
            "created_at",
            "purchase_id",
            "purchase_employee",
        ]

class GetAuthCodeSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, help_text="Địa chỉ email cần lấy Auth Code")

class CreatePhoneAccountSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, help_text="Email đã mua để tạo tài khoản Phone")
    name = serializers.CharField(required=True, help_text="Phone đã mua")
    batch = serializers.CharField(required=False, allow_blank=True, help_text="Chuỗi cURL batch (base64 encode)")
    message = serializers.CharField(required=False, allow_blank=True, help_text="Chuỗi cURL message (base64 encode)")
    media = serializers.CharField(required=False, allow_blank=True, help_text="Chuỗi cURL media (base64 encode)")

class RefreshInboxViewSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, help_text="Phone cần xem tin nhắn")

class MailCategoriesViewSerializer(serializers.Serializer):
    provider = serializers.CharField(required=True, help_text="provider cung cấp")


    