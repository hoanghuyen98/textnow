import requests
from django.utils import timezone
from .models import MailProvider, MailTransaction, PurchasedMail
from dotenv import load_dotenv
from logzero import logger
import re
from bs4 import BeautifulSoup
from django.db.models import Q
import os
from .utils import extract_auth_code 
load_dotenv()

SELLMMO_KEY = os.environ.get('SELLMMO_KEY')
DONGVAN_KEY = os.environ.get('DONGVAN_KEY')
MUAVIEW_KEY = os.environ.get('MUAVIEW_KEY')

API_CONFIG = {
    "sellmmo": {
        "base_url": "https://www.sellmmo.net/api",
        "key": SELLMMO_KEY,
        "endpoints": {
            "categories": "/products.php",
            "buy": "/buy_product",
            "otp": "https://tools.dongvanfb.net/api/get_messages_oauth2"
        }
    },
    "dongvan": {
        "base_url": "https://api.dongvanfb.net",
        "key": DONGVAN_KEY,  
        "endpoints": {
            "categories": "/user/account_type",
            "buy": "/user/buy",
            "otp": "https://tools.dongvanfb.net/api/get_messages_oauth2"
        }
    },
    "muaview": {
        "base_url": "https://muaview.vn",
        "key": MUAVIEW_KEY,  
        "endpoints": {
            "categories": "/api/thuemailao/GetOtpServices",
            "buy": "/api/thuemailao/CreateOtpOrder",
            "otp": "/api/thuemailao/CheckOtpOrder",
        }
    },
}



def fetch_categories(provider: str):
    """
    Gọi API lấy danh mục của từng provider.
    provider: sellmmo | dongvan | shopgmail
    """
    provider = provider.lower().strip()
    if provider not in API_CONFIG:
        raise ValueError(f"Provider '{provider}' không được hỗ trợ.")

    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["categories"]

    # thêm params khác nhau tùy từng API
    params = {}
    if provider == "sellmmo":
        params["api_key"] = conf["key"]
    elif provider == "dongvan":
        params["apikey"] = conf["key"]
    elif provider == "muaview":
        params["apikey"] = conf["key"]


    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        
    except Exception as e:
        logger.error(f"Lỗi khi gọi tới API của {provider}: {str(e)}")
        return {"status": "error", "message": "Lỗi hệ thống"}

    result = []
    if provider == "sellmmo":
        categories = data.get("categories") or []

        # Các category cần lấy
        allowed_category_ids = {"14", "57"}

        for cat in categories:
            # Nếu id không thuộc danh sách → bỏ qua
            if str(cat.get("id")) not in allowed_category_ids:
                continue

            for p in cat.get("products", []):
                full_name = p.get("name", "")
                price = str(p.get("price") or "").strip()

                short_name = full_name.split("-")[0].strip()
                if price:
                    short_name = f"{short_name} ({price})"

                result.append({
                    "id": p.get("id"),
                    "name": short_name,
                    "price": price,
                    "amount": p.get("amount"),
                    "description": p.get("desc") or p.get("description"),
                    "icon": cat.get("icon")
                })

    elif provider == "dongvan":
        items = data.get("data") or []
        result.extend([
            {
                "id": int(item["id"]),
                "name": f"{item.get('name')} ({item.get('price')})",
                "price": item.get("price"),
                "amount": item.get("quality"),
            }
            for item in items
            if str(item.get("id", "")).isdigit() and int(item["id"]) in (1, 2)
        ])

    elif provider == "muaview":
        items = data.get("data") or []
        result.extend([
            {
                "id": int(item["id"]),
                "name": f"{item['name']} ({item['price']})",
                "price": item["price"],
            }
            for item in items
        ])

    return {"status": "success", "provider": provider, "count": len(result), "data": result}


