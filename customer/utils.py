import re, shlex, json, requests

try:
    import curlconverter
    HAS_CONVERTER = True
except Exception:
    HAS_CONVERTER = False


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
    """
    Xoá phần `--proxy` và ký tự '\' ngay trước nó trong chuỗi curl.
    Ví dụ:
        --proxy http://localhost:9495
        hoặc  \ --proxy 'http://localhost:9495'
    """
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
    return {"status": resp.status_code, "headers": dict(resp.headers), "body": body}


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

    if media_url:
        body["media"] = {"image": media_url}
    if link_url:
        body["link"] = {"url": link_url}

    # --- Gửi request thực
    try:
        resp = requests.post(msg_url, headers=headers, json=body, timeout=30)
        print('resp: ', resp)
    except requests.RequestException as e:
        return {"status": "error", "message": f"network_error {str(e)}"}

    # --- Xử lý kết quả trả về
    try:
        result = resp.json()
        print('result: ', result)
    except Exception:
        result = resp.text

    # --- Nếu có errNo thì fail ---
    if isinstance(result, dict) and "errNo" in result:
        print("????????")
        return {
            "status": "error",
            "status_code": resp.status_code,
            "message": result.get("errMsg"),
            "response": result,
            "body_sent": body,
        }

    # --- Nếu HTTP lỗi ---
    if resp.status_code >= 400:
        print("tttttt")
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
        "message": "Gửi ảnh thành công",
        "body_sent": body,
    }
