"""Comprehensive test suite for ChatEngine, AuthContext, ChatRequest/Response, and POST /api/chat endpoint."""
import pytest
from fastapi.testclient import TestClient

from titsmart_ai.domain.chat import ChatRequest, ChatResponse, ChatSource
from titsmart_ai.security.auth import AuthContext
from titsmart_ai.domain.chat_engine import ChatEngine
from titsmart_ai.router.query_router import QueryRouter, QueryIntent
from titsmart_ai.tools.query_tool import InMemoryDataQueryTool
from titsmart_ai.tools.vector_store import InMemoryVectorStore, DeterministicFakeEmbeddingProvider
from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.domain.documents import KnowledgeDocument, TextChunk
from titsmart_ai.api.main import app, get_chat_engine


@pytest.fixture
def mock_chat_engine():
    projects = [
        Project(id="p1", code="TITS-01", name="Dự án 1", contract_value=1000.0, progress_percent=60.0),
        Project(id="p2", code="TITS-02", name="Dự án 2", contract_value=2000.0, progress_percent=0.0),
    ]
    tasks = [
        Task(id="t1", project_code="TITS-01", name="Kéo cáp ngầm", volume=100.0, progress=60.0, status="Đang làm"),
        Task(id="t2", project_code="TITS-01", name="Lắp tủ điện", volume=10.0, progress=100.0, status="Hoàn thành"),
        Task(id="t3", project_code="TITS-02", name="Đổ bê tông hố móng", volume=50.0, progress=30.0, status="Đang làm"),
    ]
    issues = [
        Issue(id="i1", project_code="TITS-01", title="Chậm cấp vật tư", description="Thiếu đầu cosse", priority="HIGH", status="OPEN")
    ]
    query_tool = InMemoryDataQueryTool(projects=projects, tasks=tasks, issues=issues)
    router = QueryRouter(known_projects={"TITS-01", "TITS-02"})
    embedding_provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    vector_store = InMemoryVectorStore(expected_dimensions=384)

    # Nạp 1 chunk vector mẫu cho TITS-01
    c1 = TextChunk(
        id="chk_1",
        document_id="doc_1",
        content="Ghi nhận hiện trường TITS-01: Thiếu đầu cosse nên chậm kéo cáp",
        source_table="issues",
        record_id="i1",
        project_code="TITS-01",
        chunk_index=0,
    )
    vecs = embedding_provider.embed([c1.content])
    vector_store.upsert([c1], vecs)

    return ChatEngine(
        router=router,
        query_tool=query_tool,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
    )


@pytest.fixture
def client(mock_chat_engine):
    app.dependency_overrides[get_chat_engine] = lambda: mock_chat_engine
    yield TestClient(app)
    app.dependency_overrides.clear()


# ==============================================================================
# 1. TEST CHAT ENGINE LOGIC & INTENTS
# ==============================================================================
def test_chat_engine_sql_intent(mock_chat_engine):
    auth = AuthContext(user_id="u1", allowed_project_codes={"TITS-01"})
    res = mock_chat_engine.answer("Tiến độ của dự án TITS-01 là bao nhiêu?", auth)
    assert res.intent == QueryIntent.SQL
    assert res.has_evidence is True
    assert "Dự án 1" in res.answer
    assert "60.0%" in res.answer or "80.0%" in res.answer
    assert len(res.sources) >= 1
    assert res.sources[0].source_type == "sql"


def test_chat_engine_vector_intent(mock_chat_engine):
    auth = AuthContext(user_id="u1", allowed_project_codes={"TITS-01"})
    res = mock_chat_engine.answer("Nguyên nhân sự cố và vướng mắc tại TITS-01 là gì?", auth)
    assert res.intent == QueryIntent.VECTOR_SEARCH
    assert res.has_evidence is True
    assert "Thiếu đầu cosse" in res.answer
    assert len(res.sources) >= 1
    assert res.sources[0].source_type == "vector"


def test_chat_engine_hybrid_intent(mock_chat_engine):
    auth = AuthContext(user_id="u1", allowed_project_codes={"TITS-01"})
    res = mock_chat_engine.answer("Dự án TITS-01 tiến độ bao nhiêu phần trăm và nguyên nhân vì sao bị chậm?", auth)
    assert res.intent == QueryIntent.HYBRID
    assert res.has_evidence is True
    assert "BÁO CÁO TỔNG HỢP" in res.answer
    assert any(s.source_type == "sql" for s in res.sources)
    assert any(s.source_type == "vector" for s in res.sources)


def test_chat_engine_no_evidence(mock_chat_engine):
    auth = AuthContext(user_id="u1", allowed_project_codes={"TITS-02"})
    # Dự án TITS-02 không có vector nhật ký nào
    res = mock_chat_engine.answer("Nguyên nhân sự cố tại TITS-02 là gì?", auth)
    assert res.intent == QueryIntent.VECTOR_SEARCH
    assert res.has_evidence is False
    assert "Không tìm thấy dữ liệu" in res.answer


