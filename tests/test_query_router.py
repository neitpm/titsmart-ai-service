"""Comprehensive test suite for QueryRouter: 15 SQL, 15 Vector, 10 Hybrid, Fail-Closed ACL, Injection, Determinism."""
import pytest
from titsmart_ai.router.query_router import QueryRouter, QueryIntent, QueryPlan

ALLOWED_PROJECTS = {"TITS-01", "TITS-02", "DA-01", "TRAM_BIEN_AP_500KV"}


@pytest.fixture
def router():
    return QueryRouter(known_projects=ALLOWED_PROJECTS)


# ==============================================================================
# 1. 15 TEST CASES FOR SQL INTENT (Tiếng Việt có dấu, không dấu, số liệu)
# ==============================================================================
SQL_TEST_QUESTIONS = [
    "Dự án TITS-01 có bao nhiêu công việc?",
    "Tiến độ hiện tại của dự án TITS-01 đạt bao nhiêu phần trăm?",
    "Tổng số task của DA-01 là bao nhiêu?",
    "Tong quan tien do du an TITS-01",  # Không dấu
    "Có bao nhiêu task chậm tiến độ tại TITS-01?",
    "Danh sách các công việc trễ hạn trong dự án TITS-02",
    "Tổng khối lượng thi công của dự án TITS-01",
    "Gia tri hop dong cua du an TITS-01 la bao nhieu",  # Không dấu
    "Thống kê số lượng công việc đã hoàn thành tại TITS-01",
    "Tỉ lệ hoàn thành của dự án DA-01 là bao nhiêu?",
    "Báo cáo chi phí và ngân sách của TITS-01",
    "TITS-01 có bao nhiêu phần trăm công việc chưa làm?",
    "Số lượng đầu việc HT của dự án TITS-01",  # Viết tắt HT (hoàn thành)
    "Tổng khối lượng NVL đã sử dụng tại TITS-01",  # Viết tắt NVL (nguyên vật liệu)
    "Thống kê tổng công việc đang làm ở TRAM_BIEN_AP_500KV",
]

@pytest.mark.parametrize("q", SQL_TEST_QUESTIONS)
def test_sql_intent_classification(router, q):
    plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
    assert plan.intent == QueryIntent.SQL, f"Câu '{q}' phải có intent SQL, nhận: {plan.intent}"
    assert plan.sql_operation is not None
    assert plan.vector_query is None


# ==============================================================================
# 2. 15 TEST CASES FOR VECTOR_SEARCH INTENT (Nguyên nhân, sự cố, nhật ký)
# ==============================================================================
VECTOR_TEST_QUESTIONS = [
    "Nguyên nhân xảy ra sự cố tại dự án TITS-01 là gì?",
    "Tại sao công trình TITS-01 bị vướng mắc mặt bằng?",
    "Diễn biến thi công đổ bê tông ngày hôm qua tại TITS-01 ra sao?",
    "Nhat ky hien truong ngay 25 cua TITS-01 ghi gi?",  # Không dấu
    "Chi đạo xử lý của ban giám đốc đối với sự cố TITS-01",
    "Giải pháp khắc phục ngập nước hố móng ở TITS-02",
    "Biên bản hiện trường dự án TITS-01 có ghi nhận tai nạn nào không?",
    "Mô tả chi tiết vướng mắc kỹ thuật kéo cáp tại DA-01",
    "Thời tiết mưa lớn ảnh hưởng như thế nào đến công trường TITS-01?",
    "Ly do tai sao chu dau tu chua ban giao tim moc o TITS-01",  # Không dấu
    "Thảo luận kỹ thuật về việc uốn cong cáp điện 22kV",
    "Ghi chú hiện trường về việc kiểm tra cốt thép cột trục A-B",
    "Kiến nghị của kỹ sư giám sát tại TRAM_BIEN_AP_500KV",
    "Tình hình thi công hiện tại ở công trường TITS-01 diễn ra như thế nào?",
    "Có sự cố kỹ thuật nào phát sinh tại trạm biến áp không?",
]

@pytest.mark.parametrize("q", VECTOR_TEST_QUESTIONS)
def test_vector_search_intent_classification(router, q):
    plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
    assert plan.intent == QueryIntent.VECTOR_SEARCH, f"Câu '{q}' phải có intent VECTOR_SEARCH, nhận: {plan.intent}"
    assert plan.vector_query is not None
    assert plan.sql_operation is None


# ==============================================================================
# 3. 10 TEST CASES FOR HYBRID INTENT (Số liệu + Lý do/Sự cố kết hợp)
# ==============================================================================
HYBRID_TEST_QUESTIONS = [
    "Dự án TITS-01 chậm tiến độ bao nhiêu phần trăm và nguyên nhân là gì?",
    "Có bao nhiêu task trễ hạn tại TITS-01 và lý do vì sao bị chậm?",
    "Tỉ lệ hoàn thành của DA-01 là bao nhiêu, tại sao công việc chưa làm xong?",
    "Du an TITS-01 dat bao nhieu phan tram tien do, vi sao cham?",  # Không dấu
    "Các công việc chậm tiến độ ở TITS-02 có những sự cố kỹ thuật nào ghi trong nhật ký?",
    "Tổng số sự cố phát sinh tại TITS-01 và tình hình diễn biến xử lý ra sao?",
    "Khối lượng thi công đạt bao nhiêu, tại sao lại có vướng mắc mặt bằng?",
    "Thống kê các task trễ hạn và giải pháp khắc phục hiện trường ở TRAM_BIEN_AP_500KV",
    "Chi phí vượt ngân sách bao nhiêu và nguyên nhân do sự cố nào gây ra?",
    "Tiến độ công việc TITS-01 như thế nào, có biên bản ghi nhận chậm trễ không?",
]

