"""Comprehensive unit and regression tests for PromptSynthesizer and ResponseFormatter."""
import pytest
from titsmart_ai.domain.chat import ChatResponse, ChatSource
from titsmart_ai.domain.documents import SearchResult
from titsmart_ai.domain.models import Project, Task, Issue
from titsmart_ai.router.query_router import QueryIntent, QueryRouter
from titsmart_ai.security.auth import AuthContext
from titsmart_ai.synthesis.prompt_synthesizer import (
    PromptSynthesizer,
    SynthesizedPrompt,
    SYSTEM_PROMPT_TEMPLATE,
)
from titsmart_ai.synthesis.response_formatter import ResponseFormatter
from titsmart_ai.domain.chat_engine import ChatEngine
from titsmart_ai.tools.query_tool import InMemoryDataQueryTool
from titsmart_ai.tools.vector_store import InMemoryVectorStore, DeterministicFakeEmbeddingProvider
from titsmart_ai.domain.documents import TextChunk


# ==============================================================================
# FIXTURES
# ==============================================================================
@pytest.fixture
def sample_project_summary():
    return {
        "project_code": "TITS-01",
        "project_name": "Tòa nhà Văn phòng TITSmart Tower",
        "status": "Đang thi công",
        "average_progress": 68.5,
        "total_tasks": 12,
        "total_volume": 450.0,
        "total_issues": 2,
        "contract_value": 15000000.0,
    }


@pytest.fixture
def sample_delayed_tasks():
    return [
        Task(
            id="task-101",
            project_code="TITS-01",
            name="Thi công đài móng và giằng móng",
            volume=120.0,
            progress=40.0,
            status="Chậm tiến độ",
        ),
        Task(
            id="task-102",
            project_code="TITS-01",
            name="Lắp đặt hệ thống tiếp địa chống sét",
            volume=35.0,
            progress=75.0,
            status="Đang thi công",
        ),
    ]


@pytest.fixture
def sample_progress_summaries():
    return [
        {
            "project_code": "TITS-01",
            "total_tasks": 10,
            "completed_tasks": 6,
            "in_progress_tasks": 3,
            "not_started_tasks": 1,
            "overall_completion_rate": 60.0,
        },
        {
            "project_code": "TITS-02",
            "total_tasks": 20,
            "completed_tasks": 15,
            "in_progress_tasks": 5,
            "not_started_tasks": 0,
            "overall_completion_rate": 75.0,
        },
    ]


@pytest.fixture
def sample_vector_results():
    return [
        SearchResult(
            id="chunk-01",
            document_id="doc-01",
            content="Nhật ký ngày 15/10: Thời tiết mưa lớn gây ngập hố móng, buộc tạm dừng công tác đổ bê tông.",
            source_table="field_logs",
            record_id="log-001",
            project_code="TITS-01",
            score=0.895,
        ),
        SearchResult(
            id="chunk-02",
            document_id="doc-02",
            content="Sự cố kỹ thuật: Thiếu thép D25 tại công trường dẫn đến chậm tiến độ lắp dựng cốt thép dầm sàn.",
            source_table="issues",
            record_id="iss-042",
            project_code="TITS-01",
            score=0.842,
        ),
    ]


