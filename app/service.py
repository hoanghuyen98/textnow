import requests
from django.utils import timezone
from .models import MailProvider, MailTransaction, PurchasedMail
from dotenv import load_dotenv
from logzero import logger
import re
import time
from bs4 import BeautifulSoup
from django.db.models import Q
import os
from .utils import extract_auth_code, parse_mail_date 
load_dotenv()

SELLMMO_KEY = os.environ.get('SELLMMO_KEY')
DONGVAN_KEY = os.environ.get('DONGVAN_KEY')
MUAVIEW_KEY = os.environ.get('MUAVIEW_KEY')
SHOPGMAIL_KEY = os.environ.get('SHOPGMAIL_KEY')

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
    "muaview_that": {
        "base_url": "https://muaview.vn",
        "key": MUAVIEW_KEY,  
        "endpoints": {
            "categories": "/api/ApiV2/GetListServices",
            "buy": "/api/ApiV2/CreateOrder",
            "otp": "/api/ApiV2/CheckOtp",
        }
    },
    "shopgmail": {
        "base_url": "https://api.shopgmail9999.com",
        "key": SHOPGMAIL_KEY,  
        "endpoints": {
            "categories": "/api/ApiV2/GetListServices",
            "buy": "/api/ApiV2/CreateOrder",
            "otp": "/api/ApiV2/CheckOtp",
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
    elif provider == "muaview_that":
        params["apikey"] = conf["key"]
    elif provider == "shopgmail":
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
        for item in items:
            if not str(item.get("id", "")).isdigit():
                continue
            item_id = int(item["id"])
            if item_id not in (1, 2):
                continue
            name = item.get("name") or ""
            price = item.get("price") or ""
            result.append({
                "id": item_id,
                "name": f"{name} ({price})" if price else name,
                "price": price,
                "amount": item.get("quality"),
            })

    elif provider == "muaview":
        items = data.get("data") or []
        allowed_ids = {15, 16}
        for item in items:
            try:
                item_id = int(item["id"])
            except (KeyError, ValueError, TypeError):
                continue
            if item_id not in allowed_ids:
                continue
            try:
                result.append({
                    "id": item_id,
                    "name": f"{item['name']} ({item['price']})",
                    "price": item["price"],
                })
            except (KeyError, TypeError):
                continue

    elif provider == "muaview_that":
        items = data.get("data") or []
        allowed_ids = {64}
        for item in items:
            try:
                item_id = int(item.get("id", -1))
            except (ValueError, TypeError):
                continue
            if item_id not in allowed_ids:
                continue
            try:
                result.append({
                    "id": item_id,
                    "name": f"{item['name']} ({item['price']})",
                    "price": item["price"],
                })
            except (KeyError, TypeError):
                continue

    elif provider == "shopgmail":
        items = data.get("data") or []
        allowed_ids = {155}
        for item in items:
            try:
                item_id = int(item.get("id", -1))
            except (ValueError, TypeError):
                continue
            if item_id not in allowed_ids:
                continue
            try:
                result.append({
                    "id": item_id,
                    "name": f"{item['name']} ({item['price']})",
                    "price": item["price"],
                })
            except (KeyError, TypeError):
                continue

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
    logger.info(f"service_id: {service_id}")

    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider,
        defaults={"base_url": conf["base_url"], "api_key": conf["key"]},
    )

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
            continue

        if not data.get("success"):
            logger.error(f"[Muaview] API error: {data}")
            continue

        result = data.get("data", {})
        order_id = result.get("order_id")
        email = result.get("email")

        if not order_id or not email:
            logger.error(f"[Muaview] response thiếu dữ liệu: {result}")
            continue

        # -------- 1️⃣ SAVE TRANSACTION --------
        purchase = MailTransaction.objects.create(
            provider=provider_obj,
            employee=employee,
            product_id=str(service_id),
            product_name=result.get("service_name", f"Service {service_id}"),
            quantity=1,
            total_price=None,
            trans_id=order_id,      # ❗ 1 order = 1 transaction
            status="success",
            raw_response=result,
        )

        # -------- 2️⃣ SAVE PURCHASED MAIL --------
        PurchasedMail.objects.create(
            purchase=purchase,
            email=email,
            password="",
            refresh_token="",
            client_id=order_id,
            provider=provider,
            is_used=False
        )

        mail = {
            "email": email,
            "password": "",
            "refresh_token": "",
            "client_id": order_id,
            "provider": provider,
        }

        mails.append(mail)
        logger.info(f"[Muaview] saved mail: {email}")

        time.sleep(1)

    return {
        "status": "success" if mails else "error",
        "message": f"Đã mua {len(mails)} email(s).",
        "mails": mails
    }


def buy_mail_muaview_that(employee, service_id, quality: int = 1):
    provider = "muaview_that"
    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["buy"]

    mails = []

    logger.info(f"service_id: {service_id}")

    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider,
        defaults={"base_url": conf["base_url"], "api_key": conf["key"]},
    )

    for i in range(quality):
        print("------------i: ", i)

        params = {
            "apikey": conf["key"],
            "service": service_id
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            logger.info(f"[Muaview][Buy][{i+1}/{quality}] response: {data}")
        except Exception as e:
            logger.error(f"Lỗi khi gọi API Muaview: {e}")
            continue

        result = data.get("data", {})
        order_id = result.get("orderid")
        email = result.get("email")

        if not order_id or not email:
            logger.error(f"[Muaview] response thiếu dữ liệu: {result}")
            continue

        # -------- 1️⃣ SAVE TRANSACTION --------
        purchase = MailTransaction.objects.create(
            provider=provider_obj,
            employee=employee,
            product_id=str(service_id),
            product_name=result.get("service_name", f"Service {service_id}"),
            quantity=1,
            total_price=None,
            trans_id=order_id,     # ❗ 1 order = 1 transaction
            status="success",
            raw_response=result,
        )

        # -------- 2️⃣ SAVE PURCHASED MAIL --------
        PurchasedMail.objects.create(
            purchase=purchase,
            email=email,
            password="",
            refresh_token="",
            client_id=order_id,
            provider=provider,
            is_used=False
        )

        mail = {
            "email": email,
            "password": "",
            "refresh_token": "",
            "client_id": order_id,
            "provider": provider,
        }

        mails.append(mail)
        logger.info(f"[Muaview] saved mail: {email}")

        time.sleep(1)

    return {
        "status": "success" if mails else "error",
        "message": f"Đã mua {len(mails)} email(s).",
        "mails": mails
    }

def buy_mail_shopgmail(employee, service_id, quality: int = 1):
    provider = "shopgmail"
    conf = API_CONFIG[provider]
    url = conf["base_url"] + conf["endpoints"]["buy"]

    mails = []

    provider_obj, _ = MailProvider.objects.get_or_create(
        name=provider,
        defaults={"base_url": conf["base_url"], "api_key": conf["key"]},
    )

    logger.info(f"service_id: {service_id}")

    for i in range(quality):
        params = {
            "apikey": conf["key"],
            "service": service_id
        }

        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            logger.info(f"[shopgmail][Buy][{i+1}/{quality}] response: {data}")
        except Exception as e:
            logger.error(f"Lỗi khi gọi API shopgmail: {e}")
            continue

        result = data.get("data", {})
        order_id = result.get("orderid")
        email = result.get("email")

        if not order_id or not email:
            logger.error(f"[shopgmail] response thiếu dữ liệu: {result}")
            continue

        # -------- 1️⃣ SAVE TRANSACTION --------
        purchase = MailTransaction.objects.create(
            provider=provider_obj,
            employee=employee,
            product_id=str(service_id),
            product_name=result.get("service", f"Service {service_id}"),
            quantity=1,
            total_price=None,
            trans_id=order_id,        # ❗ mỗi order 1 transaction
            status="success",
            raw_response=result,
        )

        # -------- 2️⃣ SAVE PURCHASED MAIL --------
        purchased_mail = PurchasedMail.objects.create(
            purchase=purchase,
            email=email,
            password="",
            refresh_token="",
            client_id=order_id,
            provider=provider,
            is_used=False
        )

        mail = {
            "email": email,
            "password": "",
            "refresh_token": "",
            "client_id": order_id,
            "provider": provider,
        }

        mails.append(mail)
        logger.info(f"[shopgmail] saved mail: {email}")

        time.sleep(1)

    return {
        "status": "success" if mails else "error",
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

    if provider == "muaview_that":
        url = API_CONFIG["muaview_that"]["base_url"] + API_CONFIG["muaview_that"]["endpoints"]["otp"]
        params = {
            "apikey": API_CONFIG["muaview_that"]["key"],
            "order_id": client_id,   # client_id chính là order_id
        }
        logger.info(f"client_id: {client_id}")
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
        except Exception as e:
            logger.error(f"muaview_that OTP error: {e}")
            return {"status": "error", "message": "Không kết nối được muaview_that"}

        result = data.get("data", {}) or {}
        otp = result.get("otp")

        return {
            "status": "success" if otp else "pending",
            "provider": "muaview_that",
            "email": result.get("email") or email,
            "auth_code": otp or "",
            "from": "",
            "subject": "",
            "date": "",
        }

    if provider == "shopgmail":
        url = API_CONFIG["shopgmail"]["base_url"] + API_CONFIG["shopgmail"]["endpoints"]["otp"]
        params = {
            "apikey": API_CONFIG["shopgmail"]["key"],
            "orderid": client_id,   # client_id chính là order_id
        }
        logger.info(f"client_id: {client_id}")
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
        except Exception as e:
            logger.error(f"shopgmail OTP error: {e}")
            return {"status": "error", "message": "Không kết nối được shopgmail"}

        result = data.get("data", {}) or {}
        otp = result.get("otp")

        return {
            "status": "success" if otp else "pending",
            "provider": "muaview_that",
            "email": result.get("email") or email,
            "auth_code": otp or "",
            "from": "",
            "subject": "",
            "date": "",
        }


    if provider in ("sellmmo", "dongvan"):
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

        latest_msg = max(
            messages_with_code,
            key=lambda x: parse_mail_date(x.get("date", ""))
        )

        return {
            "status": "success",
            "provider": provider,
            "email": data.get("email") or email,
            "auth_code": latest_msg.get("code"),
            "from": latest_msg.get("from"),
            "subject": latest_msg.get("subject"),
            "date": latest_msg.get("date"),
        }
    else:
        return {"status": "error", "message": f"Dịch vụ không hỗ trợ ."}