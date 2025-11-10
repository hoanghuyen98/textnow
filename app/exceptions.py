    # app/exceptions.py
from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_exception_handler
from rest_framework import status as http_status


# ===== A. Các Exception tiện dụng =====
class AppAPIException(APIException):
    status_code = http_status.HTTP_400_BAD_REQUEST
    default_detail = "Đã xảy ra lỗi."
    default_code = "error"

    def __init__(self, message=None, status_code=None, data=None):
        """
        message: chuỗi lỗi hiển thị
        status_code: HTTP status (mặc định 400)
        data: payload bổ sung (ví dụ errors chi tiết)
        """
        if status_code is not None:
            self.status_code = status_code

        # DRF sẽ serialize self.detail -> JSON
        self.detail = {
            "status": "error",
            "message": message or self.default_detail
        }
        if data is not None:
            # ví dụ {"field": ["err1", "err2"]} hoặc bất kỳ thông tin bổ sung nào
            self.detail["errors"] = data


class BadRequest(AppAPIException):
    status_code = http_status.HTTP_400_BAD_REQUEST


class Unauthorized(AppAPIException):
    status_code = http_status.HTTP_401_UNAUTHORIZED


class Forbidden(AppAPIException):
    status_code = http_status.HTTP_403_FORBIDDEN


class NotFound(AppAPIException):
    status_code = http_status.HTTP_404_NOT_FOUND


class Conflict(AppAPIException):
    status_code = http_status.HTTP_409_CONFLICT


class TooManyRequests(AppAPIException):
    status_code = http_status.HTTP_429_TOO_MANY_REQUESTS


# ===== B. Exception handler để đồng bộ format toàn hệ thống (khuyến nghị) =====
def custom_exception_handler(exc, context):
    """
    - Ưu tiên: nếu bạn raise các AppAPIException ở trên -> giữ nguyên {status, message, errors?}
    - Nếu là ValidationError / PermissionDenied / NotAuthenticated... -> chuẩn hoá về format chung
    """
    response = drf_exception_handler(exc, context)

    if response is None:
        # Không phải lỗi do DRF biết; để mặc định (500) hoặc tự bọc nếu cần
        return response

    # Nếu đã là AppAPIException: detail đã đúng format -> trả nguyên
    if isinstance(exc, AppAPIException):
        return response

    # Các lỗi DRF mặc định (ValidationError, NotAuthenticated, PermissionDenied, v.v.)
    # thường trả về dạng {"detail": "..."} hoặc dict field->list
    data = response.data

    # Trường hợp {"detail": "..."} -> chuẩn hóa
    if isinstance(data, dict) and "detail" in data and isinstance(data["detail"], str):
        response.data = {
            "status": "error",
            "message": data["detail"]
        }
        return response

    # Trường hợp ValidationError: dict field->list -> gom lại
    if isinstance(data, dict):
        # cố gắng lấy message ngắn gọn đầu tiên
        first_msg = None
        for v in data.values():
            if isinstance(v, (list, tuple)) and v:
                first_msg = str(v[0])
                break
            if isinstance(v, str):
                first_msg = v
                break

        response.data = {
            "status": "error",
            "message": first_msg or "Dữ liệu không hợp lệ.",
            "errors": data  # giữ chi tiết cho FE nếu muốn hiển thị field-level
        }
        return response

    # Fallback
    response.data = {
        "status": "error",
        "message": "Đã xảy ra lỗi."
    }
    return response
