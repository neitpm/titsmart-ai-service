"""Authentication context models and dependency injection for security enforcement."""
from typing import Set, Optional
from pydantic import BaseModel, Field, ConfigDict
from fastapi import Header, HTTPException, status, Depends
import jwt

from titsmart_ai.config import settings
from titsmart_ai.security.membership import ProjectMembershipProvider, InMemoryProjectMembershipProvider


class AuthContext(BaseModel):
    """
    Context xác thực người dùng:
    - Bắt buộc là nguồn duy nhất xác định quyền truy cập dự án (allowed_project_codes).
    - Quyền dự án BẮT BUỘC được nạp từ server-side lookup (hoặc verified JWT claims).
    - Tuyệt đối không nhận quyền dự án từ client request body.
    """
    user_id: str
    username: Optional[str] = None
    role: str = "engineer"
    allowed_project_codes: Set[str] = Field(default_factory=set)

    model_config = ConfigDict(extra="forbid")


# Singleton provider mặc định cho ứng dụng offline / dev
_default_membership_provider = InMemoryProjectMembershipProvider()


def get_membership_provider() -> ProjectMembershipProvider:
    return _default_membership_provider


def get_auth_context(
    authorization: Optional[str] = Header(default=None),
    x_user_id: Optional[str] = Header(default=None),
    x_allowed_projects: Optional[str] = Header(default=None),
    x_internal_secret: Optional[str] = Header(default=None),
    membership_provider: ProjectMembershipProvider = Depends(get_membership_provider),
) -> AuthContext:
    """
    Dependency lấy context xác thực đa chế độ tuân thủ bảo mật production:

    1. Production / JWT Mode (hoặc khi có Authorization Bearer token):
       - Token JWT bắt buộc hợp lệ, được ký bằng secret server.
       - user_id được lấy từ token claim ('sub' hoặc 'user_id').
       - allowed_project_codes được tra cứu từ server-side membership_provider (DB project_members).
       - Hoàn toàn KHÔNG tin tưởng client-provided headers.

    2. Local Mock Mode (CHỈ cho phép khi AUTH_MODE == 'mock' và APP_ENV != 'production'):
       - Bị cấm tuyệt đối nếu APP_ENV == 'production'.
       - Nếu settings.INTERNAL_AUTH_SECRET được cấu hình, bắt buộc header X-Internal-Secret phải khớp.
       - Cho phép reverse-proxy nội bộ hoặc test harness truyền X-User-Id và X-Allowed-Projects.
    """
    auth_mode = settings.AUTH_MODE.lower()
    app_env = settings.APP_ENV.lower()

    # Cảnh báo bảo mật: Nếu là production, cấm triệt để mock mode
    if app_env in ("production", "prod") and auth_mode == "mock":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Cấu hình hệ thống không hợp lệ: Không được bật AUTH_MODE='mock' trên production.",
        )

    # =========================================================================
    # A. CHẾ ĐỘ XÁC THỰC QUA JWT TOKEN (Bearer Token)
    # =========================================================================
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        jwt_secret = settings.JWT_SECRET_KEY or "titsmart_offline_dev_secret_key_32chars"
        try:
            decode_options = {
                "require": ["exp", "sub"],
                "verify_exp": True,
                "verify_sub": True,
            }
            decode_kwargs = {
                "algorithms": [settings.JWT_ALGORITHM],
                "options": decode_options,
            }
            if settings.JWT_ISSUER:
                decode_kwargs["issuer"] = settings.JWT_ISSUER
            if settings.JWT_AUDIENCE:
                decode_kwargs["audience"] = settings.JWT_AUDIENCE

            payload = jwt.decode(token, jwt_secret, **decode_kwargs)
            user_id = str(payload.get("sub") or payload.get("user_id") or "")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token JWT không hợp lệ: Thiếu claim 'sub' hoặc 'user_id'.",
                )

            # Lấy quyền dự án từ server-side membership lookup
            # Frontend hoàn toàn không thể tự phong quyền
            allowed_projects = membership_provider.get_allowed_projects(user_id)

            return AuthContext(
                user_id=user_id,
                role=str(payload.get("role", "engineer")),
                allowed_project_codes=allowed_projects,
            )
        except jwt.PyJWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token xác thực JWT không hợp lệ hoặc đã hết hạn: {str(e)}",
            )

    # Nếu cấu hình bắt buộc JWT mode mà client không gửi Bearer token
    if auth_mode == "jwt":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực Bearer JWT token (AUTH_MODE='jwt').",
        )

    # =========================================================================
    # B. CHẾ ĐỘ LOCAL MOCK MODE (Chỉ dùng cho Local / Test / Internal Proxy)
    # =========================================================================
    if auth_mode == "mock":
        # Kiểm tra internal secret nếu có cấu hình
        if settings.INTERNAL_AUTH_SECRET:
            if not x_internal_secret or x_internal_secret != settings.INTERNAL_AUTH_SECRET:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Từ chối truy cập: Header X-Internal-Secret không hợp lệ cho chế độ mock.",
                )

        if not x_user_id or not x_user_id.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Yêu cầu xác thực: Thiếu thông tin User ID trong header.",
            )

        user_id_clean = x_user_id.strip()

        # Nếu client mock truyền X-Allowed-Projects -> parse
        # Nếu không truyền -> fallback tra cứu từ server-side membership provider
        projects_set = set()
        if x_allowed_projects and x_allowed_projects.strip():
            projects_set = {p.strip() for p in x_allowed_projects.split(",") if p.strip()}
        else:
            projects_set = membership_provider.get_allowed_projects(user_id_clean)

        return AuthContext(
            user_id=user_id_clean,
            role="engineer",
            allowed_project_codes=projects_set,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Chế độ xác thực '{settings.AUTH_MODE}' không được hỗ trợ.",
    )