@pytest.mark.parametrize("q", HYBRID_TEST_QUESTIONS)
def test_hybrid_intent_classification(router, q):
    plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
    assert plan.intent == QueryIntent.HYBRID, f"Câu '{q}' phải có intent HYBRID, nhận: {plan.intent}"
    assert plan.sql_operation is not None
    assert plan.vector_query is not None


# ==============================================================================
# 4. FAIL-CLOSED, INJECTION, UNSUPPORTED & EDGE CASES (15+ TEST CASES)
# ==============================================================================
def test_fail_closed_empty_allowed_projects(router):
    """Khi người dùng không có quyền truy cập bất kỳ dự án nào (rỗng) -> Trả về UNSUPPORTED."""
    plan = router.route("Tiến độ dự án TITS-01 là bao nhiêu?", allowed_project_codes=set())
    assert plan.intent == QueryIntent.UNSUPPORTED
    assert "Fail-closed" in plan.reasons[0]


def test_unauthorized_project_access(router):
    """Truy vấn vào dự án không thuộc danh sách được cấp quyền -> Trả về UNSUPPORTED."""
    plan = router.route("Tiến độ dự án SECRET_PROJECT_99 là bao nhiêu?", allowed_project_codes={"TITS-01"})
    assert plan.intent == QueryIntent.UNSUPPORTED
    assert "Không có quyền truy cập" in plan.reasons[0]


def test_empty_question(router):
    plan = router.route("   ", allowed_project_codes=ALLOWED_PROJECTS)
    assert plan.intent == QueryIntent.UNSUPPORTED
    assert "Câu hỏi rỗng" in plan.reasons[0]


def test_raw_sql_injection_attempts(router):
    injections = [
        "TITS-01; DROP TABLE projects;--",
        "SELECT * FROM tasks WHERE 1=1",
        "TITS-01' UNION SELECT id, password FROM users --",
        "EXEC sp_executesql 'delete from issues'",
    ]
    for q in injections:
        plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
        assert plan.intent == QueryIntent.UNSUPPORTED


def test_mutation_requests_rejected(router):
    mutations = [
        "Hãy xóa công việc số 5 trong dự án TITS-01",
        "Sửa tiến độ dự án TITS-01 thành 100%",
        "Cập nhật dữ liệu chi phí cho dự án DA-01",
        "Thêm mới một nhật ký hiện trường cho TITS-01",
    ]
    for q in mutations:
        plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
        assert plan.intent == QueryIntent.UNSUPPORTED


def test_off_topic_questions_rejected(router):
    off_topics = [
        "Thời tiết Hà Nội hôm nay thế nào?",
        "Giá vàng hôm nay tăng hay giảm?",
        "Hãy làm một bài thơ về xây dựng",
        "Kết quả bóng đá Ngoại Hạng Anh tối qua",
    ]
    for q in off_topics:
        plan = router.route(q, allowed_project_codes=ALLOWED_PROJECTS)
        assert plan.intent == QueryIntent.UNSUPPORTED


def test_prefix_collision_and_boundary_matching(router):
    """
    Kiểm tra chống prefix collision:
    - Nếu được cấp quyền TITS-01 nhưng câu hỏi hỏi về TITS-010 -> Không được nhận diện nhầm là TITS-01.
    """
    # Người dùng chỉ có quyền TITS-01
    allowed = {"TITS-01"}
    # Câu hỏi về TITS-010 (dự án ngoài quyền)
    plan = router.route("Tiến độ của dự án TITS-010 là bao nhiêu?", allowed_project_codes=allowed)
    assert plan.intent == QueryIntent.UNSUPPORTED
    assert plan.project_code == "TITS-010"
    assert "Không có quyền truy cập" in plan.reasons[0]


def test_multiple_projects_in_question_deterministic(router):
    """Kiểm tra xử lý khi câu hỏi chứa nhiều mã dự án theo thứ tự tất định (Longest match first)."""
    allowed = {"TITS-01", "TITS-01-SUB"}
    plan = router.route("So sánh tiến độ giữa TITS-01 và TITS-01-SUB", allowed_project_codes=allowed)
    # Longest match first ưu tiên mã đặc thù TITS-01-SUB
    assert plan.project_code == "TITS-01-SUB"


def test_router_determinism(router):
    """Kiểm tra tính tất định: cùng 1 câu hỏi gọi 5 lần liên tiếp phải cho kết quả giống hệt 100%."""
    q = "Dự án TITS-01 chậm tiến độ bao nhiêu phần trăm và nguyên nhân là gì?"
    plans = [router.route(q, allowed_project_codes=ALLOWED_PROJECTS) for _ in range(5)]
    first_dict = plans[0].model_dump()
    for p in plans[1:]:
        assert p.model_dump() == first_dict
