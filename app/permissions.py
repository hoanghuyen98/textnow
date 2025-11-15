# permissions.py
from rest_framework import permissions
from logzero import logger

def get_user_role(user):
    """Trả về role hiện tại của user."""
    if hasattr(user, "employee_profile"):
        return user.employee_profile.role
    elif hasattr(user, "customer_profile"):
        return "customer"
    return "guest"


class RoleRequiredPermission(permissions.BasePermission):
    """
    ✅ Kiểm tra role của user theo view.allowed_roles
    """
    message = "Bạn không có quyền truy cập API này."

    def has_permission(self, request, view):
        # Chưa đăng nhập
        if not request.user or not request.user.is_authenticated:
            self.message = "Bạn cần đăng nhập để truy cập API này."
            return False

        user_role = get_user_role(request.user)
        logger.info(f'user_role: {user_role}')
        allowed_roles = getattr(view, "allowed_roles", [])

        # Nếu không giới hạn role nào → cho phép luôn
        if not allowed_roles:
            return True

        # Nếu role không nằm trong danh sách cho phép
        if user_role not in allowed_roles:
            self.message = f"Không có quyền truy cập API này."
            return False

        return True