"""
Membership lookup service for server-side project authorization.
Zero trust on frontend claims. Only trusted sources determine project access.
"""
from typing import Protocol, Set, Dict, Optional, runtime_checkable
import logging

from titsmart_ai.adapters.supabase_adapter import ReadOnlyDataClient

logger = logging.getLogger(__name__)


@runtime_checkable
class ProjectMembershipProvider(Protocol):
    """
    Protocol trừu tượng tra cứu quyền dự án của user từ server-side DB/Store:
    - user_id được lấy từ verified JWT sub.
    - access_token: JWT của chính user để chuyển tiếp xuống Supabase PostgREST client,
      bảo đảm database RLS kích hoạt đúng auth.uid() = user_id.
    - Server truy vấn trực tiếp bảng project_members dưới context user.
    - Frontend hoàn toàn không có quyền khai báo allowed_project_codes.
    """
    def get_allowed_projects(self, user_id: str, access_token: Optional[str] = None) -> Set[str]:
        ...


class InMemoryProjectMembershipProvider:
    """
    Hiện thực tra cứu quyền trong bộ nhớ (phục vụ test, offline, mock).
    """
    def __init__(self, mapping: Optional[Dict[str, Set[str]]] = None):
        self._mapping: Dict[str, Set[str]] = dict(mapping or {
            "engineer_01": {"TITS-01", "TITS-02"},
            "engineer_tits01": {"TITS-01"},
            "engineer_tits02": {"TITS-02"},
            "admin_user": {"TITS-01", "TITS-02", "DA-01", "TRAM_BIEN_AP_500KV"},
        })

    def get_allowed_projects(self, user_id: str, access_token: Optional[str] = None) -> Set[str]:
        return set(self._mapping.get(user_id, set()))

    def set_user_projects(self, user_id: str, projects: Set[str]) -> None:
        self._mapping[user_id] = set(projects)


class SupabaseProjectMembershipProvider:
    """
    Adapter tra cứu bảng project_members thực tế từ Supabase qua ReadOnlyDataClient:
    - Nhận access_token của user để query với header Authorization: Bearer <user_jwt>,
      cho phép PostgreSQL Row Level Security (RLS) áp dụng chính xác auth.uid() = user_id.
    - Ghi log tường minh phân biệt giữa:
        1) User không có dự án nào (Normal ACL empty).
        2) Database gặp sự cố mạng / timeout (Fail-closed due to DB error).
    - Bảo đảm an toàn tuyệt đối: Không tiết lộ token/secret trong log.
    """
    def __init__(self, client: ReadOnlyDataClient):
        self._client = client

    def get_allowed_projects(self, user_id: str, access_token: Optional[str] = None) -> Set[str]:
        if not user_id or not user_id.strip():
            logger.warning("[AUTH_MEMBERSHIP] user_id rỗng, từ chối cấp quyền.")
            return set()

        clean_uid = user_id.strip()
        try:
            # Tra cứu bảng project_members.
            # Client hỗ trợ truyền access_token để RLS thực thi auth.uid()
            rows = self._client.select_project_members(user_id=clean_uid, access_token=access_token)
            if not rows:
                logger.info(f"[AUTH_MEMBERSHIP] User '{clean_uid}' không thuộc dự án nào trong hệ thống (ACL empty).")
                return set()

            allowed = {str(r.get("project_code")) for r in rows if r.get("project_code")}
            logger.info(f"[AUTH_MEMBERSHIP] Tra cứu thành công: User '{clean_uid}' có quyền trên {len(allowed)} dự án.")
            return allowed
        except Exception as e:
            # Phân biệt rõ sự cố database với trường hợp user không có quyền
            logger.error(f"[SECURITY_ALERT][DB_OUTAGE] Tra cứu project_members thất bại cho user '{clean_uid}' do lỗi database: {type(e).__name__}. Áp dụng fail-closed.")
            # Fail-closed: Khi database gặp sự cố, tuyệt đối không cấp quyền
            return set()