@pytest.fixture
def mock_engine_suite():
    projects = [
        Project(id="p1", code="TITS-01", name="TITSmart Office", contract_value=5000.0, progress_percent=70.0),
        Project(id="p2", code="TITS-02", name="TITSmart Factory", contract_value=8000.0, progress_percent=30.0),
    ]
    tasks = [
        Task(id="t1", project_code="TITS-01", name="Thi công cọc khoan nhồi", volume=100.0, progress=70.0, status="Đang làm"),
        Task(id="t2", project_code="TITS-01", name="Đổ bê tông sàn tầng hầm", volume=200.0, progress=100.0, status="Hoàn thành"),
        Task(id="t3", project_code="TITS-02", name="Gia công kết cấu thép", volume=150.0, progress=25.0, status="Đang làm"),
    ]
    issues = [
        Issue(id="i1", project_code="TITS-01", title="Chậm cấp thép", description="Nhà thầu phụ giao chậm thép phi 20", priority="HIGH", status="OPEN")
    ]
    query_tool = InMemoryDataQueryTool(projects=projects, tasks=tasks, issues=issues)
    router = QueryRouter(known_projects={"TITS-01", "TITS-02"})
    embedding_provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    vector_store = InMemoryVectorStore(expected_dimensions=384)

    chunk = TextChunk(
        id="chk_log1",
        document_id="doc_fl1",
        content="Nhật ký thi công: Máy xúc hỏng bơm thủy lực tại hố móng TITS-01",
        source_table="field_logs",
        record_id="fl_01",
        project_code="TITS-01",
        chunk_index=0,
    )
    vec = embedding_provider.embed([chunk.content])
    vector_store.upsert([chunk], vec)

    synthesizer = PromptSynthesizer()
    formatter = ResponseFormatter()
    engine = ChatEngine(
        router=router,
        query_tool=query_tool,
        vector_store=vector_store,
        embedding_provider=embedding_provider,
        prompt_synthesizer=synthesizer,
        response_formatter=formatter,
    )
    return engine, synthesizer, formatter


