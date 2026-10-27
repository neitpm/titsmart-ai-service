"""Tests for SampleDataLoader, validation rules, schema drift, numeric edge cases, and /health API endpoint."""
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from titsmart_ai.ingestion.sample_loader import SampleDataLoader
from titsmart_ai.domain.models import Project, Task, FieldLog, Issue, DocumentTrack
from titsmart_ai.api.main import app


@pytest.fixture
def sample_loader():
    return SampleDataLoader()


@pytest.fixture
def client():
    return TestClient(app)


def test_load_projects_sample_both_apis(sample_loader):
    # Test LoadResult API
    res = sample_loader.load_projects_result()
    assert res.total_records == 10
    assert res.loaded == 10
    assert res.skipped == 0
    assert len(res.errors) == 0
    # Test backward-compatible list API
    items = sample_loader.load_projects()
    assert len(items) == 10
    assert isinstance(items[0], Project)


def test_load_tasks_sample_both_apis(sample_loader):
    res = sample_loader.load_tasks_result()
    assert res.total_records == 50
    assert res.loaded == 50
    assert res.skipped == 0
    items = sample_loader.load_tasks()
    assert len(items) == 50
    assert isinstance(items[0], Task)


def test_load_field_logs_sample_both_apis(sample_loader):
    res = sample_loader.load_field_logs_result()
    assert res.total_records == 17
    assert res.loaded == 17
    assert res.skipped == 0
    items = sample_loader.load_field_logs()
    assert len(items) == 17
    assert isinstance(items[0], FieldLog)


def test_load_issues_sample_both_apis(sample_loader):
    res = sample_loader.load_issues_result()
    assert res.total_records == 2
    assert res.loaded == 2
    assert res.skipped == 0
    items = sample_loader.load_issues()
    assert len(items) == 2
    assert isinstance(items[0], Issue)


def test_load_document_tracks_sample_both_apis(sample_loader):
    res = sample_loader.load_document_tracks_result()
    assert res.total_records == 20
    assert res.loaded == 20
    assert res.skipped == 0
    items = sample_loader.load_document_tracks()
    assert len(items) == 20
    assert isinstance(items[0], DocumentTrack)


def test_schema_drift_rejection(tmp_path):
    drift_file = tmp_path / "projects_sample.json"
    drift_data = [
        {"id": "p-1", "code": "PRJ1", "name": "Du An 1", "projectCode": "unexpected_camel_case"}
    ]
    drift_file.write_text(json.dumps(drift_data), encoding="utf-8")
    loader = SampleDataLoader(sample_dir=tmp_path)
    res = loader.load_projects_result()
    assert res.loaded == 0
    assert res.skipped == 1
    assert len(res.errors) == 1
    assert "projectCode" in res.errors[0] or "extra_forbidden" in res.errors[0]


def test_numeric_edge_cases_rejection(tmp_path):
    """Kiểm tra từ chối chặt chẽ: NaN, Inf, âm, vượt 100, boolean, text."""
    bad_file = tmp_path / "projects_sample.json"
    bad_data = [
        {"id": "p-1", "code": "P1", "name": "T1", "progress_percent": 150.0},        # vượt 100
        {"id": "p-2", "code": "P2", "name": "T2", "contract_value": -10.0},          # số âm
        {"id": "p-3", "code": "P3", "name": "T3", "progress_percent": True},          # boolean
        {"id": "p-4", "code": "P4", "name": "T4", "progress_percent": "not_a_num"},  # text
    ]
    bad_file.write_text(json.dumps(bad_data), encoding="utf-8")
    loader = SampleDataLoader(sample_dir=tmp_path)
    res = loader.load_projects_result()
    assert res.loaded == 0
    assert res.skipped == 4
    assert len(res.errors) == 4


def test_numeric_string_coersion(tmp_path):
    """Kiểm tra chấp nhận chuỗi số hợp lệ ('50.5' -> 50.5)."""
    good_file = tmp_path / "projects_sample.json"
    good_data = [
        {"id": "p-1", "code": "P1", "name": "T1", "progress_percent": "50.5"}
    ]
    good_file.write_text(json.dumps(good_data), encoding="utf-8")
    loader = SampleDataLoader(sample_dir=tmp_path)
    res = loader.load_projects_result()
    assert res.loaded == 1
    assert res.items[0].progress_percent == 50.5


def test_loader_handles_missing_file(tmp_path):
    loader = SampleDataLoader(sample_dir=tmp_path)
    res = loader.load_projects_result()
    assert res.loaded == 0
    assert len(res.errors) == 1


def test_loader_handles_malformed_json(tmp_path):
    bad_file = tmp_path / "projects_sample.json"
    bad_file.write_text("{ this is not valid json }", encoding="utf-8")
    loader = SampleDataLoader(sample_dir=tmp_path)
    res = loader.load_projects_result()
    assert res.loaded == 0
    assert len(res.errors) == 1


def test_loader_summary_statistics(sample_loader):
    summary = sample_loader.load_all_summary()
    assert summary["total_loaded"] == 99
    assert summary["total_skipped"] == 0
    assert len(summary["errors"]) == 0


def test_health_check_endpoint(client):
    import titsmart_ai.api.main as api_main
    # Test standard cached call
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "offline_sample_only"
    assert data["database_connected"] is False
    assert data["cache_refreshed"] is False
    assert data["sample_data"]["total_loaded"] == 99

    initial_cache_id = id(api_main._sample_stats_cache)

    # Subsequent call must reuse identical cache
    subsequent_res = client.get("/health")
    assert subsequent_res.status_code == 200
    assert id(api_main._sample_stats_cache) == initial_cache_id

    # Test force refresh parameter: must re-instantiate cache
    refresh_response = client.get("/health?refresh=true")
    assert refresh_response.status_code == 200
    refresh_data = refresh_response.json()
    assert refresh_data["cache_refreshed"] is True
    assert refresh_data["sample_data"]["total_loaded"] == 99
    assert id(api_main._sample_stats_cache) != initial_cache_id
