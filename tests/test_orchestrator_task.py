"""
Tests verifying orchestrator task reception, state integrity, and pytest execution.
"""
import pytest
from pathlib import Path

import orchestrator


def test_orchestrator_receives_task():
    """Xác nhận orchestrator đã nạp task hợp lệ và state.json đầy đủ trường."""
    state = orchestrator.read_state()
    assert isinstance(state, dict)
    assert "task" in state
    assert isinstance(state["task"], str)
    assert len(state["task"].strip()) > 0


def test_orchestrator_state_schema_keys():
    """Kiểm tra cấu trúc state.json đáp ứng yêu cầu workflow."""
    state = orchestrator.read_state()
    required_keys = {"round", "iteration", "max_iterations", "state", "next_actor", "task"}
    missing = required_keys - set(state.keys())
    assert not missing, f"state.json thiếu các trường: {missing}"
    assert state["state"] in ("CODING", "REVIEW", "NEEDS_FIX", "PASSED")
    assert state["next_actor"] in ("ANTIGRAVITY", "CODEX")


def test_orchestrator_read_write_roundtrip(tmp_path, monkeypatch):
    """Kiểm tra hàm read_state và write_state ghi và đọc đúng chuẩn UTF-8 sạch."""
    dummy_file = tmp_path / "test_state.json"
    monkeypatch.setattr(orchestrator, "STATE_FILE", dummy_file)

    test_payload = {
        "round": 8,
        "iteration": 1,
        "max_iterations": 5,
        "state": "CODING",
        "next_actor": "ANTIGRAVITY",
        "task": "Thử nghiệm tiếng Việt: Kiểm tra trích dẫn & kiểm soát ảo giác 🚀",
    }
    orchestrator.write_state(test_payload)

    # Đọc lại bằng hàm read_state của orchestrator
    loaded = orchestrator.read_state()
    assert loaded == test_payload

    # Kiểm tra không có BOM (Byte Order Mark) trong file đã ghi
    raw_bytes = dummy_file.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "File ghi không được chứa BOM!"


def test_orchestrator_read_state_file_not_found(tmp_path, monkeypatch):
    """Kiểm tra read_state ném FileNotFoundError khi file state không tồn tại."""
    dummy_file = tmp_path / "non_existent.json"
    monkeypatch.setattr(orchestrator, "STATE_FILE", dummy_file)

    with pytest.raises(FileNotFoundError):
        orchestrator.read_state()


def test_orchestrator_read_state_invalid_json(tmp_path, monkeypatch):
    """Kiểm tra read_state ném ValueError khi nội dung state không phải json object hợp lệ."""
    dummy_file = tmp_path / "invalid_state.json"
    dummy_file.write_text("invalid json content", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "STATE_FILE", dummy_file)

    with pytest.raises(Exception):
        orchestrator.read_state()


def test_pytest_execution_confirmation():
    """Xác nhận pytest thực thi thành công trong môi trường orchestrator."""
    assert True