# ==============================================================================
# 1. UNIT TESTS: PromptSynthesizer
# ==============================================================================
class TestPromptSynthesizer:

    def test_system_prompt_principles(self):
        synthesizer = PromptSynthesizer()
        prompt = synthesizer.build_system_prompt()
        assert "ZERO HALLUCINATION" in prompt
        assert "FAIL-CLOSED" in prompt
        assert "GROUNDING & CITATIONS" in prompt
        assert "VĂN PHONG KỸ THUẬT XÂY DỰNG" in prompt

    def test_custom_system_template(self):
        custom_template = "Chỉ dẫn kỹ thuật đặc thù cho kiểm toán công trình độc lập."
        synthesizer = PromptSynthesizer(system_template=custom_template)
        assert synthesizer.build_system_prompt() == custom_template

    def test_format_sql_context_single_project(self, sample_project_summary, sample_delayed_tasks):
        synthesizer = PromptSynthesizer()
        ctx = synthesizer.format_sql_context(
            summary=sample_project_summary,
            delayed_tasks=sample_delayed_tasks,
        )
        assert "Dự án: Tòa nhà Văn phòng TITSmart Tower (Mã: TITS-01)" in ctx
        assert "- Trạng thái dự án: Đang thi công" in ctx
        assert "- Tiến độ trung bình: 68.5%" in ctx
        assert "- Tổng số công việc: 12" in ctx
        assert "- Tổng khối lượng thi công: 450.0" in ctx
        assert "- Giá trị hợp đồng: 15,000,000.00" in ctx
        assert "Danh sách 2 công việc chưa hoàn thành / chậm tiến độ:" in ctx
        assert "Task [task-101] 'Thi công đài móng và giằng móng': Tiến độ 40.0%" in ctx
        assert "Task [task-102] 'Lắp đặt hệ thống tiếp địa chống sét': Tiến độ 75.0%" in ctx

    def test_format_sql_context_progress_summaries(self, sample_progress_summaries):
        synthesizer = PromptSynthesizer()
        ctx = synthesizer.format_sql_context(progress_summaries=sample_progress_summaries)
        assert "Thống kê phân bổ tiến độ theo từng dự án được cấp quyền:" in ctx
        assert "Dự án TITS-01: Tổng tasks=10, Hoàn thành=6, Đang làm=3, Chưa làm=1, Tỉ lệ HT=60.0%" in ctx
        assert "Dự án TITS-02: Tổng tasks=20, Hoàn thành=15, Đang làm=5, Chưa làm=0, Tỉ lệ HT=75.0%" in ctx

    def test_format_sql_context_empty(self):
        synthesizer = PromptSynthesizer()
        ctx = synthesizer.format_sql_context()
        assert ctx == "Không có dữ liệu số liệu SQL phù hợp."

    def test_format_vector_context(self, sample_vector_results):
        synthesizer = PromptSynthesizer()
        ctx = synthesizer.format_vector_context(sample_vector_results)
        assert "[Bằng chứng 1] (Bảng: field_logs | Bản ghi: log-001 | Dự án: TITS-01 | Điểm tương đồng: 0.8950):" in ctx
        assert "Thời tiết mưa lớn gây ngập hố móng" in ctx
        assert "[Bằng chứng 2] (Bảng: issues | Bản ghi: iss-042 | Dự án: TITS-01 | Điểm tương đồng: 0.8420):" in ctx
        assert "Thiếu thép D25 tại công trường" in ctx

    def test_format_vector_context_empty(self):
        synthesizer = PromptSynthesizer()
        assert synthesizer.format_vector_context([]) == "Không có tài liệu nhật ký hay sự cố nào được tìm thấy."
        assert synthesizer.format_vector_context(None) == "Không có tài liệu nhật ký hay sự cố nào được tìm thấy."

    def test_estimate_tokens(self):
        synthesizer = PromptSynthesizer()
        assert synthesizer.estimate_tokens("") == 0
        assert synthesizer.estimate_tokens("   ") == 0
        assert synthesizer.estimate_tokens("Ngắn") >= 1
        long_text = "Tiến độ dự án xây dựng cần được kiểm soát chặt chẽ theo từng giai đoạn nghiệm thu." * 10
        tokens = synthesizer.estimate_tokens(long_text)
        assert tokens > 50
        assert isinstance(tokens, int)

    def test_synthesize_sql_intent(self, sample_project_summary, sample_delayed_tasks):
        synthesizer = PromptSynthesizer()
        result = synthesizer.synthesize(
            question="Tiến độ dự án TITS-01 hiện nay ra sao?",
            intent=QueryIntent.SQL,
            summary=sample_project_summary,
            delayed_tasks=sample_delayed_tasks,
            project_code="TITS-01",
            allowed_project_codes={"TITS-01", "TITS-02"},
        )
        assert isinstance(result, SynthesizedPrompt)
        assert result.intent == QueryIntent.SQL
        assert result.user_prompt == "Tiến độ dự án TITS-01 hiện nay ra sao?"
        assert result.token_estimate > 0
        assert "Dự án: Tòa nhà Văn phòng TITSmart Tower" in result.sql_context
        assert result.vector_context == ""
        assert "### RETRIEVED CONTEXT ###" in result.full_prompt
        assert "[KHỐI DỮ LIỆU SỐ LIỆU & TIẾN ĐỘ THI CÔNG (SQL)]:" in result.full_prompt
        assert result.metadata["intent"] == "sql"
        assert result.metadata["has_sql_context"] is True
        assert result.metadata["has_vector_context"] is False
        assert result.metadata["project_code"] == "TITS-01"
        assert result.metadata["allowed_project_codes"] == ["TITS-01", "TITS-02"]

    def test_synthesize_vector_intent(self, sample_vector_results):
        synthesizer = PromptSynthesizer()
        result = synthesizer.synthesize(
            question="Có sự cố gì phát sinh ở hiện trường TITS-01?",
            intent=QueryIntent.VECTOR_SEARCH,
            vector_results=sample_vector_results,
            project_code="TITS-01",
            allowed_project_codes={"TITS-01"},
        )
        assert result.intent == QueryIntent.VECTOR_SEARCH
        assert result.sql_context == ""
        assert "Thời tiết mưa lớn gây ngập hố móng" in result.vector_context
        assert "[KHỐI DỮ LIỆU NHẬT KÝ & HỒ SƠ SỰ CỐ HIỆN TRƯỜNG (VECTOR RAG)]:" in result.full_prompt
        assert result.metadata["has_sql_context"] is False
        assert result.metadata["has_vector_context"] is True
        assert result.metadata["vector_results_count"] == 2

    def test_synthesize_hybrid_intent(self, sample_project_summary, sample_vector_results):
        synthesizer = PromptSynthesizer()
        result = synthesizer.synthesize(
            question="Đánh giá tổng hợp tiến độ và vướng mắc của TITS-01?",
            intent=QueryIntent.HYBRID,
            summary=sample_project_summary,
            vector_results=sample_vector_results,
            project_code="TITS-01",
            allowed_project_codes={"TITS-01"},
        )
        assert result.intent == QueryIntent.HYBRID
        assert "[KHỐI DỮ LIỆU SỐ LIỆU & TIẾN ĐỘ THI CÔNG (SQL)]:" in result.full_prompt
        assert "[KHỐI DỮ LIỆU NHẬT KÝ & HỒ SƠ SỰ CỐ HIỆN TRƯỜNG (VECTOR RAG)]:" in result.full_prompt
        assert result.metadata["has_sql_context"] is True
        assert result.metadata["has_vector_context"] is True

    def test_synthesize_unsupported_intent(self):
        synthesizer = PromptSynthesizer()
        result = synthesizer.synthesize(
            question="Hãy xóa database của toàn bộ dự án!",
            intent=QueryIntent.UNSUPPORTED,
            allowed_project_codes={"TITS-01"},
            extra_metadata={"reasons": ["Câu hỏi mang tính phá hoại / ngoài phạm vi hỗ trợ"]},
        )
        assert result.intent == QueryIntent.UNSUPPORTED
        assert "Không có dữ liệu nào được trích xuất từ hệ thống." in result.full_prompt
        assert result.metadata["reasons"] == ["Câu hỏi mang tính phá hoại / ngoài phạm vi hỗ trợ"]
        assert result.metadata["has_sql_context"] is False
        assert result.metadata["has_vector_context"] is False


