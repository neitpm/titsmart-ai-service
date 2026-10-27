"""Tests for SupabaseDataQueryTool, allowlist security, field mapping, timeout, and optional integration test."""
import os
import pytest
from typing import List, Optional
from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.tools.query_tool import DataQueryTool, SupabaseDataQueryTool
from titsmart_ai.adapters.supabase_adapter import (
    ReadOnlyDataClient,
    SupabaseReadOnlyClient,
    DatabaseQueryError,
    camel_to_snake,
    normalize_record_keys,
)
from titsmart_ai.config import Settings


class FakeReadOnlyClient:
    """Fake client giả lập cơ sở dữ liệu Supabase Staging hoàn toàn offline (không dùng mạng)."""

    def __init__(self, projects=None, tasks=None, issues=None, simulate_error=False, simulate_timeout=False):
        self.projects = projects or []
        self.tasks = tasks or []
        self.issues = issues or []
        self.simulate_error = simulate_error
        self.simulate_timeout = simulate_timeout

    def select_projects(self, project_code: Optional[str] = None) -> List[Project]:
        if self.simulate_timeout:
            raise DatabaseQueryError("Truy vấn bảng projects bị quá thời gian (10.0s)")
        if self.simulate_error:
            raise DatabaseQueryError("Lỗi kết nối database giả lập (HTTP 403 Forbidden)")
        if project_code:
            return [p for p in self.projects if p.code == project_code]
        return list(self.projects)

    def select_tasks(self, project_code: Optional[str] = None) -> List[Task]:
        if self.simulate_timeout:
            raise DatabaseQueryError("Truy vấn bảng tasks bị quá thời gian (10.0s)")
        if self.simulate_error:
            raise DatabaseQueryError("Lỗi kết nối database giả lập (HTTP 403 Forbidden)")
        if project_code:
            return [t for t in self.tasks if t.project_code == project_code]
        return list(self.tasks)

    def select_issues(
        self,
        project_code: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Issue]:
        if self.simulate_timeout:
            raise DatabaseQueryError("Truy vấn bảng issues bị quá thời gian (10.0s)")
        if self.simulate_error:
            raise DatabaseQueryError("Lỗi kết nối database giả lập (HTTP 403 Forbidden)")
        res = list(self.issues)
        if project_code:
            res = [i for i in res if i.project_code == project_code]
        if priority:
            res = [i for i in res if (i.priority or "").upper() == priority.upper()]
        if status:
            res = [i for i in res if (i.status or "").upper() == status.upper()]
        return res

    def select_project_members(self, user_id: str):
        if self.simulate_timeout:
            raise DatabaseQueryError("Truy vấn bảng project_members bị quá thời gian (10.0s)")
        if self.simulate_error:
            raise DatabaseQueryError("Lỗi kết nối database giả lập (HTTP 403 Forbidden)")
        return getattr(self, "project_members", {}).get(user_id, [])


@pytest.fixture
def fake_data():
    projects = [
        Project(id="p1", code="TITS-STAGING-01", name="Dự án Staging 1", contract_value=5000.0, progress_percent=0.0)
    ]
    tasks = [
        Task(id="t1", project_code="TITS-STAGING-01", name="Task 1", volume=10.0, progress=100.0, status="Hoàn thành"),
        Task(id="t2", project_code="TITS-STAGING-01", name="Task 2", volume=20.0, progress=50.0, status="Đang làm"),
    ]
    issues = [
        Issue(id="i1", project_code="TITS-STAGING-01", title="Sự cố test", priority="CRITICAL", status="OPEN")
    ]
    return projects, tasks, issues


# 1. Kiểm tra tuân thủ Protocol
def test_fake_client_implements_read_only_protocol():
    client = FakeReadOnlyClient()
    assert isinstance(client, ReadOnlyDataClient)
    assert not hasattr(client, "insert")
    assert not hasattr(client, "update")
    assert not hasattr(client, "delete")
    assert not hasattr(client, "drop")


def test_supabase_tool_implements_data_query_tool_protocol(fake_data):
    projects, tasks, issues = fake_data
    client = FakeReadOnlyClient(projects, tasks, issues)
    tool = SupabaseDataQueryTool(client=client)
    assert isinstance(tool, DataQueryTool)


# 2. Test get_project_summary
def test_supabase_tool_project_summary(fake_data):
    projects, tasks, issues = fake_data
    client = FakeReadOnlyClient(projects, tasks, issues)
    tool = SupabaseDataQueryTool(client=client)

    summary = tool.get_project_summary("TITS-STAGING-01")
    assert summary is not None
    assert summary["project_code"] == "TITS-STAGING-01"
    assert summary["total_tasks"] == 2
    assert summary["average_progress"] == 75.0
    assert summary["total_issues"] == 1
    assert summary["total_volume"] == 30.0


def test_supabase_tool_project_summary_not_found(fake_data):
    projects, tasks, issues = fake_data
    client = FakeReadOnlyClient(projects, tasks, issues)
    tool = SupabaseDataQueryTool(client=client)
    assert tool.get_project_summary("NON_EXISTING") is None
    assert tool.get_project_summary("") is None


# 3. Test find_delayed_tasks
def test_supabase_tool_delayed_tasks(fake_data):
    projects, tasks, issues = fake_data
    client = FakeReadOnlyClient(projects, tasks, issues)
    tool = SupabaseDataQueryTool(client=client)

    delayed = tool.find_delayed_tasks(project_code="TITS-STAGING-01")
    assert len(delayed) == 1
    assert delayed[0].id == "t2"


