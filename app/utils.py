import re, shlex, json, requests
from datetime import datetime, timezone
from logzero import logger
from bs4 import BeautifulSoup

try:
    import curlconverter
    HAS_CONVERTER = True
except Exception:
    HAS_CONVERTER = False
import time


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


def run_curl(curl_text):
    c = strip_proxy(curl_text)
    p = parse_curl(c)
    if not p["url"]:
        return {"error": "No URL found"}

    h, d = p["headers"], p["data"]
    try:
        if d and "application/json" in h.get("Content-Type", ""):
            try:
                resp = requests.request(p["method"], p["url"], json=json.loads(d), headers=h)
            except Exception:
                resp = requests.request(p["method"], p["url"], data=d, headers=h)
        else:
            resp = requests.request(p["method"], p["url"], data=d, headers=h)
    except Exception as e:
        return {"error": str(e)}

    try:
        body = resp.json()
    except Exception:
        body = resp.text
        logger.info(f"run_curl_body: {body}")
    return {"status": resp.status_code, "headers": dict(resp.headers), "body": body}


def run_curl_with_retry(batch_cmd: str, retries: int = 3, delay: float = 1.0):
    """
    Gọi run_curl(batch_cmd) tối đa 3 lần.
    Nếu bất kỳ lần nào trả về status < 400 → coi như live.
    Nếu lỗi hoặc status >= 400 → thử lại tối đa 3 lần.
    """
    for attempt in range(1, retries + 1):
        try:
            result = run_curl(batch_cmd)

            # Nếu result rỗng → retry
            if not result:
                logger.warning(f"[Retry {attempt}] Empty result")
                time.sleep(delay)
                continue

            # Nếu có field error → retry
            if "error" in result:
                logger.warning(f"[Retry {attempt}] Error: {result.get('error')}")
                time.sleep(delay)
                continue

            # Nếu status >= 400 → retry
            if result.get("status", 500) >= 400:
                logger.warning(f"[Retry {attempt}] Status >=400: {result.get('status')}")
                time.sleep(delay)
                continue

            # ➜ Thành công
            logger.info(f"[Retry {attempt}] CURL thành công → LIVE")
            return True

        except Exception as e:
            logger.error(f"[Retry {attempt}] Exception: {e}")
            time.sleep(delay)

    # ➜ Sau 3 lần vẫn thất bại
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
    Gửi tin nhắn qua API Pinger (/2.2/message).
    - message_curl: cURL mẫu lưu trong DB (PhoneAccount.message)
    - to_number: số điện thoại người nhận (dạng chuỗi số, ví dụ "18573675730")
    - text: nội dung tin nhắn (bắt buộc nếu không có ảnh)
    - media_url: URL ảnh (nếu có)
    - link_url: link đính kèm (nếu có)
    """

    # --- Parse cURL (loại bỏ proxy, trích headers/url/body)
    parsed = parse_curl(strip_proxy(message_curl))
    msg_url = parsed.get("url")
    headers = parsed.get("headers", {})
    raw_data = parsed.get("data", "")

    # --- Parse JSON gốc trong cURL body
    try:
        body = json.loads(raw_data) if raw_data else {}
    except json.JSONDecodeError:
        body = {}

    # --- Ghi đè nội dung gửi
    body["text"] = text or " "
    body["to"] = [{
        "name": name,
        "TN": to_number
    }]
    logger.info(f'send_pinger_message_body: {body}')
    if media_url:
        body["media"] = {"image": media_url}
    if link_url:
        body["link"] = {"url": link_url}

    # --- Gửi request thực
    try:
        resp = requests.post(msg_url, headers=headers, json=body, timeout=30)
        logger.info(f'resp: {resp}')
    except requests.RequestException as e:
        return {"status": "error", "message": f"network_error {str(e)}"}

    # --- Xử lý kết quả trả về
    try:
        result = resp.json()
        logger.info(f'result: {result}')
    except Exception:
        result = resp.text

    # --- Nếu có errNo thì fail ---
    if isinstance(result, dict) and "errNo" in result:
        return {
            "status": "error",
            "status_code": resp.status_code,
            "message": result.get("errMsg"),
            "response": result,
            "body_sent": body,
        }

    # --- Nếu HTTP lỗi ---
    if resp.status_code >= 400:
        return {
            "status": "error",
            "status_code": resp.status_code,
            "message": f"HTTP Error {resp.status_code}",
            "response": result,
            "body_sent": body,
        }

    # --- Thành công ---
    return {
        "status": "status",
        "status_code": resp.status_code,
        "response": result,
        "message": "Image message sent successfully.",
        "body_sent": body,
    }