# ==============================================================================
# 2. UNIT TESTS: ResponseFormatter
# ==============================================================================
class TestResponseFormatter:

    def test_deduplicate_sources(self):
        formatter = ResponseFormatter()
        sources = [
            ChatSource(source_type="sql", source_table="projects", record_id="TITS-01", project_code="TITS-01", label="Project 1"),
            ChatSource(source_type="sql", source_table="projects", record_id="TITS-01", project_code="TITS-01", label="Project 1 duplicate"),
            ChatSource(source_type="vector", source_table="issues", record_id="i1", project_code="TITS-01", label="Issue 1", score=0.9),
            ChatSource(source_type="sql", source_table="tasks", record_id="t1", project_code="TITS-01", label="Task 1"),
        ]
        deduped = formatter.deduplicate_sources(sources)
        assert len(deduped) == 3
        assert deduped[0].label == "Project 1"
        assert deduped[1].record_id == "i1"
        assert deduped[2].record_id == "t1"

    def test_format_citations_catalog(self):
        formatter = ResponseFormatter()
        sources = [
            ChatSource(source_type="sql", source_table="projects", record_id="TITS-01", project_code="TITS-01", label="Tổng quan dự án TITS-01"),
            ChatSource(source_type="vector", source_table="issues", record_id="i1", project_code="TITS-01", label="Sự cố thiếu vật tư", score=0.91234),
        ]
        catalog = formatter.format_citations_catalog(sources)
        assert ResponseFormatter.CITATIONS_HEADER in catalog
        assert "- [Nguồn 1] (SQL: projects/TITS-01 | Dự án: TITS-01): Tổng quan dự án TITS-01" in catalog
        assert "- [Nguồn 2] (VECTOR: issues/i1 | Dự án: TITS-01 | Điểm tương quan: 0.9123): Sự cố thiếu vật tư" in catalog

    def test_format_citations_catalog_empty(self):
        formatter = ResponseFormatter()
        assert formatter.format_citations_catalog([]) == ""

    def test_validate_citations(self):
        formatter = ResponseFormatter()
        valid_sources = [
            ChatSource(source_type="sql", source_table="tasks", record_id="t1", project_code="TITS-01", label="Task 1"),
            ChatSource(source_type="vector", source_table="field_logs", record_id="fl1", project_code="TITS-01", label="Log 1"),
        ]
        assert formatter.validate_citations(valid_sources) is True
        assert formatter.validate_citations([]) is True
        assert formatter.validate_citations("invalid_input") is False  # type: ignore

    def test_validate_citations_rejection(self):
        formatter = ResponseFormatter()
        bad_source_list = [
            {"source_type": "sql", "source_table": "tasks", "record_id": "t1", "project_code": "TITS-01", "label": "Task 1"}  # not ChatSource
        ]
        assert formatter.validate_citations(bad_source_list) is False  # type: ignore

    def test_format_sql_project_summary(self, sample_project_summary, sample_delayed_tasks):
        formatter = ResponseFormatter()
        res = formatter.format_sql_project_summary(sample_project_summary, delayed_tasks=sample_delayed_tasks)
        assert isinstance(res, ChatResponse)
        assert res.intent == QueryIntent.SQL
        assert res.has_evidence is True
        assert "Thông tin dự án Tòa nhà Văn phòng TITSmart Tower (TITS-01):" in res.answer
        assert "- Tiến độ trung bình: 68.5%" in res.answer
        assert "Danh sách 2 công việc chưa hoàn thành:" in res.answer
        assert ResponseFormatter.CITATIONS_HEADER in res.answer
        assert any(s.source_table == "projects" for s in res.sources)
        assert any(s.source_table == "tasks" for s in res.sources)

    def test_format_sql_project_summary_without_citations(self, sample_project_summary):
        formatter = ResponseFormatter()
        res = formatter.format_sql_project_summary(sample_project_summary, append_citations=False)
        assert ResponseFormatter.CITATIONS_HEADER not in res.answer
        assert len(res.sources) == 1

    def test_format_sql_aggregate_progress(self, sample_progress_summaries):
        formatter = ResponseFormatter()
        res = formatter.format_sql_aggregate_progress(
            sample_progress_summaries,
            allowed_projects={"TITS-01", "TITS-02"},
        )
        assert res.intent == QueryIntent.SQL
        assert res.has_evidence is True
        assert "- Tổng số công việc: 30" in res.answer  # 10 + 20
        assert "- Đã hoàn thành: 21" in res.answer      # 6 + 15
        assert "- Đang thực hiện: 8" in res.answer      # 3 + 5
        assert "- Tỷ lệ hoàn thành chung: 70.0%" in res.answer  # 21/30 * 100
        assert len(res.sources) == 2
        assert ResponseFormatter.CITATIONS_HEADER in res.answer

    def test_format_vector_response(self, sample_vector_results):
        formatter = ResponseFormatter()
        res = formatter.format_vector_response(sample_vector_results)
        assert res.intent == QueryIntent.VECTOR_SEARCH
        assert res.has_evidence is True
        assert "Thời tiết mưa lớn gây ngập hố móng" in res.answer
        assert ResponseFormatter.CITATIONS_HEADER in res.answer
        assert len(res.sources) == 2

    def test_format_vector_response_empty(self):
        formatter = ResponseFormatter()
        res = formatter.format_vector_response([])
        assert res.intent == QueryIntent.VECTOR_SEARCH
        assert res.has_evidence is False
        assert "Không tìm thấy dữ liệu" in res.answer
        assert res.sources == []
        assert ResponseFormatter.CITATIONS_HEADER not in res.answer

    def test_format_hybrid_response(self, sample_project_summary, sample_vector_results):
        formatter = ResponseFormatter()
        sql_res = formatter.format_sql_project_summary(sample_project_summary)
        vec_res = formatter.format_vector_response(sample_vector_results)

        hybrid_res = formatter.format_hybrid_response(sql_res, vec_res)
        assert hybrid_res.intent == QueryIntent.HYBRID
        assert hybrid_res.has_evidence is True
        assert "=== BÁO CÁO TỔNG HỢP (HYBRID SQL + RAG) ===" in hybrid_res.answer
        assert "[1. Số liệu tiến độ & công việc]:" in hybrid_res.answer
        assert "[2. Nhật ký & nguyên nhân thực tế]:" in hybrid_res.answer

        # Chỉ có duy nhất 1 header trích dẫn ở cuối
        assert hybrid_res.answer.count(ResponseFormatter.CITATIONS_HEADER) == 1
        assert len(hybrid_res.sources) == len(sql_res.sources) + len(vec_res.sources)

    def test_format_hybrid_response_missing_one_side(self, sample_project_summary):
        formatter = ResponseFormatter()
        sql_res = formatter.format_sql_project_summary(sample_project_summary)
        vec_res = formatter.format_vector_response([])  # No vector evidence

        hybrid_res = formatter.format_hybrid_response(sql_res, vec_res)
        assert hybrid_res.has_evidence is True  # SQL has evidence
        assert any("Không tìm thấy nhật ký/sự cố" in w for w in hybrid_res.warnings)

    def test_format_unsupported_and_no_evidence(self):
        formatter = ResponseFormatter()
        unsup = formatter.format_unsupported("Từ chối truy cập dự án ngoài quyền hạn.")
        assert unsup.intent == QueryIntent.UNSUPPORTED
        assert unsup.has_evidence is False
        assert unsup.sources == []

        no_ev = formatter.format_no_evidence("Dữ liệu trống.", intent=QueryIntent.SQL)
        assert no_ev.intent == QueryIntent.SQL
        assert no_ev.has_evidence is False

    def test_standardize_technical_answer(self):
        formatter = ResponseFormatter()
        source = ChatSource(source_type="sql", source_table="projects", record_id="TITS-01", project_code="TITS-01", label="Dự án 1")
        res = formatter.standardize_technical_answer(
            answer_text="   Báo cáo kỹ thuật sơ bộ   ",
            sources=[source, source],  # Duplicate sources
            intent=QueryIntent.SQL,
        )
        assert res.answer.startswith("Báo cáo kỹ thuật sơ bộ")
        assert len(res.sources) == 1
        assert ResponseFormatter.CITATIONS_HEADER in res.answer

        # Test idempotency (doesn't duplicate citations header if already present)
        res2 = formatter.standardize_technical_answer(
            answer_text=res.answer,
            sources=res.sources,
            intent=QueryIntent.SQL,
        )
        assert res2.answer.count(ResponseFormatter.CITATIONS_HEADER) == 1


