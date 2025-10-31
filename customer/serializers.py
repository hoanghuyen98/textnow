import re
import hashlib
from rest_framework import serializers
from .models import PhoneAccount, Customer


class PhoneAccountSerializer(serializers.ModelSerializer):
    creator = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = PhoneAccount
        fields = [
            "id", "name", "phone", "mail", "provider", "status", "creator",
            "batch", "message", "media", "created_at", "updated_at"
        ]

    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # ------------------------------
    # ✅ Chuẩn hóa số điện thoại
    # ------------------------------
    def normalize_phone(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\D", "", text)  # giữ lại chỉ chữ số

    # =========================================================
    # ✅ 2. Hàm trích xuất 4 trường trong Authorization
    # =========================================================
    def extract_oauth_fields(self, curl_text: str):
        """Trích xuất 4 giá trị OAuth từ chuỗi curl"""
        if not curl_text:
            return {}

        # Tìm dòng Authorization trong curl
        auth_match = re.search(r"-H\s+'Authorization:\s*([^']+)'", curl_text)
        if not auth_match:
            return {}

        auth_str = auth_match.group(1)

        # Regex trích từng trường
        fields = {}
        for field in ["oauth_consumer_key", "oauth_timestamp", "oauth_signature", "oauth_nonce"]:
            match = re.search(rf'{field}="([^"]+)"', auth_str)
            if match:
                fields[field] = match.group(1)

        return fields

    # =========================================================
    # ✅ Validate tổng hợp
    # =========================================================
    def validate(self, data):
        errors = {}

        # 🔹 Chuẩn hoá phone
        if not data.get("phone"):
            data["phone"] = self.normalize_phone(data.get("name", ""))
        else:
            data["phone"] = self.normalize_phone(data["phone"])

        # 🔹 Trích 4 field OAuth cho từng loại curl
        batch_fields = self.extract_oauth_fields(data.get("batch"))
        message_fields = self.extract_oauth_fields(data.get("message"))
        media_fields = self.extract_oauth_fields(data.get("media"))

        # =====================================================
        # 🔹 Check trùng trong DB (theo từng nhóm batch/message/media)
        # =====================================================
        def check_duplicate_in_db(field_name, field_values):
            """Trả về list các oauth_fields trùng trong DB"""
            if not field_values:
                return []

            duplicates = []
            for key, value in field_values.items():
                if PhoneAccount.objects.filter(**{f"{field_name}__icontains": value}).exists():
                    duplicates.append(key)
            return duplicates

        batch_dupes = check_duplicate_in_db("batch", batch_fields)
        message_dupes = check_duplicate_in_db("message", message_fields)
        media_dupes = check_duplicate_in_db("media", media_fields)

        # =====================================================
        # 🔹 Gom lỗi lại theo field
        # =====================================================
        if batch_dupes:
            dup_list = ", ".join(batch_dupes)
            errors["batch"] = [f"Duplicate detected in batch vui lòng kiểm tra lại API."]

        if message_dupes:
            dup_list = ", ".join(message_dupes)
            errors["message"] = [f"Duplicate detected in message vui lòng kiểm tra lại API."]

        if media_dupes:
            dup_list = ", ".join(media_dupes)
            errors["media"] = [f"Duplicate detected in media vui lòng kiểm tra lại API."]

        # 🔹 Check trùng name/phone
        if data.get("name") and PhoneAccount.objects.filter(name__iexact=data["name"].strip()).exists():
            errors["name"] = [f"Duplicate name detected: '{data['name']}'"]

        if data.get("phone") and PhoneAccount.objects.filter(phone=data["phone"]).exists():
            errors["phone"] = [f"Duplicate phone detected: {data['phone']}"]

        # =====================================================
        if errors:
            raise serializers.ValidationError(errors)

        return data

class PhoneAccountMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneAccount
        fields = ["name", "phone", "status"]  # chỉ 2 trường

class CustomerSerializer(serializers.ModelSerializer):
    phones = PhoneAccountMinimalSerializer(many=True, read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    class Meta:
        model = Customer
        fields = ["id", "username", "company_name", "address", "status", "phones"]