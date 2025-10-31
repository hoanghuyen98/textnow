import re, shlex, json, requests

try:
    import curlconverter
    HAS_CONVERTER = True
except Exception:
    HAS_CONVERTER = False


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
    body["text"] = text or "📸 Ảnh được gửi từ người dùng"
    body["to"] = [{
        "name": f"({to_number[:3]}) {to_number[3:6]}-{to_number[6:]}",
        "TN": to_number
    }]

    if media_url:
        body["media"] = {"image": media_url}
    if link_url:
        body["link"] = {"url": link_url}

    # --- Gửi request thực
    try:
        resp = requests.post(msg_url, headers=headers, json=body, timeout=30)
    except requests.RequestException as e:
        return {"success": False, "error_type": "network_error", "message": str(e)}

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
            "success": False,
            "status_code": resp.status_code,
            "errNo": result.get("errNo"),
            "errMsg": result.get("errMsg"),
            "retry": result.get("retry"),
            "response": result,
            "body_sent": body,
        }

    # --- Nếu HTTP lỗi ---
    if resp.status_code >= 400:
        print("tttttt")
        return {
            "success": False,
            "status_code": resp.status_code,
            "errMsg": f"HTTP Error {resp.status_code}",
            "response": result,
            "body_sent": body,
        }

    # --- Thành công ---
    return {
        "success": True,
        "status_code": resp.status_code,
        "response": result,
        "body_sent": body,
    }
