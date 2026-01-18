import re, shlex, json, requests
from datetime import datetime, timezone
from logzero import logger
from bs4 import BeautifulSoup
import subprocess
import os

PROXY_US = os.environ.get('PROXY_US')
logger.info(PROXY_US)
try:
    import curlconverter
    HAS_CONVERTER = True
except Exception:
    HAS_CONVERTER = False
import time


def parse_mail_date(date_str: str):
    """
    "21:59 - 17/01/2026" → datetime
    """
    try:
        return datetime.strptime(date_str.strip(), "%H:%M - %d/%m/%Y")
    except Exception:
        return datetime.min

def to_utc_isoformat(t):
    """
    Chuyển '2025-11-10 04:33:25.871598' → '2025-11-10T04:33:25Z'
    """
    try:
        dt = parse_time(t)
        if dt == datetime.min:
            return t
        # Gán timezone UTC
        dt = dt.replace(tzinfo=timezone.utc)
        # Bỏ microsecond, chỉ giữ tới giây
        dt = dt.replace(microsecond=0)
        # Xuất ra ISO 8601 UTC (đuôi Z)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return t

def parse_time(t):
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M:%S.%f")
    except Exception:
        return datetime.min

def normalize_phone_number(raw_number: str):
    """
    Chuẩn hóa số điện thoại người nhận từ các định dạng khác nhau.
    Ví dụ:
        (629) 234-3458 → to_number=16292343458, name=(629) 234-3458
        6292343458     → to_number=16292343458, name=(629) 234-3458
        16292343458    → to_number=16292343458, name=(629) 234-3458
    """
    if not raw_number:
        return None, None

    # 🔹 Lấy toàn bộ chữ số (loại bỏ (), -, space, ...)
    digits = re.sub(r'\D', '', raw_number)

    # 🔹 Kiểm tra độ dài hợp lệ
    if len(digits) == 10:
        # Thiếu số 1 ở đầu → thêm vào
        digits = '1' + digits
    elif len(digits) == 11 and digits.startswith('1'):
        # Đã hợp lệ → giữ nguyên
        pass
    else:
        # Không hợp lệ
        return None, None

    # 🔹 Tạo chuỗi name dạng (AAA) BBB-CCCC
    area = digits[1:4]
    mid = digits[4:7]
    last = digits[7:]
    name = f"({area}) {mid}-{last}"

    return digits, name

def extract_auth_code(html_content: str) -> str | None:
    """
    Trích mã xác minh (4–8 chữ số) từ nội dung HTML email.
    - Ưu tiên vùng có chứa "code", "verify", "xác minh"
    - Bỏ qua các số trong CSS, màu (#fff), px, %, rgba,...
    """
    if not html_content:
        return None

    # 🔹 Cắt vùng có chứa "code" / "verify" / "xác minh" (nếu có)
    match_section = re.search(r"(?is)(.{0,200}(code|verify|xác minh).{0,200})", html_content)
    snippet = match_section.group(0) if match_section else html_content

    # 🔹 Bước 1: tìm dãy số 4–8 chữ số gần từ khóa code/verify/xác minh
    match = re.search(r"(?i)(?:code|verify|xác minh)[^0-9]{0,20}(\d{4,8})", snippet)
    if match:
        return match.group(1)

    # 🔹 Bước 2: fallback – tìm trong các thẻ HTML (b, strong, span, p, div)
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup.find_all(["b", "strong", "span", "p", "div"]):
            text = tag.get_text(strip=True)
            # Bỏ qua số trong định dạng style
            if not text or re.search(r"(px|rgb|rgba|#|%)", text):
                continue
            if re.fullmatch(r"\d{4,8}", text):
                return text
    except Exception as e:
        logger.warning(f"Lỗi BeautifulSoup khi parse HTML: {e}")

    return None

def replace_proxy(c: str, new_proxy: str) -> str:
    if not c:
        return c

    # Thay thế proxy cũ bằng proxy mới
    c = re.sub(
        r"(\\\s*)?--proxy(?:=)?\s*['\"]?[^ \n\r'\"]+['\"]?",
        f"--proxy {new_proxy}",
        c,
        flags=re.IGNORECASE
    )

    # Dọn whitespace dư
    c = re.sub(r"\\\s*\n", " ", c)
    c = re.sub(r"\s{2,}", " ", c).strip()
    return c

def strip_proxy(c: str) -> str:

    if not c:
        return c

    # 1️⃣ Xóa dấu '\' + khoảng trắng + --proxy ... (có hoặc không dấu =, có hoặc không ngoặc)
    c = re.sub(
        r"(\\\s*)?--proxy(?:=)?\s*['\"]?[^ \n\r'\"]+['\"]?",
        "",
        c,
        flags=re.IGNORECASE
    )

    # 2️⃣ Dọn khoảng trắng, dòng trống, tránh lỗi escape
    c = re.sub(r"\\\s*\n", " ", c)  # bỏ '\' + xuống dòng
    c = re.sub(r"\s{2,}", " ", c).strip()

    return c