# ==============================================================================
# 3. REGRESSION & INTEGRATION TESTS: ChatEngine Integration
# ==============================================================================
class TestChatEngineSynthesisRegression:

    def test_chat_engine_synthesize_prompt_sql(self, mock_engine_suite):
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="eng_01", allowed_project_codes={"TITS-01"})
        prompt = engine.synthesize_prompt("Tiến độ của dự án TITS-01 là bao nhiêu?", auth)

        assert isinstance(prompt, SynthesizedPrompt)
        assert prompt.intent == QueryIntent.SQL
        assert "TITS-01" in prompt.sql_context
        assert prompt.vector_context == ""
        assert prompt.metadata["has_sql_context"] is True
        assert prompt.metadata["has_vector_context"] is False
        assert prompt.metadata["project_code"] == "TITS-01"

    def test_chat_engine_synthesize_prompt_vector(self, mock_engine_suite):
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="eng_01", allowed_project_codes={"TITS-01"})
        prompt = engine.synthesize_prompt("Ghi nhận nhật ký sự cố máy móc tại TITS-01 là gì?", auth)

        assert prompt.intent == QueryIntent.VECTOR_SEARCH
        assert "Máy xúc hỏng bơm thủy lực" in prompt.vector_context
        assert prompt.metadata["has_vector_context"] is True
        assert prompt.metadata["vector_results_count"] >= 1

    def test_chat_engine_synthesize_prompt_hybrid(self, mock_engine_suite):
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="eng_01", allowed_project_codes={"TITS-01"})
        prompt = engine.synthesize_prompt("Tiến độ TITS-01 thế nào và nguyên nhân vì sao bị chậm?", auth)

        assert prompt.intent == QueryIntent.HYBRID
        assert prompt.metadata["has_sql_context"] is True
        assert prompt.metadata["has_vector_context"] is True
        assert "KHỐI DỮ LIỆU SỐ LIỆU & TIẾN ĐỘ THI CÔNG (SQL)" in prompt.full_prompt
        assert "KHỐI DỮ LIỆU NHẬT KÝ & HỒ SƠ SỰ CỐ HIỆN TRƯỜNG (VECTOR RAG)" in prompt.full_prompt

    def test_chat_engine_synthesize_prompt_fail_closed_empty_projects(self, mock_engine_suite):
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="guest", allowed_project_codes=set())
        prompt = engine.synthesize_prompt("Tiến độ TITS-01?", auth)

        assert prompt.intent == QueryIntent.UNSUPPORTED
        assert prompt.metadata["has_sql_context"] is False
        assert prompt.metadata["has_vector_context"] is False
        assert "allowed_project_codes rỗng" in prompt.metadata.get("reasons", [""])[0]

    def test_chat_engine_synthesize_prompt_fail_closed_unauthorized_project(self, mock_engine_suite):
        """User chỉ có quyền TITS-02 nhưng hỏi TITS-01 -> Không được tổng hợp prompt của TITS-01."""
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="user_tits02", allowed_project_codes={"TITS-02"})
        prompt = engine.synthesize_prompt("Tiến độ của dự án TITS-01 là bao nhiêu?", auth)

        assert prompt.intent == QueryIntent.UNSUPPORTED
        assert "TITS-01" not in prompt.sql_context
        assert prompt.metadata["has_sql_context"] is False
        assert prompt.metadata["has_vector_context"] is False

    def test_chat_engine_answer_transparent_citations(self, mock_engine_suite):
        """Đảm bảo mọi câu trả lời có bằng chứng đều đính kèm danh mục trích dẫn minh bạch."""
        engine, _, _ = mock_engine_suite
        auth = AuthContext(user_id="eng_01", allowed_project_codes={"TITS-01"})

        res_sql = engine.answer("Tiến độ TITS-01?", auth)
        assert res_sql.has_evidence is True
        assert ResponseFormatter.CITATIONS_HEADER in res_sql.answer
        assert all(s.source_type == "sql" for s in res_sql.sources)

        res_vec = engine.answer("Nhật ký sự cố máy móc tại TITS-01?", auth)
        assert res_vec.has_evidence is True
        assert ResponseFormatter.CITATIONS_HEADER in res_vec.answer
        assert all(s.source_type == "vector" for s in res_vec.sources)

        res_hybrid = engine.answer("Tiến độ TITS-01 và nguyên nhân vì sao bị chậm?", auth)
        assert res_hybrid.has_evidence is True
        assert ResponseFormatter.CITATIONS_HEADER in res_hybrid.answer
        assert any(s.source_type == "sql" for s in res_hybrid.sources)
        assert any(s.source_type == "vector" for s in res_hybrid.sources)

    def test_chat_engine_custom_formatter_synthesizer_injection(self, mock_engine_suite):
        """Xác nhận ChatEngine hỗ trợ Dependency Injection cho PromptSynthesizer và ResponseFormatter."""
        _, _, _ = mock_engine_suite
        custom_synth = PromptSynthesizer(system_template="Chỉ dẫn độc quyền")
        custom_formatter = ResponseFormatter()

        router = QueryRouter(known_projects={"TITS-01"})
        query_tool = InMemoryDataQueryTool(projects=[], tasks=[], issues=[])
        embedding_provider = DeterministicFakeEmbeddingProvider(dimensions=384)
        vector_store = InMemoryVectorStore(expected_dimensions=384)

        custom_engine = ChatEngine(
            router=router,
            query_tool=query_tool,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
            prompt_synthesizer=custom_synth,
            response_formatter=custom_formatter,
        )

        assert custom_engine.prompt_synthesizer is custom_synth
        assert custom_engine.response_formatter is custom_formatter
