from rest_framework.throttling import SimpleRateThrottle

class IPGlobalThrottle(SimpleRateThrottle):
    """
    ✅ Chặn flood theo IP (bất kể user nào)
    Ví dụ: nếu một IP gửi quá 200 request/phút thì bị khóa tạm thời.
    """
    scope = 'ip_global'

    def get_cache_key(self, request, view):
        # Dùng địa chỉ IP của client làm khóa throttle
        return self.get_ident(request)