def parse_curl(c):
    if HAS_CONVERTER and hasattr(curlconverter, "parse"):
        try:
            p = curlconverter.parse(c)
            return {"method": p.get("method", "GET"), "url": p.get("url"),
                    "headers": p.get("headers", {}), "data": p.get("data")}
        except Exception:
            pass

    t = shlex.split(c)
    m, u, h, d = "GET", None, {}, None
    i = 0
    while i < len(t):
        if t[i] == "curl" and i + 1 < len(t): u = t[i + 1].strip("'\"")
        elif t[i] == "-X" and i + 1 < len(t): m = t[i + 1].upper()
        elif t[i] == "-H" and i + 1 < len(t):
            k, v = t[i + 1].split(":", 1); h[k.strip()] = v.strip().strip("'\"")
        elif t[i].startswith("--data") or t[i] == "-d":
            d = t[i + 1].strip("'\"") if i + 1 < len(t) else None
        elif t[i].startswith("http"): u = t[i].strip("'\"")
        i += 1
    h.pop("Host", None)
    return {"method": m, "url": u, "headers": h, "data": d}


def run_curl(curl_text):
    # Thay thế proxy trong curl
    curl_text = replace_proxy(curl_text, PROXY_US)
    # Parse curl
    p = parse_curl(curl_text)
    if not p["url"]:
        return {"error": "No URL found"}

    proxy = {
        "http": PROXY_US,
        "https": PROXY_US,
    }
    logger.info('-----------------')
    logger.info(proxy)
    h, d = p["headers"], p["data"]

    try:
        if d and "application/json" in h.get("Content-Type", ""):
            try:
                resp = requests.request(
                    p["method"], p["url"], 
                    json=json.loads(d), headers=h, proxies=proxy
                )
            except Exception:
                resp = requests.request(
                    p["method"], p["url"], 
                    data=d, headers=h, proxies=proxy
                )
        else:
            resp = requests.request(
                p["method"], p["url"], 
                data=d, headers=h, proxies=proxy
            )

    except Exception as e:
        return {"error": str(e)}

    try:
        body = resp.json()
    except Exception:
        body = resp.text

    # -------------------------------
    # 1) Lỗi: body là string (VD: Bad credentials)
    # -------------------------------
    if isinstance(body, str):
        return {
            "status": "error",
            "message": body.strip()
        }
    # -------------------------------
    # 2) Validate định dạng Pinger tiêu chuẩn
    # body phải có: success + result(list)
    # -------------------------------
    if not isinstance(body, dict):
        return {"status": "error", "message": "Invalid response format (not dict)"}

    if "success" not in body:
        return {"status": "error", "message": "Missing 'success' in response"}

    if "result" not in body:
        return {"status": "error", "message": "Missing 'result' in response"}

    if not isinstance(body["result"], list):
        return {"status": "error", "message": "'result' must be a list"}

    # Validate từng item trong result
    for i, item in enumerate(body["result"]):
        if not isinstance(item, dict):
            return {"status": "error", "message": f"result[{i}] is not a dict"}

        for key in ["httpResponseCode", "contentType", "body"]:
            if key not in item:
                return {
                    "status": "error",
                    "message": f"Missing '{key}' in result[{i}]"
                }

    # -------------------------------
    # 3) Kiểm tra lỗi cấp 2: errNo / errMsg trong từng body JSON
    # -------------------------------
    for item in body.get("result", []):
        raw = item.get("body")
        if not raw:
            continue

        try:
            parsed = json.loads(raw)
        except:
            continue

        if "errNo" in parsed or "errMsg" in parsed:
            return {
                "status": "error",
                "message": parsed.get("errMsg", "Unknown error"),
                "code": parsed.get("errNo")
            }

    # -------------------------------
    # 4) Không lỗi → success
    # -------------------------------
    return {
        "status": "success",
        "body": body
    }