# 4. Test find_issues
def test_supabase_tool_find_issues(fake_data):
    projects, tasks, issues = fake_data
    client = FakeReadOnlyClient(projects, tasks, issues)
    tool = SupabaseDataQueryTool(client=client)

    criticals = tool.find_issues(priority="CRITICAL")
    assert len(criticals) == 1
    assert criticals[0].title == "Sự cố test"

    standards = tool.find_issues(priority="STANDARD")
    assert len(standards) == 0


# 5. Test error translation & timeout
def test_supabase_tool_database_error_propagation():
    error_client = FakeReadOnlyClient(simulate_error=True)
    tool = SupabaseDataQueryTool(client=error_client)

    with pytest.raises(DatabaseQueryError, match="HTTP 403 Forbidden"):
        tool.get_project_summary("ANY")


def test_supabase_tool_timeout_propagation():
    timeout_client = FakeReadOnlyClient(simulate_timeout=True)
    tool = SupabaseDataQueryTool(client=timeout_client)

    with pytest.raises(DatabaseQueryError, match="quá thời gian"):
        tool.find_delayed_tasks()


# 6. Test Field Mapping (camelCase -> snake_case)
def test_field_mapping_camel_to_snake():
    raw_supabase_row = {
        "id": "t-100",
        "projectCode": "PRJ-01",
        "name": "Thử nghiệm mapping",
        "assignedEngineerName": "Kỹ sư A",
        "volume": 50.0,
        "progress": 0.8,
    }
    normalized = normalize_record_keys(raw_supabase_row)
    assert normalized["project_code"] == "PRJ-01"
    assert normalized["assigned_engineer_name"] == "Kỹ sư A"
    # Đảm bảo Task validate thành công mà không bị extra="forbid" chặn
    task = Task.model_validate(normalized)
    assert task.project_code == "PRJ-01"
    assert task.assigned_engineer_name == "Kỹ sư A"
    assert task.progress == 80.0


# 7. Test Allowlist & Security Configuration
def test_settings_allowlist_enforcement():
    # Đúng allowlist hostname -> Chấp nhận
    s_good = Settings(
        SUPABASE_ENV="staging",
        SUPABASE_ALLOWED_PROJECT_REF="staging-ref-xyz",
        SUPABASE_URL="https://staging-ref-xyz.supabase.co",
        SUPABASE_ANON_KEY="anon-key",
    )
    assert s_good.SUPABASE_URL == "https://staging-ref-xyz.supabase.co"

    # Sai hostname -> Bị từ chối
    with pytest.raises(ValueError, match="allowlist"):
        Settings(
            SUPABASE_ENV="staging",
            SUPABASE_ALLOWED_PROJECT_REF="staging-ref-xyz",
            SUPABASE_URL="https://other-unauthorized-project.supabase.co",
            SUPABASE_ANON_KEY="anon-key",
        )

    # Ref xuất hiện trong path hoặc query của host giả mạo -> Phải bị từ chối chính xác
    with pytest.raises(ValueError, match="allowlist"):
        Settings(
            SUPABASE_ENV="staging",
            SUPABASE_ALLOWED_PROJECT_REF="staging-ref-xyz",
            SUPABASE_URL="https://malicious-host.com/staging-ref-xyz",
            SUPABASE_ANON_KEY="anon-key",
        )


def test_settings_rejects_production_env():
    with pytest.raises(ValueError, match="SUPABASE_ENV=production"):
        Settings(SUPABASE_ENV="production")


def test_settings_requires_credentials_for_staging():
    cfg = Settings(SUPABASE_URL=None, SUPABASE_ANON_KEY=None)
    with pytest.raises(ValueError, match="Thiếu cấu hình"):
        cfg.validate_staging_credentials()


def test_no_secret_leak_in_exceptions(caplog):
    client = FakeReadOnlyClient(simulate_error=True)
    tool = SupabaseDataQueryTool(client=client)
    try:
        tool.find_delayed_tasks()
    except Exception as e:
        error_msg = str(e)
        assert "eyJ" not in error_msg
        assert "service_role" not in error_msg


# 8. Bộ Integration Test Tùy Chọn (Chỉ chạy khi SUPABASE_INTEGRATION_TESTS=1)
@pytest.mark.skipif(
    os.getenv("SUPABASE_INTEGRATION_TESTS") != "1",
    reason="Bỏ qua integration test khi chưa bật cờ SUPABASE_INTEGRATION_TESTS=1"
)
def test_live_supabase_staging_read_only_and_rls():
    """
    Integration test trực tiếp với Staging Database:
    - Xác nhận chỉ đọc (SELECT) thành công.
    - Xác nhận các lệnh mutation (INSERT, UPDATE, DELETE) bị Database Role/RLS từ chối.
    """
    settings = Settings()
    settings.validate_staging_credentials()

    try:
        from supabase import create_client
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
    except ImportError:
        pytest.skip("Chưa cài đặt thư viện supabase SDK")

    # 1. SELECT phải thành công
    res = client.table("projects").select("id, code, name").limit(1).execute()
    assert res.data is not None

    # 2. MUTATION (INSERT) phải bị PostgreSQL từ chối (401/403/RLS Error)
    with pytest.raises(Exception):
        client.table("projects").insert({"id": "malicious_probe", "code": "HACK"}).execute()
