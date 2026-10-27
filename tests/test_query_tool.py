"""Tests for DataQueryTool protocol, InMemoryDataQueryTool implementation, and numeric precision rules."""
import pytest
from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.tools.query_tool import DataQueryTool, InMemoryDataQueryTool, round_float


@pytest.fixture
def query_tool():
    """Tool sử dụng dữ liệu sample mặc định."""
    return InMemoryDataQueryTool()


@pytest.fixture
def custom_query_tool():
    """Tool với dữ liệu kiểm thử kiểm soát chặt chẽ từng trường hợp biên."""
    projects = [
        Project(id="p1", code="PRJ-01", name="Dự án 1", contract_value=1000.0, progress_percent=50.0),
        Project(id="p2", code="PRJ-02", name="Dự án 2", contract_value=2000.0, progress_percent=0.0),
    ]
    tasks = [
        # PRJ-01: 3 tasks (t1: 100%, t2: 50%, t3: 0%)
        Task(id="t1", project_code="PRJ-01", name="Task 1", volume=10.5, progress=100.0, status="Hoàn thành"),
        Task(id="t2", project_code="PRJ-01", name="Task 2", volume=20.5, progress=50.0, status="Đang làm"),
        Task(id="t3", project_code="PRJ-01", name="Task 3", volume=30.0, progress=0.0, status="Chưa làm"),
        # PRJ-02: 1 task với volume None và progress None
        Task(id="t4", project_code="PRJ-02", name="Task 4", volume=None, progress=None, status=None),
    ]
    issues = [
        Issue(id="i1", project_code="PRJ-01", title="Sự cố 1", priority="CRITICAL", status="OPEN"),
        Issue(id="i2", project_code="PRJ-01", title="Sự cố 2", priority="STANDARD", status="RESOLVED"),
        Issue(id="i3", project_code="PRJ-02", title="Sự cố 3", priority="CRITICAL", status="PROCESSING"),
    ]
    return InMemoryDataQueryTool(projects=projects, tasks=tasks, issues=issues)


# 1. Kiểm tra tuân thủ Protocol
def test_protocol_compliance(query_tool):
    assert isinstance(query_tool, DataQueryTool)


# 2. Test round_float precision & error handling
def test_round_float_deterministic():
    assert round_float(10.555, 2) == 10.56
    assert round_float(10.554, 2) == 10.55
    assert round_float(None) == 0.0


def test_round_float_rejects_nan_and_inf():
    with pytest.raises(ValueError, match="không hữu hạn"):
        round_float(float("nan"))
    with pytest.raises(ValueError, match="không hữu hạn"):
        round_float(float("inf"))


# 3. Test progress normalization tại Ingestion/Model
def test_task_progress_normalization():
    # val <= 1.0 (như 0.5) tự động chuyển sang 50.0% tại tầng model ingestion
    t_ratio = Task(id="t_ratio", project_code="PRJ-01", name="T", progress=0.5)
    assert t_ratio.progress == 50.0

    # val = 1.0 -> 100.0%
    t_one = Task(id="t_one", project_code="PRJ-01", name="T", progress=1.0)
    assert t_one.progress == 100.0

    # val = 0.01 -> 1.0%
    t_small = Task(id="t_small", project_code="PRJ-01", name="T", progress=0.01)
    assert t_small.progress == 1.0

    # val = None -> None (default 0.0)
    t_none = Task(id="t_none", project_code="PRJ-01", name="T", progress=None)
    assert t_none.progress is None


# 4. Test get_project_summary
def test_project_summary_existing(custom_query_tool):
    summary = custom_query_tool.get_project_summary("PRJ-01")
    assert summary is not None
    assert summary["project_code"] == "PRJ-01"
    assert summary["project_name"] == "Dự án 1"
    assert summary["total_tasks"] == 3
    # Tiến độ trung bình của (100% + 50% + 0%) / 3 = 50.0%
    assert summary["average_progress"] == 50.0
    assert summary["total_issues"] == 2
    assert summary["total_volume"] == 61.0
    assert summary["contract_value"] == 1000.0


def test_project_summary_not_found(custom_query_tool):
    assert custom_query_tool.get_project_summary("NON_EXISTING_PROJECT") is None
    assert custom_query_tool.get_project_summary("") is None


def test_project_summary_with_null_values(custom_query_tool):
    summary = custom_query_tool.get_project_summary("PRJ-02")
    assert summary is not None
    assert summary["total_tasks"] == 1
    assert summary["total_volume"] == 0.0
    assert summary["average_progress"] == 0.0


# 5. Test find_delayed_tasks
def test_find_delayed_tasks_all(custom_query_tool):
    delayed = custom_query_tool.find_delayed_tasks()
    assert len(delayed) == 3
    ids = [t.id for t in delayed]
    assert "t2" in ids and "t3" in ids and "t4" in ids
    assert "t1" not in ids


def test_find_delayed_tasks_by_project(custom_query_tool):
    delayed_prj1 = custom_query_tool.find_delayed_tasks(project_code="PRJ-01")
    assert len(delayed_prj1) == 2
    ids = [t.id for t in delayed_prj1]
    assert "t2" in ids and "t3" in ids


def test_find_delayed_tasks_custom_threshold(custom_query_tool):
    delayed = custom_query_tool.find_delayed_tasks(threshold=50.0)
    assert len(delayed) == 2
    ids = [t.id for t in delayed]
    assert "t3" in ids and "t4" in ids


def test_find_delayed_tasks_invalid_threshold(custom_query_tool):
    with pytest.raises(ValueError, match="Ngưỡng tiến độ"):
        custom_query_tool.find_delayed_tasks(threshold=150.0)
    with pytest.raises(ValueError, match="Ngưỡng tiến độ"):
        custom_query_tool.find_delayed_tasks(threshold=-5.0)


# 6. Test get_progress_summary
def test_progress_summary_project(custom_query_tool):
    res = custom_query_tool.get_progress_summary("PRJ-01")
    assert res["project_code"] == "PRJ-01"
    assert res["total_tasks"] == 3
    assert res["completed_tasks"] == 1
    assert res["in_progress_tasks"] == 1
    assert res["not_started_tasks"] == 1
    assert res["overall_completion_rate"] == 50.0


def test_progress_summary_empty():
    empty_tool = InMemoryDataQueryTool(projects=[], tasks=[], issues=[])
    res = empty_tool.get_progress_summary("ANY")
    assert res["total_tasks"] == 0
    assert res["overall_completion_rate"] == 0.0


# 7. Test find_issues
def test_find_issues_by_priority(custom_query_tool):
    criticals = custom_query_tool.find_issues(priority="CRITICAL")
    assert len(criticals) == 2
    ids = [i.id for i in criticals]
    assert "i1" in ids and "i3" in ids


def test_find_issues_by_status_and_project(custom_query_tool):
    issues = custom_query_tool.find_issues(project_code="PRJ-01", status="OPEN")
    assert len(issues) == 1
    assert issues[0].id == "i1"


def test_find_issues_not_found(custom_query_tool):
    issues = custom_query_tool.find_issues(priority="NON_EXISTING")
    assert len(issues) == 0


# 8. Test Immutability
def test_data_immutability(custom_query_tool):
    delayed = custom_query_tool.find_delayed_tasks()
    first_task = delayed[0]
    first_task.name = "MODIFIED_NAME"

    delayed_again = custom_query_tool.find_delayed_tasks()
    assert delayed_again[0].name != "MODIFIED_NAME"
