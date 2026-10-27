"""Authentication context models and dependency injection for security enforcement."""
from typing import Set, Optional
from pydantic import BaseModel, Field, ConfigDict
from fastapi import Header, HTTPException, status


class AuthContext(BaseModel):
    """
    Context xác thực người dùng:
    - Bắt buộc là nguồn duy nhất xác định quyền truy cập dự án (allowed_project_codes).
    - Tuyệt đối không tin tưởng bất kỳ project_code nào gửi từ request body.
    """
    user_id: str
    username: Optional[str] = None
    role: str = "engineer"
    allowed_project_codes: Set[str] = Field(default_factory=set)

    model_config = ConfigDict(extra="forbid")


def get_auth_context(
    x_user_id: Optional[str] = Header(default=None),
    x_allowed_projects: Optional[str] = Header(default=None),
) -> AuthContext:
    """
    Dependency lấy context xác thực:
    - Bắt buộc phải có X-User-Id, nếu thiếu lập tức trả về HTTP 401 Unauthorized.
    - X-Allowed-Projects parse danh sách dự án; nếu thiếu hoặc rỗng, allowed_project_codes = set() (fail-closed).
    - Tuyệt đối không có default credentials/projects.
    """
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực: Thiếu thông tin User ID trong header.",
        )

    projects_set = set()
    if x_allowed_projects and x_allowed_projects.strip():
        projects_set = {p.strip() for p in x_allowed_projects.split(",") if p.strip()}

    return AuthContext(
        user_id=x_user_id.strip(),
        role="engineer",
        allowed_project_codes=projects_set,
    )
