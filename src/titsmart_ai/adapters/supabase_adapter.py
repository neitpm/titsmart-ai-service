"""ReadOnly client protocol, mapping, and Supabase adapter for staging read-only access."""
import re
import logging
from typing import Protocol, List, Optional, Dict, Any, runtime_checkable
from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.config import Settings

logger = logging.getLogger(__name__)


class DatabaseQueryError(Exception):
    """Ngoại lệ nghiệp vụ khi có lỗi truy vấn cơ sở dữ liệu hoặc timeout."""
    pass


def camel_to_snake(name: str) -> str:
    """Chuyển đổi key camelCase sang snake_case rõ ràng."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


# Bảng mapping tường minh (Explicit Mapping) cho các trường nghiệp vụ quan trọng
# Tránh rủi ro collision do generic regex (như projectID, assignedEngineerID, etc.)
EXPLICIT_FIELD_MAPPING: Dict[str, str] = {
    "projectCode": "project_code",
    "projectName": "project_name",
    "contractValue": "contract_value",
    "contractNo": "contract_no",
    "contractName": "contract_name",
    "progressPercent": "progress_percent",
    "assignedEngineerName": "assigned_engineer_name",
    "assignedEngineerId": "assigned_engineer_id",
    "assignerName": "assigner_name",
    "assignerId": "assigner_id",
    "purchaseStatus": "purchase_status",
    "constrStatus": "constr_status",
    "imagesCount": "images_count",
    "reportedTime": "reported_time",
    "receiverName": "receiver_name",
    "docStatus": "doc_status",
    "paymentStatus": "payment_status",
    "sendDate": "send_date",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
}


def normalize_record_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Chuẩn hóa trường dữ liệu:
    1. Ưu tiên tra cứu bảng mapping tường minh (EXPLICIT_FIELD_MAPPING).
    2. Fallback sang regex camel_to_snake nếu không có trong từ điển.
    """
    normalized = {}
    for k, v in row.items():
        if k in EXPLICIT_FIELD_MAPPING:
            snake_k = EXPLICIT_FIELD_MAPPING[k]
        else:
            snake_k = camel_to_snake(k)
        normalized[snake_k] = v
    return normalized


@runtime_checkable
class ReadOnlyDataClient(Protocol):
    """
    Protocol trừu tượng cho client dữ liệu chỉ đọc:
    - Chỉ cho phép select/read.
    - Không có bất kỳ phương thức insert, update, delete, drop.
    - Không nhận raw SQL chuỗi tùy ý.
    """

    def select_projects(self, project_code: Optional[str] = None) -> List[Project]:
        ...

    def select_tasks(self, project_code: Optional[str] = None) -> List[Task]:
        ...

    def select_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        ...


class SupabaseReadOnlyClient:
    """
    Adapter thực tế gọi Supabase Python Client (dùng PostgREST read-only).
    - Chỉ sử dụng trên môi trường Staging/Dev với allowlist.
    - Tuyệt đối không dùng service-role key.
    - Xử lý timeout và mapping 2 chiều giữa camelCase và snake_case.
    - Không log URL hoặc Secret.
    """

    def __init__(self, client: Any, settings: Optional[Settings] = None, timeout: float = 10.0):
        self._client = client
        self._timeout = timeout
        if settings:
            settings.validate_staging_credentials()
            self._timeout = settings.SUPABASE_REQUEST_TIMEOUT

    def select_projects(self, project_code: Optional[str] = None) -> List[Project]:
        try:
            query = self._client.table("projects").select("*")
            if project_code:
                query = query.eq("code", project_code)
            res = query.execute()
            data = res.data or []
            return [Project.model_validate(normalize_record_keys(row)) for row in data]
        except TimeoutError as e:
            logger.error("Hết thời gian chờ (Timeout) khi truy vấn bảng projects")
            raise DatabaseQueryError(f"Truy vấn bảng projects bị quá thời gian ({self._timeout}s)") from e
        except Exception as e:
            logger.error("Lỗi khi truy vấn bảng projects")
            raise DatabaseQueryError(f"Không thể truy vấn danh sách dự án: {str(e)}") from e

    def select_tasks(self, project_code: Optional[str] = None) -> List[Task]:
        try:
            query = self._client.table("tasks").select("*")
            if project_code:
                query = query.eq("project_code", project_code)
            res = query.execute()
            data = res.data or []
            return [Task.model_validate(normalize_record_keys(row)) for row in data]
        except TimeoutError as e:
            logger.error("Hết thời gian chờ (Timeout) khi truy vấn bảng tasks")
            raise DatabaseQueryError(f"Truy vấn bảng tasks bị quá thời gian ({self._timeout}s)") from e
        except Exception as e:
            logger.error("Lỗi khi truy vấn bảng tasks")
            raise DatabaseQueryError(f"Không thể truy vấn danh sách công việc: {str(e)}") from e

    def select_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        try:
            query = self._client.table("issues").select("*")
            if project_code:
                query = query.eq("project_code", project_code)
            if priority:
                query = query.eq("priority", priority)
            if status:
                query = query.eq("status", status)
            res = query.execute()
            data = res.data or []
            return [Issue.model_validate(normalize_record_keys(row)) for row in data]
        except TimeoutError as e:
            logger.error("Hết thời gian chờ (Timeout) khi truy vấn bảng issues")
            raise DatabaseQueryError(f"Truy vấn bảng issues bị quá thời gian ({self._timeout}s)") from e
        except Exception as e:
            logger.error("Lỗi khi truy vấn bảng issues")
            raise DatabaseQueryError(f"Không thể truy vấn danh sách sự cố: {str(e)}") from e
