"""Comprehensive security tests for JWT verification, membership lookup, and header spoofing rejection."""
import pytest
import jwt
from fastapi.testclient import TestClient
from fastapi import HTTPException

from titsmart_ai.api.main import app, get_chat_engine
from titsmart_ai.config import settings, Settings
from titsmart_ai.security.auth import get_auth_context, AuthContext
from titsmart_ai.security.membership import InMemoryProjectMembershipProvider
from tests.test_chat_engine import mock_chat_engine


@pytest.fixture
def client(mock_chat_engine):
    app.dependency_overrides[get_chat_engine] = lambda: mock_chat_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_jwt_verification_and_server_side_membership(client):
    """
    Test chuẩn xác thực Production:
    - Client gửi JWT hợp lệ chứa 'sub': 'engineer_tits01'.
    - Server tra cứu từ membership_provider: engineer_tits01 chỉ có quyền TITS-01.
    - Dù client có cố tình chèn header X-Allowed-Projects: TITS-02, server hoàn toàn lờ đi và chỉ cấp TITS-01.
    """
    secret = settings.JWT_SECRET_KEY or "titsmart_offline_dev_secret_key_32chars"
    token = jwt.encode(
        {"sub": "engineer_tits01", "role": "engineer", "aud": "authenticated", "exp": 9999999999},
        secret,
        algorithm="HS256"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Allowed-Projects": "TITS-02,HACK_PROJECT",  # Cố tình giả mạo header
    }

    # Hỏi thông tin dự án TITS-01 -> Được phép
    res_allowed = client.post("/api/chat", json={"question": "Tiến độ dự án TITS-01 là bao nhiêu?"}, headers=headers)
    assert res_allowed.status_code == 200
    assert res_allowed.json()["has_evidence"] is True

    # Hỏi thông tin dự án TITS-02 -> Bị từ chối dù có header X-Allowed-Projects: TITS-02
    res_denied = client.post("/api/chat", json={"question": "Tiến độ dự án TITS-02 là bao nhiêu?"}, headers=headers)
    assert res_denied.status_code == 200
    assert res_denied.json()["has_evidence"] is False
    assert "ngoài phạm vi quyền hạn" in res_denied.json()["answer"]


def test_jwt_invalid_or_expired_token(client):
    """Token sai secret hoặc định dạng hỏng -> Trả 401 Unauthorized."""
    headers = {"Authorization": "Bearer invalid.token.payload"}
    res = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers=headers)
    assert res.status_code == 401
    assert "Token xác thực JWT không hợp lệ" in res.json()["detail"]


def test_jwt_mode_enforced_rejects_mock_headers(monkeypatch, client):
    """
    Khi AUTH_MODE='jwt', nếu request chỉ gửi X-User-Id mà không có Bearer token -> Bắt buộc 401.
    """
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt")
    headers = {
        "x-user-id": "engineer_01",
        "x-allowed-projects": "TITS-01",
    }
    res = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers=headers)
    assert res.status_code == 401
    assert "AUTH_MODE='jwt'" in res.json()["detail"]


def test_production_environment_rejects_mock_mode(monkeypatch, client):
    """
    Bảo vệ Production: Nếu APP_ENV='production', hệ thống từ chối mọi yêu cầu ở chế độ mock (HTTP 500).
    """
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "AUTH_MODE", "mock")

    headers = {"x-user-id": "engineer_01"}
    res = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers=headers)
    assert res.status_code == 500
    assert "Không được bật AUTH_MODE='mock' trên production" in res.json()["detail"]


def test_config_validator_prevents_mock_in_production():
    """
    Pydantic Settings validator chặn khởi động nếu cấu hình APP_ENV=production cùng AUTH_MODE=mock.
    """
    with pytest.raises(ValueError, match="Tuyệt đối không được bật AUTH_MODE='mock' trong môi trường PRODUCTION"):
        Settings(APP_ENV="production", AUTH_MODE="mock")


def test_supabase_project_membership_provider_unit():
    """Test unit cho SupabaseProjectMembershipProvider với FakeReadOnlyClient."""
    from titsmart_ai.security.membership import SupabaseProjectMembershipProvider
    from tests.test_supabase_adapter import FakeReadOnlyClient

    fake_client = FakeReadOnlyClient()
    fake_client.project_members = {
        "u_test_1": [{"user_id": "u_test_1", "project_code": "TITS-01"}, {"user_id": "u_test_1", "project_code": "TITS-02"}],
        "u_test_2": [{"user_id": "u_test_2", "project_code": "DA-01"}],
    }
    provider = SupabaseProjectMembershipProvider(client=fake_client)

    # u_test_1 có quyền TITS-01 và TITS-02
    assert provider.get_allowed_projects("u_test_1") == {"TITS-01", "TITS-02"}
    # u_test_2 chỉ có DA-01
    assert provider.get_allowed_projects("u_test_2") == {"DA-01"}
    # User không tồn tại -> Trả về set rỗng (fail-closed)
    assert provider.get_allowed_projects("u_unknown") == set()
    # User id rỗng -> Trả về set rỗng
    assert provider.get_allowed_projects("") == set()

    # Lỗi database -> Fail-closed trả về set rỗng
    error_client = FakeReadOnlyClient(simulate_error=True)
    error_provider = SupabaseProjectMembershipProvider(client=error_client)
    assert error_provider.get_allowed_projects("u_test_1") == set()


def test_jwt_claims_verification_iss_aud_exp(monkeypatch, client):
    """Xác minh chặt chẽ các JWT claims: exp, aud, iss, sub."""
    secret = settings.JWT_SECRET_KEY or "titsmart_offline_dev_secret_key_32chars"
    monkeypatch.setattr(settings, "JWT_ISSUER", "https://xyz-staging.supabase.co/auth/v1")
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "authenticated")

    # 1. Token thiếu exp -> Bị từ chối
    token_no_exp = jwt.encode(
        {"sub": "u1", "iss": "https://xyz-staging.supabase.co/auth/v1", "aud": "authenticated"},
        secret,
        algorithm="HS256"
    )
    res = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers={"Authorization": f"Bearer {token_no_exp}"})
    assert res.status_code == 401

    # 2. Token sai issuer -> Bị từ chối
    token_bad_iss = jwt.encode(
        {"sub": "u1", "iss": "https://attacker.com", "aud": "authenticated", "exp": 9999999999},
        secret,
        algorithm="HS256"
    )
    res = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers={"Authorization": f"Bearer {token_bad_iss}"})
    assert res.status_code == 401

    # 3. Token đúng claims -> Thành công
    token_valid = jwt.encode(
        {"sub": "engineer_tits01", "iss": "https://xyz-staging.supabase.co/auth/v1", "aud": "authenticated", "exp": 9999999999},
        secret,
        algorithm="HS256"
    )
    res = client.post("/api/chat", json={"question": "Tiến độ dự án TITS-01 là bao nhiêu?"}, headers={"Authorization": f"Bearer {token_valid}"})
    assert res.status_code == 200