# ==============================================================================
# 2. TEST SECURITY & FAIL-CLOSED ENFORCEMENT
# ==============================================================================
def test_chat_engine_empty_allowed_projects(mock_chat_engine):
    """Fail-Closed: User không có quyền dự án nào -> Không trả lời."""
    auth = AuthContext(user_id="u_none", allowed_project_codes=set())
    res = mock_chat_engine.answer("Tiến độ TITS-01 thế nào?", auth)
    assert res.intent == QueryIntent.UNSUPPORTED
    assert res.has_evidence is False
    assert "chưa được phân quyền" in res.answer


def test_chat_engine_unauthorized_project_access(mock_chat_engine):
    """User chỉ có quyền TITS-02 nhưng hỏi thông tin TITS-01 -> Bị từ chối."""
    auth = AuthContext(user_id="u_tits02", allowed_project_codes={"TITS-02"})
    res = mock_chat_engine.answer("Tiến độ dự án TITS-01 là bao nhiêu?", auth)
    assert res.intent == QueryIntent.UNSUPPORTED
    assert res.has_evidence is False
    assert "ngoài phạm vi quyền hạn" in res.answer


def test_chat_engine_mutation_rejected(mock_chat_engine):
    auth = AuthContext(user_id="u1", allowed_project_codes={"TITS-01"})
    res = mock_chat_engine.answer("Hãy xóa toàn bộ công việc của TITS-01", auth)
    assert res.intent == QueryIntent.UNSUPPORTED
    assert res.has_evidence is False


# ==============================================================================
# 3. TEST FASTAPI ENDPOINT: POST /api/chat
# ==============================================================================
def test_api_chat_success(client):
    headers = {
        "x-user-id": "engineer_01",
        "x-allowed-projects": "TITS-01,TITS-02",
    }
    payload = {"question": "Tiến độ của dự án TITS-01 là bao nhiêu?"}
    response = client.post("/api/chat", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "sql"
    assert data["has_evidence"] is True
    assert len(data["sources"]) >= 1


def test_api_chat_rejects_extra_fields(client):
    """Client cố tình gửi project_code hoặc user_id trong body -> Bị 422 Unprocessable Entity."""
    headers = {"x-user-id": "u1", "x-allowed-projects": "TITS-01"}
    bad_payload = {
        "question": "Tiến độ TITS-01?",
        "project_code": "TITS-01",  # Trường ngoài contract
        "user_id": "hacker_admin",
    }
    response = client.post("/api/chat", json=bad_payload, headers=headers)
    assert response.status_code == 422


def test_chat_engine_sql_aggregate_acl_isolation(mock_chat_engine):
    """
    Test SQL aggregate không làm lộ dữ liệu ngoài ACL:
    - User A chỉ có quyền TITS-01.
    - User B có quyền TITS-01 và TITS-02.
    - Kết quả thống kê chung của User A chỉ được tính trên TITS-01, không bị lẫn task của TITS-02.
    """
    auth_a = AuthContext(user_id="user_a", allowed_project_codes={"TITS-01"})
    auth_b = AuthContext(user_id="user_b", allowed_project_codes={"TITS-01", "TITS-02"})

    # Câu hỏi thống kê tổng hợp (không chỉ rõ project_code)
    question = "Tổng quan tiến độ các dự án hiện tại là bao nhiêu?"

    res_a = mock_chat_engine.answer(question, auth_a)
    res_b = mock_chat_engine.answer(question, auth_b)

    assert res_a.intent == QueryIntent.SQL
    assert res_b.intent == QueryIntent.SQL

    # User A chỉ có sources từ TITS-01
    assert all(s.project_code == "TITS-01" for s in res_a.sources)
    # User B có sources bao gồm cả TITS-01 và TITS-02
    b_project_codes = {s.project_code for s in res_b.sources}
    assert "TITS-01" in b_project_codes
    assert "TITS-02" in b_project_codes


def test_api_chat_rejects_missing_auth_headers(client):
    """Client không gửi bất kỳ Auth Header nào -> Bắt buộc 401 Unauthorized."""
    # Hoàn toàn không truyền headers
    response = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"})
    assert response.status_code == 401
    assert "Thiếu thông tin User ID" in response.json()["detail"]


def test_api_chat_empty_allowed_projects_header(client):
    """User hợp lệ nhưng X-Allowed-Projects không truyền -> allowed_project_codes rỗng -> Fail-closed."""
    headers = {"x-user-id": "valid_user_no_projects"}
    response = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["has_evidence"] is False
    assert "chưa được phân quyền" in data["answer"]


def test_api_chat_requires_auth_header(client):
    # Header rỗng hoặc chuỗi khoảng trắng -> 401
    response = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers={"x-user-id": ""})
    assert response.status_code == 401
    response_ws = client.post("/api/chat", json={"question": "Tiến độ TITS-01?"}, headers={"x-user-id": "   "})
    assert response_ws.status_code == 401


def test_api_chat_empty_question(client):
    headers = {"x-user-id": "u1", "x-allowed-projects": "TITS-01"}
    response = client.post("/api/chat", json={"question": ""}, headers=headers)
    assert response.status_code == 422  # min_length=1
