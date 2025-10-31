# chat/views.py
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
import requests, json, time, logging
from rest_framework import status
from django.contrib.auth import authenticate, login, logout
from .serializers import PhoneAccountSerializer, CustomerSerializer
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.views.decorators.csrf import csrf_exempt
import base64
from .models import PhoneAccount
from rest_framework.permissions import IsAuthenticated, AllowAny
from .utils import run_curl, parse_curl, strip_proxy, send_pinger_message
import re
from rest_framework_simplejwt.tokens import RefreshToken


logger = logging.getLogger(__name__)

# ===== Views =====
def customer_home(request):
    return render(request, "customer.html")


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    try:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"error": "Refresh token is missing"}, status=status.HTTP_400_BAD_REQUEST)

        token = RefreshToken(refresh_token)
        token.blacklist()
        return Response({"success": "Logout successful"}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

# ---------------------------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_info(request):
    user = request.user

    # ✅ Nếu user có employee_profile → cấm truy cập
    if hasattr(user, "employee_profile"):
        return Response(
            {"error": "User có role Employee — không được phép truy cập API Customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ✅ Nếu user không có customer_profile → báo lỗi rõ
    if not hasattr(user, "customer_profile"):
        return Response(
            {"error": "User hiện không có Customer liên kết."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # ✅ OK, là customer thật sự
    customer = user.customer_profile
    serializer = CustomerSerializer(customer)
    
    # 🔹 Lấy thống kê phone accounts
    phones = PhoneAccount.objects.filter(customer=customer)
    total_phones = phones.count()
    alive_count = phones.filter(status="live").count()
    die_count = phones.filter(status="die").count()

    return Response(
      {
          "customer": serializer.data,
          "stats": {
              "total_phones": total_phones,
              "alive": alive_count,
              "die": die_count
          }
      },
      status=status.HTTP_200_OK
    )
#-----------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_phone_account(request):
    data = request.data.copy()
    print('data:', data)

    data["creator"] = request.user.id 
    for field in ["batch", "message", "media"]:
        if field in data and data[field]:
            try:
                decoded = base64.b64decode(data[field]).decode("utf-8")
                data[field] = decoded
            except Exception:
                pass
            data[field] = strip_proxy(data[field])

    serializer = PhoneAccountSerializer(data=data)
    if not serializer.is_valid():
        return Response({"errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    obj = serializer.save()

    print(f"Testing curl for phone {obj.phone} ...")
    try:
        result = run_curl(obj.batch)
        print("🔹 run_curl result:", result)

        # Nếu có lỗi hoặc HTTP status >= 400 → đánh die
        if "error" in result or result.get("status", 0) >= 400:
            obj.status = "die"
        else:
            obj.status = "alive"

    except Exception as e:
        print("Exception while testing curl:", e)
        obj.status = "die"

    obj.save(update_fields=["status"])

    return Response(
        {
            "message": f"Phone created successfully (status: {obj.status})",
            "data": PhoneAccountSerializer(obj).data
        },
        status=status.HTTP_201_CREATED
    )


# -----------
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def refresh_inbox(request):
    phone = request.query_params.get("phone")
    obj = get_object_or_404(PhoneAccount, phone=phone)

    curl_text = obj.batch
    if not curl_text:
        return Response(
            {"error": f"Không có batch script cho số {phone}"},
            status=status.HTTP_404_NOT_FOUND
        )

    raw_result = run_curl(curl_text)
    body = raw_result.get("body")

    # Nếu không có body JSON => lỗi
    if not isinstance(body, (dict, list)):
        try:
            body = json.loads(body)
        except Exception:
            return Response(
                {"error": "Không parse được dữ liệu trả về", "raw": body},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # Parse dữ liệu
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

                if not other_name:
                    other_name = f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"

                if other_number not in contacts:
                    contacts[other_number] = other_name
                else:
                    prev_name = contacts[other_number]
                    if prev_name == other_number or prev_name == f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}":
                        if other_name not in [other_number, f"({other_number[:3]}) {other_number[3:6]}-{other_number[6:]}"]:
                            contacts[other_number] = other_name

                conversations.setdefault(other_number, []).append({
                    "direction": direction,
                    "text": text,
                    "image": media,
                    "time": time_created
                })

        contact_list = [{"phone": p, "name": n} for p, n in contacts.items()]

        result = {
            "results": {
                "contacts": contact_list,
                "conversations": conversations
            }
        }

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": str(e), "raw": body},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_message(request):
    phone = request.data.get("phone")
    to_number = request.data.get("to")
    text = request.data.get("text")

    if not all([phone, to_number, text]):
        return Response({"error": "Missing required fields: phone / to / text"}, status=400)

    if not to_number.startswith("1"):
        to_number = "1" + to_number

    obj = get_object_or_404(PhoneAccount, phone=phone)
    curl_text = obj.message
    if not curl_text:
        return Response(
            {"error": f"Không có message cURL cho số {phone}"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # 🧹 Bước 1: Xóa phần "media": {...} trong cURL gốc
    # Hỗ trợ cả trường hợp có hoặc không dấu phẩy cuối
    curl_text = re.sub(
        r',?\s*"media"\s*:\s*\{[^}]*\}', '', curl_text
    )

    # 🧱 Bước 2: Tạo body mới
    new_body = {
        "text": text,
        "to": [
            {
                "name": f"({to_number[1:4]}) {to_number[4:7]}-{to_number[7:]}",
                "TN": to_number
            }
        ]
    }
    body_str = json.dumps(new_body, ensure_ascii=False)

    # 🧩 Bước 3: Thay body cũ trong cURL bằng body mới
    updated_curl = re.sub(
        r'(--data-raw\s*\')[^\']*(\')',
        f"--data-raw '{body_str}'",
        curl_text
    )

    print("✅ Updated curl (cleaned):")
    print(updated_curl)

    # 📨 Bước 4: Gửi request thật
    result = send_pinger_message(
        message_curl=updated_curl,
        to_number=to_number,
        text=text
    )
    print("result:", result)

    # Lấy mã mặc định từ response
    status_code = result.get("status_code", 200)
    response_data = result.get("response", {})

    # ⚠️ Nếu có errNo trong phản hồi → fail, đổi mã HTTP sang 400
    if isinstance(response_data, dict) and "errNo" in response_data:
        status_code = 400

    # Giữ nguyên format JSON trả về frontend
    return Response({
        "sent_to": to_number,
        "text": text,
        "status_code": status_code,
        "response": response_data
    }, status=status_code)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_media_api(request):
    phone = request.data.get("phone")
    print('phone: ', phone)
    to_number = request.data.get("to")
    print('to_number: ', to_number)
    file = request.FILES.get("file")
    print('file: ', file)

    obj = get_object_or_404(PhoneAccount, phone=phone)
    curl_text = obj.media
    if not curl_text:
        return Response({"error": f"Missing media cURL for this number {phone}"}, status=404)

    parsed = parse_curl(strip_proxy(curl_text))
    url = parsed.get("url")
    headers = parsed.get("headers", {})
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
    # Upload ảnh
    try:
        resp = requests.post(url, headers=headers, data=file.file, timeout=60)
        resp.raise_for_status()
        upload_text = resp.text
    except Exception as e:
        return Response({
            "sent_to": to_number,
            "uploaded_image_url": "(upload_failed)",
            "status_code": 500,
            "response": {"error": f"Failed to upload image: {str(e)}"}
        }, status=500)

    # Parse phản hồi upload
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
    print('uploaded_image_url: ', uploaded_image_url)
    if not uploaded_image_url or not str(uploaded_image_url).startswith("http"):
        return Response({
            "sent_to": to_number,
            "uploaded_image_url": "(upload_failed)",
            "status_code": 400,
            "response": {
                "errNo": err_no or 500,
                "errMsg": err_msg or "Upload response missing valid image URL",
                "raw_text": upload_text,
                "upload_response": upload_json
            }
        }, status=400)

    print('uploaded_image_url: ', uploaded_image_url)

    try:
        send_result = send_pinger_message(
            message_curl=obj.message,
            to_number=to_number,
            text=" ", 
            media_url=uploaded_image_url
        )
    except Exception as e:
        return Response({"error": f"Unable to send message: {str(e)}"}, status=500)

    response_data = send_result.get("response", {})
    status_code = send_result.get("status_code", 200)

    # ⚠️ Nếu gửi ảnh lỗi (errNo có trong phản hồi)
    if isinstance(response_data, dict) and "errNo" in response_data:
        status_code = 400

    return Response({
        "sent_to": to_number,
        "uploaded_image_url": uploaded_image_url,
        "status_code": status_code,
        "response": response_data
    }, status=status_code)