def buy_mail_sellmmo(employee, product_id: str, amount: int = 1, coupon: str = ""):

    provider = "sellmmo"
    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["buy"]

    payload = {
        "action": "buyProduct",
        "id": product_id,
        "amount": amount,
        "coupon": coupon,
        "api_key": conf["key"]
    }

    logger.info(f"[SellMMO] payload: {payload}")

    try:
        resp = requests.post(url, data=payload, timeout=15)
        data = resp.json()
    except Exception as e:
        logger.error(f"Lỗi khi gọi API SellMMO: {e}")
        return {"status": "error", "message": f"Lỗi hệ thống mua mail"}

    if data.get("status") != "success":
        return {"status": "error", "message": data.get("msg", "Lỗi không xác định")}

    raw_items = data.get("data") or []
    mails = []
    for item in raw_items:
        parts = item.split("|")
        email = parts[0].strip() if len(parts) > 0 else ""
        password = parts[1].strip() if len(parts) > 1 else ""
        refresh_token = parts[2].strip() if len(parts) > 2 else ""
        client_id = parts[3].strip() if len(parts) > 3 else ""

        mails.append({
            "email": email,
            "password": password,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "provider": provider
        })

    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider, defaults={"base_url": conf["base_url"], "api_key": conf["key"]}
    )

    purchase = MailTransaction.objects.create(
        provider=provider_obj,
        employee=employee,
        product_id=product_id,
        product_name=f"Product {product_id}",
        quantity=len(mails),
        trans_id=data.get("trans_id") or timezone.now().strftime("%Y%m%d%H%M%S"),
        status="success",
        raw_response=data,
    )

    for m in mails:
        PurchasedMail.objects.create(
            purchase=purchase,
            email=m.get("email"),
            password=m.get("password"),
            refresh_token=m.get("refresh_token", ""),
            client_id=m.get("client_id", ""),
            provider=m.get("provider", provider),
            is_used=False
        )

    return {
        "status": "success",
        "message": f"Đã mua {len(mails)} email(s).",
        "mails": mails
    }


def buy_mail_muaview(employee, service_id: int, quality: int = 1):
    provider = "muaview"
    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["buy"]

    mails = []
    order_ids = []
    logger.info(f"service_id: {service_id}")
    # Lặp từng lần tạo order vì API chỉ trả về 1 mail/order
    for i in range(quality):

        params = {
            "apikey": conf["key"],
            "service_id": service_id
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            logger.info(f"[Muaview][Buy][{i+1}/{quality}] response: {data}")
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Muaview: {e}")
            return {"status": "error", "message": "Lỗi hệ thống khi mua mail"}

        if not data.get("success"):
            return {"status": "error", "message": data.get("message", "Lỗi không xác định")}

        result = data.get("data", {})
    
        mail = {
            "email": result.get("email"),
            "password": "",
            "refresh_token": "",
            "client_id": result.get("order_id"),
            "provider": provider,
        }
        logger.info(mail)
        mails.append(mail)
        order_ids.append(result.get("order_id"))

    # -------- SAVE TO DATABASE --------
    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider,
        defaults={"base_url": conf["base_url"], "api_key": conf["key"]},
    )

    purchase = MailTransaction.objects.create(
        provider=provider_obj,
        employee=employee,
        product_id=str(service_id),
        product_name=result.get("service_name", f"Service {service_id}"),
        quantity=len(mails),
        total_price=None,     # nếu API trả giá thì update vào đây
        trans_id=",".join(map(str, order_ids)),
        status="success",
        raw_response={"orders": mails},
    )

    # insert từng mail
    for m in mails:
        PurchasedMail.objects.create(
            purchase=purchase,
            email=m.get("email"),
            password=m.get("password"),
            refresh_token=m.get("refresh_token", ""),
            client_id=m.get("client_id", ""),
            provider=m.get("provider", provider),
            is_used=False
        )
    logger.info(mails)
    print("-------------")
    return {
        "status": "success",
        "message": f"Đã mua {len(mails)} email(s).",
        "mails": mails
    }


