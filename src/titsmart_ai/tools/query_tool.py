"""Data Query Tool protocol and in-memory implementation for deterministic, read-only analytics."""
from typing import Protocol, List, Optional, Dict, Any, runtime_checkable
from decimal import Decimal, ROUND_HALF_UP

from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.ingestion.sample_loader import SampleDataLoader


def round_float(val: Optional[float], places: int = 2) -> float:
    """
    Làm tròn số thực xác định (deterministic) bằng Decimal ROUND_HALF_UP.
    - Xử lý rõ ràng None: trả về 0.0 (giá trị mặc định an toàn cho tổng/trung bình).
    - Không nuốt lỗi (No broad except): kiểm tra is_finite(), nếu dữ liệu hỏng sẽ raise ValueError rõ ràng.
    """
    if val is None:
        return 0.0

    decimal_value = Decimal(str(val))
    if not decimal_value.is_finite():
        raise ValueError(f"Giá trị số không hợp lệ (không hữu hạn): {val}")

    return float(decimal_value.quantize(Decimal("10") ** -places, rounding=ROUND_HALF_UP))


@runtime_checkable
class DataQueryTool(Protocol):
    """
    Protocol trừu tượng cho truy vấn số liệu phân tích:
    - 100% Read-Only.
    - Không nhận chuỗi raw SQL từ bên ngoài.
    - Kết quả tính toán tất định (deterministic).
    - Dễ dàng thay thế bằng SupabaseDataQueryTool khi kết nối DB.
    """

    def get_project_summary(self, project_code: str) -> Optional[Dict[str, Any]]:
        """Trả về tổng quan dự án: tên, tổng task, tiến độ trung bình, số issue, tổng khối lượng."""
        ...

    def find_delayed_tasks(
        self, project_code: Optional[str] = None, threshold: float = 100.0
    ) -> List[Task]:
        """Tìm các task chưa hoàn thành (mặc định: progress < threshold)."""
        ...

    def get_progress_summary(
        self, project_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Tổng hợp phân bố tiến độ: số lượng task hoàn thành, đang làm, chưa làm, tỷ lệ hoàn thành chung."""
        ...

    def find_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        """Lọc danh sách issue/sự cố theo dự án, mức độ ưu tiên hoặc trạng thái."""
        ...


class InMemoryDataQueryTool:
    """
    Hiện thực DataQueryTool trên dữ liệu nạp từ SampleDataLoader (bộ nhớ trong).
    Tuyệt đối không can thiệp, biến đổi hay ghi đè dữ liệu gốc.
    """

    def __init__(
        self,
        projects: Optional[List[Project]] = None,
        tasks: Optional[List[Task]] = None,
        issues: Optional[List[Issue]] = None,
        sample_loader: Optional[SampleDataLoader] = None,
    ):
        loader = sample_loader or SampleDataLoader()
        self._projects = list(projects) if projects is not None else loader.load_projects()
        self._tasks = list(tasks) if tasks is not None else loader.load_tasks()
        self._issues = list(issues) if issues is not None else loader.load_issues()

    def get_project_summary(self, project_code: str) -> Optional[Dict[str, Any]]:
        if not project_code:
            return None

        # 1. Tìm thông tin dự án
        project = next((p for p in self._projects if p.code == project_code), None)
        if not project:
            return None

        # 2. Lấy danh sách tasks và issues của dự án
        proj_tasks = [t for t in self._tasks if t.project_code == project_code]
        proj_issues = [i for i in self._issues if i.project_code == project_code]

        total_tasks = len(proj_tasks)
        total_volume = sum((t.volume or 0.0) for t in proj_tasks)
        total_volume = round_float(total_volume, 2)

        # Tính tiến độ trung bình:
        # Trong Data Contract: progress của task luôn được chuẩn hóa theo thang % (0.0 -> 100.0)
        if total_tasks > 0:
            progress_sum = sum((t.progress or 0.0) for t in proj_tasks)
            avg_progress = round_float(progress_sum / total_tasks, 2)
        else:
            avg_progress = round_float(project.progress_percent or 0.0, 2)

        return {
            "project_code": project.code,
            "project_name": project.name,
            "status": project.status,
            "total_tasks": total_tasks,
            "average_progress": avg_progress,
            "total_issues": len(proj_issues),
            "total_volume": total_volume,
            "contract_value": project.contract_value or 0.0,
        }

    def find_delayed_tasks(
        self, project_code: Optional[str] = None, threshold: float = 100.0
    ) -> List[Task]:
        if threshold < 0.0 or threshold > 100.0:
            raise ValueError(f"Ngưỡng tiến độ (threshold) phải nằm trong khoảng [0.0, 100.0], nhận: {threshold}")

        # Sao chép sâu (deep=True) để bảo vệ tuyệt đối tính bất biến của nested structures
        tasks = [t.model_copy(deep=True) for t in self._tasks]

        if project_code:
            tasks = [t for t in tasks if t.project_code == project_code]

        # Chuẩn hóa duy nhất: t.progress luôn là thang % (0.0 -> 100.0)
        return [t for t in tasks if (t.progress or 0.0) < threshold]

    def get_progress_summary(
        self, project_code: Optional[str] = None
    ) -> Dict[str, Any]:
        tasks = self._tasks
        if project_code:
            tasks = [t for t in tasks if t.project_code == project_code]

        total = len(tasks)
        if total == 0:
            return {
                "project_code": project_code,
                "total_tasks": 0,
                "completed_tasks": 0,
                "in_progress_tasks": 0,
                "not_started_tasks": 0,
                "overall_completion_rate": 0.0,
            }

        completed = 0
        in_progress = 0
        not_started = 0
        total_progress = 0.0

        for t in tasks:
            pct = t.progress or 0.0
            total_progress += pct

            if pct >= 100.0 or (t.status and "hoàn thành" in t.status.lower()):
                completed += 1
            elif pct > 0.0 or (t.status and "đang" in t.status.lower()):
                in_progress += 1
            else:
                not_started += 1

        overall_rate = round_float(total_progress / total, 2)

        return {
            "project_code": project_code,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "not_started_tasks": not_started,
            "overall_completion_rate": overall_rate,
        }

    def find_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        issues = [i.model_copy(deep=True) for i in self._issues]

        if project_code:
            issues = [i for i in issues if i.project_code == project_code]
        if priority:
            issues = [i for i in issues if (i.priority or "").upper() == priority.upper()]
        if status:
            issues = [i for i in issues if (i.status or "").upper() == status.upper()]

        return issues


class SupabaseDataQueryTool:
    """
    Hiện thực DataQueryTool kết nối với cơ sở dữ liệu Supabase Staging.
    - Nhận client thông qua Dependency Injection (ReadOnlyDataClient protocol).
    - 100% tuân thủ DataQueryTool protocol.
    - Không nhận raw SQL, chỉ gọi phương thức an toàn của client.
    - Tính toán tất định (deterministic), không suy đoán dữ liệu thiếu.
    """

    def __init__(self, client: Any):
        self._client = client

    def get_project_summary(self, project_code: str) -> Optional[Dict[str, Any]]:
        if not project_code:
            return None

        projects = self._client.select_projects(project_code=project_code)
        if not projects:
            return None
        project = projects[0]

        proj_tasks = self._client.select_tasks(project_code=project_code)
        proj_issues = self._client.select_issues(project_code=project_code)

        total_tasks = len(proj_tasks)
        total_volume = sum((t.volume or 0.0) for t in proj_tasks)
        total_volume = round_float(total_volume, 2)

        if total_tasks > 0:
            progress_sum = sum((t.progress or 0.0) for t in proj_tasks)
            avg_progress = round_float(progress_sum / total_tasks, 2)
        else:
            avg_progress = round_float(project.progress_percent or 0.0, 2)

        return {
            "project_code": project.code,
            "project_name": project.name,
            "status": project.status,
            "total_tasks": total_tasks,
            "average_progress": avg_progress,
            "total_issues": len(proj_issues),
            "total_volume": total_volume,
            "contract_value": project.contract_value or 0.0,
        }

    def find_delayed_tasks(
        self, project_code: Optional[str] = None, threshold: float = 100.0
    ) -> List[Task]:
        if threshold < 0.0 or threshold > 100.0:
            raise ValueError(f"Ngưỡng tiến độ (threshold) phải nằm trong khoảng [0.0, 100.0], nhận: {threshold}")

        tasks = self._client.select_tasks(project_code=project_code)
        return [t.model_copy(deep=True) for t in tasks if (t.progress or 0.0) < threshold]

    def get_progress_summary(
        self, project_code: Optional[str] = None
    ) -> Dict[str, Any]:
        tasks = self._client.select_tasks(project_code=project_code)

        total = len(tasks)
        if total == 0:
            return {
                "project_code": project_code,
                "total_tasks": 0,
                "completed_tasks": 0,
                "in_progress_tasks": 0,
                "not_started_tasks": 0,
                "overall_completion_rate": 0.0,
            }

        completed = 0
        in_progress = 0
        not_started = 0
        total_progress = 0.0

        for t in tasks:
            pct = t.progress or 0.0
            total_progress += pct

            if pct >= 100.0 or (t.status and "hoàn thành" in t.status.lower()):
                completed += 1
            elif pct > 0.0 or (t.status and "đang" in t.status.lower()):
                in_progress += 1
            else:
                not_started += 1

        overall_rate = round_float(total_progress / total, 2)

        return {
            "project_code": project_code,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "not_started_tasks": not_started,
            "overall_completion_rate": overall_rate,
        }

    def find_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        issues = self._client.select_issues(
            project_code=project_code, priority=priority, status=status
        )
        return [i.model_copy(deep=True) for i in issues]