def run_curl_with_retry(batch_cmd: str, retries: int = 2, delay: float = 1.0):
    """
    Gọi run_curl(batch_cmd) tối đa 3 lần.
    Nếu bất kỳ lần nào trả về status < 400 → coi như live.
    Nếu lỗi hoặc status >= 400 → thử lại tối đa 3 lần.
    """
    print("??????????????????")
    for attempt in range(1, retries + 1):
        try:
            result = run_curl(batch_cmd)

            # Nếu result rỗng
            if not result:
                logger.warning(f"[Retry {attempt}] Empty result")
                time.sleep(delay)
                continue

            # Nếu có trường "error"
            if "error" in result:
                logger.warning(f"[Retry {attempt}] Error: {result.get('error')}")
                time.sleep(delay)
                continue

            # -------------------------
            # FIX: Chuẩn hóa status_code
            # -------------------------
            raw_status = result.get("status")

            if raw_status == "success":
                status_code = 200
            elif raw_status == "error":
                status_code = 500
            else:
                try:
                    status_code = int(raw_status)
                except (TypeError, ValueError):
                    status_code = 500

            # Nếu status lỗi ≥ 400 → retry
            if status_code >= 400:
                logger.warning(f"[Retry {attempt}] Status >=400: {status_code}")
                time.sleep(delay)
                continue

            # Thành công
            logger.info(f"[Retry {attempt}] CURL thành công → LIVE")
            return True

        except Exception as e:
            logger.error(f"[Retry {attempt}] Exception: {e}")
            time.sleep(delay)

    # Sau 3 lần retry thất bại
    logger.error("[Retry] Tất cả retry đều thất bại → DIE")
    return False


def send_pinger_message(
    message_curl: str,
    to_number: str,
    text: str = "",
    media_url: str = None,
    link_url: str = None,
    name: str = None,
):
    """
    Gửi tin nhắn qua API Pinger bằng CURL mẫu nhưng override proxy.
    """

    # 1) Thay proxy trong curl = proxy của bạn
    message_curl = replace_proxy(message_curl, PROXY_US)

    # 2) Parse curl (headers, url, body)
    parsed = parse_curl(message_curl)
    msg_url = parsed.get("url")
    headers = parsed.get("headers", {})
    raw_data = parsed.get("data", "")

    # 3) Parse JSON gốc
    try:
        body = json.loads(raw_data) if raw_data else {}
    except json.JSONDecodeError:
        body = {}

    # 4) Ghi đè nội dung gửi
    body["text"] = text or " "
    body["to"] = [{
        "name": name,
        "TN": to_number
    }]

    # Ghi log để debug
    logger.info(f'send_pinger_message_body: {body}')

    if media_url:
        body["media"] = {"image": media_url}
    if link_url:
        body["link"] = {"url": link_url}

    # 5) Proxy config (luôn dùng proxy của bạn)
    proxy_cfg = {
        "http": PROXY_US,
        "https": PROXY_US,
    }

    # 6) Gửi request thật
    try:
        resp = requests.post(
            msg_url,
            headers=headers,
            json=body,
            proxies=proxy_cfg, 
            timeout=30
        )
        logger.info(f'resp: {resp}')
    except requests.RequestException as e:
        return {"status": "error", "message": f"network_error {str(e)}"}

    # 7) Parse response
    try:
        result = resp.json()
        logger.info(f'result: {result}')
    except Exception:
        result = resp.text

    # 8) Lỗi từ server Pinger
    if isinstance(result, dict) and "errNo" in result:
        return {
            "status": "error",
            "status_code": resp.status_code,
            "message": result.get("errMsg"),
            "response": result,
            "body_sent": body,
        }

    # 9) Lỗi HTTP
    if resp.status_code >= 400:
        return {
            "status": "error",
            "status_code": resp.status_code,
            "message": f"HTTP Error {resp.status_code}",
            "response": result,
            "body_sent": body,
        }

    # 10) Thành công
    return {
        "status": "success",
        "status_code": resp.status_code,
        "response": result,
        "message": "Message sent successfully.",
        "body_sent": body,
    }


def upload_pinger_media(curl_text: str, file):
    """
    Upload ảnh qua Pinger Media API bằng cURL mẫu + override proxy.
    """

    # 1) Thay proxy trong curl
    curl_text = replace_proxy(curl_text, PROXY_US)

    # 2) Parse curl
    parsed = parse_curl(curl_text)
    url = parsed.get("url")
    headers = parsed.get("headers", {}) or {}
    headers.pop("Host", None)

    # 3) Chuẩn hóa headers để upload binary file
    mime_type = file.content_type or "application/octet-stream"
    headers.update({
        "Content-Type": mime_type,
        "Upload-Incomplete": "?0",
        "Upload-Draft-Interop-Version": "3",
        "Content-Encoding": "binary",
        "Accept": "*/*",
    })
    for h in ["Accept-Encoding", "Transfer-Encoding", "Content-Length"]:
        headers.pop(h, None)

    proxy_cfg = {"http": PROXY_US, "https": PROXY_US}

    # 4) Upload file
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=file.file,
            proxies=proxy_cfg,
            timeout=60
        )
    except Exception as e:
        logger.error(f"Media upload failed: {str(e)}")
        return None, "upload_failed"

    # 5) Parse response JSON
    try:
        data = resp.json()
    except:
        data = {}

    uploaded_url = (
        data.get("url")
        or data.get("result", {}).get("url")
        or data.get("result", {}).get("image")
        or data.get("result", {}).get("media", {}).get("url")
    )

    if not uploaded_url or not str(uploaded_url).startswith("http"):
        return None, "invalid_url"

    return uploaded_url, None