def buy_mail_dongvan(employee, account_type: int, quality: int = 0, type: str = "full"):
    provider = "dongvan"
    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["buy"]

    params = {
        "apikey": conf["key"],
        "account_type": account_type,
        "quality": quality,
        "type": type
    }


    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        logger.info(f"[DongVan] response: {data}")
    except Exception as e:
        logger.error(f"Lỗi khi gọi API DongVan: {e}")
        return {"status": "error", "message": f"Lỗi hệ thống mua mail"}

    if not data.get("status"):
        return {"status": "error", "message": data.get("message", "Lỗi không xác định")}

  
    result = data.get("data", {})
    raw_items = result.get("list_data", [])
    mails = []

    for item in raw_items:
        parts = item.split("|")
        email = parts[0] if len(parts) > 0 else ""
        password = parts[1] if len(parts) > 1 else ""
        refresh_token = parts[2] if len(parts) > 2 else ""
        client_id = parts[3] if len(parts) > 3 else ""

        mails.append({
            "email": email.strip(),
            "password": password.strip(),
            "refresh_token": refresh_token.strip(),
            "client_id": client_id.strip(),
            "provider": provider
        })


    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider, defaults={"base_url": conf["base_url"], "api_key": conf["key"]}
    )

    purchase = MailTransaction.objects.create(
        provider=provider_obj,
        employee=employee,
        product_id=str(account_type),
        product_name=result.get("account_type", f"Type {account_type}"),
        quantity=len(mails),
        total_price=result.get("total_amount"),
        trans_id=result.get("order_code") or timezone.now().strftime("%Y%m%d%H%M%S"),
        status="success",
        raw_response=data,
    )

    for m in mails:
        PurchasedMail.objects.create(
            purchase=purchase,
            email=m.get("email"),
            password=m.get("password"),
            refresh_token=m.get("refresh_token", ""),
            client_id=m.get("client_id", ""),
            provider=m.get("provider", provider),
            is_used=False
        )
    return {
        "status": "success",
        "message": f"Đã mua {len(mails)} email(s).",
        "mails": mails
    }



def get_auth_code(email: str, refresh_token: str, client_id: str, provider: str):
    """
    - Tự detect provider từ PurchasedMail (sellmmo / dongvan / muaview)
    - sellmmo + dongvan → dùng inbox OAuth2 (tools.dongvanfb.net)
    - muaview → dùng order_id = client_id (CheckOtpOrder)
    - Giữ nguyên format response legacy
    """

    print("provider: ", provider)
    print("")
    # =============== MUAVIEW (client_id = order_id) =================
    if provider == "muaview":
        url = API_CONFIG["muaview"]["base_url"] + API_CONFIG["muaview"]["endpoints"]["otp"]
        params = {
            "apikey": API_CONFIG["muaview"]["key"],
            "order_id": client_id,   # client_id chính là order_id
        }
        logger.info(f"client_id: {client_id}")
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
        except Exception as e:
            logger.error(f"Muaview OTP error: {e}")
            return {"status": "error", "message": "Không kết nối được Muaview"}

        if not data.get("success"):
            return {"status": "error", "message": data.get("message", "Lỗi OTP Muaview")}

        result = data.get("data", {}) or {}
        otp = result.get("otp")

        return {
            "status": "success" if otp else "pending",
            "provider": "muaview",
            "email": result.get("email") or email,
            "auth_code": otp or "",
            "from": "",
            "subject": "",
            "date": "",
        }

    # ============= SELLMO & DONGVAN (OAuth2 inbox) =================
    if not all([email, refresh_token, client_id]):
        return {"status": "error", "message": "Thiếu email/refresh_token/client_id để lấy OTP"}

    # nếu không lookup được thì fallback default là dongvan
    if provider not in ("sellmmo", "dongvan"):
        provider = "dongvan"

    url = API_CONFIG[provider]["endpoints"]["otp"]  # đều là tools.dongvanfb.net/api/get_messages_oauth2
    payload = {
        "email": email.strip(),
        "refresh_token": refresh_token.strip(),
        "client_id": client_id.strip(),
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        data = resp.json()
    except Exception as e:
        logger.error(f"Lỗi OTP {provider}: {e}")
        return {"status": "error", "message": f"Lỗi hệ thống khi gọi OTP {provider}."}

    if not data or not data.get("status"):
        return {
            "status": "error",
            "message": data.get("message", "Không thể lấy dữ liệu hợp lệ từ OTP API."),
        }

    messages = data.get("messages", []) or []
    if not messages:
        return {"status": "error", "message": f"Không có email nào trong hộp thư {email}."}

    # dò mã xác minh trong từng email
    for m in messages:
        if not m.get("code"):
            html_content = m.get("message", "")
            code = extract_auth_code(html_content)
            if code:
                m["code"] = code

    messages_with_code = [m for m in messages if m.get("code")]
    if not messages_with_code:
        return {"status": "error", "message": f"Không tìm thấy mã xác minh trong hộp thư {email}."}

    latest_msg = sorted(messages_with_code, key=lambda x: x.get("uid", 0))[-1]

    return {
        "status": "success",
        "provider": provider,
        "email": data.get("email") or email,
        "auth_code": latest_msg.get("code"),
        "from": latest_msg.get("from"),
        "subject": latest_msg.get("subject"),
        "date": latest_msg.get("date"),
    }