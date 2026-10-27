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
    - Server truy vấn trực tiếp bảng project_members.
    - Frontend hoàn toàn không có quyền khai báo allowed_project_codes.
    """
    def get_allowed_projects(self, user_id: str) -> Set[str]:
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

    def get_allowed_projects(self, user_id: str) -> Set[str]:
        return set(self._mapping.get(user_id, set()))

    def set_user_projects(self, user_id: str, projects: Set[str]) -> None:
        self._mapping[user_id] = set(projects)


class SupabaseProjectMembershipProvider:
    """
    Adapter tra cứu bảng project_members thực tế từ Supabase qua ReadOnlyDataClient:
    - Thực hiện query: select_project_members(user_id)
    - Bảo đảm an toàn fail-closed: lỗi mạng hoặc không tìm thấy user -> trả về set() rỗng.
    """
    def __init__(self, client: ReadOnlyDataClient):
        self._client = client

    def get_allowed_projects(self, user_id: str) -> Set[str]:
        if not user_id or not user_id.strip():
            return set()

        try:
            # Tra cứu từ bảng project_members qua protocol client
            rows = self._client.select_project_members(user_id=user_id.strip())
            if not rows:
                return set()

            return {str(r.get("project_code")) for r in rows if r.get("project_code")}
        except Exception as e:
            logger.error(f"Lỗi khi tra cứu project_members cho user {user_id}: {e}")
            # Fail-closed: Khi database gặp sự cố, tuyệt đối không cấp quyền bừa bãi
            return set()
