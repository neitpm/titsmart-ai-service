"""Deterministic ChatEngine coordinating Router, DataQueryTool, VectorStore, PromptSynthesizer, ResponseFormatter, and LLMAdapter."""
from typing import Optional, List
from titsmart_ai.domain.chat import ChatResponse, ChatSource
from titsmart_ai.security.auth import AuthContext
from titsmart_ai.router.query_router import QueryRouter, QueryIntent, QueryPlan
from titsmart_ai.tools.query_tool import DataQueryTool
from titsmart_ai.tools.vector_store import VectorStore, EmbeddingProvider
from titsmart_ai.synthesis.prompt_synthesizer import PromptSynthesizer, SynthesizedPrompt
from titsmart_ai.synthesis.response_formatter import ResponseFormatter
from titsmart_ai.llm.llm_adapter import LLMAdapter, MockLLMAdapter
from titsmart_ai.llm.guardrails import LLMGuardrails


class ChatEngine:
    """
    Bộ máy thực thi Chat Hybrid kết hợp QueryRouter, SQL Analytics, Vector RAG,
    PromptSynthesizer và ResponseFormatter:
    - Điều phối luồng xử lý: AuthContext -> QueryRouter -> Retrieval -> Synthesis & Response Formatting.
    - Hoàn toàn tất định (Deterministic Template Engine), bảo đảm Grounding và Zero Hallucination.
    - Bảo mật Fail-Closed: Chỉ truy vấn và tổng hợp trong allowed_project_codes từ AuthContext.
    """

    def __init__(
        self,
        router: QueryRouter,
        query_tool: DataQueryTool,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        prompt_synthesizer: Optional[PromptSynthesizer] = None,
        response_formatter: Optional[ResponseFormatter] = None,
        llm_adapter: Optional[LLMAdapter] = None,
    ):
        self.router = router
        self.query_tool = query_tool
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider
        self.prompt_synthesizer = prompt_synthesizer or PromptSynthesizer()
        self.response_formatter = response_formatter or ResponseFormatter()
        self.llm_adapter = llm_adapter or MockLLMAdapter(response_formatter=self.response_formatter)

    def answer(self, question: str, auth_context: AuthContext) -> ChatResponse:
        # 1. FAIL-CLOSED: Kiểm tra quyền dự án của user
        if not auth_context.allowed_project_codes:
            return self.response_formatter.format_unsupported(
                "Bạn chưa được phân quyền truy cập vào bất kỳ dự án nào. Vui lòng liên hệ quản trị viên.",
                warnings=["Người dùng không có quyền truy cập dự án (allowed_project_codes rỗng)"],
            )

        # 2. Guardrail phát hiện prompt injection trong câu hỏi
        is_inj, inj_msg = LLMGuardrails.detect_injection(question)
        if is_inj:
            return self.response_formatter.format_unsupported(
                f"Yêu cầu bị từ chối do vi phạm chính sách an toàn thông tin: {inj_msg}",
                warnings=[inj_msg or "Prompt Injection Detected"],
            )

        # 3. Định tuyến câu hỏi qua QueryRouter
        plan: QueryPlan = self.router.route(
            question, allowed_project_codes=auth_context.allowed_project_codes
        )

        if plan.intent == QueryIntent.UNSUPPORTED:
            return self.response_formatter.format_unsupported(
                f"Yêu cầu không được hỗ trợ hoặc nằm ngoài phạm vi quyền hạn: {'; '.join(plan.reasons)}",
                warnings=plan.reasons,
            )

        # 3. Phân luồng thực thi dựa trên Intent
        if plan.intent == QueryIntent.SQL:
            return self._handle_sql_intent(plan, auth_context)
        elif plan.intent == QueryIntent.VECTOR_SEARCH:
            return self._handle_vector_intent(plan, auth_context)
        elif plan.intent == QueryIntent.HYBRID:
            return self._handle_hybrid_intent(plan, auth_context)

        return self.response_formatter.format_no_evidence(
            "Không tìm thấy dữ liệu phù hợp.",
            intent=plan.intent,
        )

    def answer_with_llm(self, question: str, auth_context: AuthContext) -> ChatResponse:
        """
        Thực thi câu trả lời thông qua LLM (Mock/Staging) kết hợp Guardrails:
        - ACL lọc dữ liệu trước khi gửi prompt.
        - Kháng Prompt Injection.
        - Backend-driven sources thu thập độc lập.
        - Citation Post-Validation chống bịa nguồn.
        - Fail-closed khi không có bằng chứng (has_evidence=False).
        """
        # 1. FAIL-CLOSED: Kiểm tra quyền dự án của user
        if not auth_context.allowed_project_codes:
            return self.response_formatter.format_unsupported(
                "Bạn chưa được phân quyền truy cập vào bất kỳ dự án nào. Vui lòng liên hệ quản trị viên.",
                warnings=["Người dùng không có quyền truy cập dự án (allowed_project_codes rỗng)"],
            )

        # 2. Guardrail phát hiện prompt injection trong câu hỏi
        is_inj, inj_msg = LLMGuardrails.detect_injection(question)
        if is_inj:
            return self.response_formatter.format_unsupported(
                f"Yêu cầu bị từ chối do vi phạm chính sách an toàn thông tin: {inj_msg}",
                warnings=[inj_msg or "Prompt Injection Detected"],
            )

        # 3. Định tuyến bằng QueryRouter
        plan: QueryPlan = self.router.route(
            question, allowed_project_codes=auth_context.allowed_project_codes
        )
        if plan.intent == QueryIntent.UNSUPPORTED:
            return self.response_formatter.format_unsupported(
                f"Yêu cầu không được hỗ trợ hoặc nằm ngoài phạm vi quyền hạn: {'; '.join(plan.reasons)}",
                warnings=plan.reasons,
            )

        # 4. Thu thập dữ liệu Backend & Sources đã được ACL xác thực
        summary = None
        delayed_tasks = None
        progress_summaries = None
        vector_results = None
        backend_sources: List[ChatSource] = []

        if plan.intent in (QueryIntent.SQL, QueryIntent.HYBRID):
            if plan.project_code:
                summary = self.query_tool.get_project_summary(plan.project_code)
                if summary:
                    backend_sources.append(
                        ChatSource(
                            source_type="sql",
                            source_table="projects",
                            record_id=plan.project_code,
                            project_code=plan.project_code,
                            label=f"Tổng quan dự án {plan.project_code}",
                        )
                    )
                if plan.sql_operation == "find_delayed_tasks":
                    delayed_tasks = self.query_tool.find_delayed_tasks(
                        project_code=plan.project_code, threshold=100.0
                    )
                    for t in (delayed_tasks or [])[:5]:
                        backend_sources.append(
                            ChatSource(
                                source_type="sql",
                                source_table="tasks",
                                record_id=t.id,
                                project_code=plan.project_code,
                                label=f"Task: {t.name}",
                            )
                        )
            else:
                progress_summaries = [
                    self.query_tool.get_progress_summary(project_code=p_code)
                    for p_code in sorted(auth_context.allowed_project_codes)
                ]
                for p_stat in progress_summaries:
                    p_code = p_stat.get("project_code")
                    if p_stat.get("total_tasks", 0) > 0 and p_code:
                        backend_sources.append(
                            ChatSource(
                                source_type="sql",
                                source_table="tasks",
                                record_id=f"progress_summary_{p_code}",
                                project_code=p_code,
                                label=f"Thống kê tiến độ dự án {p_code}",
                            )
                        )

        if plan.intent in (QueryIntent.VECTOR_SEARCH, QueryIntent.HYBRID):
            query_text = plan.vector_query or plan.normalized_question
            target_projects = {plan.project_code} if plan.project_code else auth_context.allowed_project_codes
            query_vec = self.embedding_provider.embed([query_text])[0]
            vector_results = self.vector_store.search(query_vec, project_codes=target_projects, top_k=3)
            for r in (vector_results or []):
                backend_sources.append(
                    ChatSource(
                        source_type="vector",
                        source_table=r.source_table,
                        record_id=r.record_id,
                        project_code=r.project_code,
                        label=f"Trích xuất {r.source_table} ({r.project_code})",
                        score=r.score,
                    )
                )

        backend_sources = self.response_formatter.deduplicate_sources(backend_sources)

        # 5. Nếu không có bằng chứng từ backend -> Fail-Closed từ chối ngay lập tức
        if not backend_sources and not summary and not progress_summaries and not vector_results:
            return self.response_formatter.format_no_evidence(
                "Không tìm thấy đủ bằng chứng hoặc dữ liệu phù hợp trong hệ thống để trả lời.",
                intent=plan.intent,
                warnings=["Không tìm thấy bằng chứng phù hợp (has_evidence=False)"],
            )

        # 6. Tổng hợp Prompt
        synthesized_prompt = self.prompt_synthesizer.synthesize(
            question=question,
            intent=plan.intent,
            summary=summary,
            delayed_tasks=delayed_tasks,
            progress_summaries=progress_summaries,
            vector_results=vector_results,
            project_code=plan.project_code,
            allowed_project_codes=auth_context.allowed_project_codes,
        )

        # 7. Gọi LLM Adapter
        return self.llm_adapter.generate(synthesized_prompt, backend_sources)

    def synthesize_prompt(self, question: str, auth_context: AuthContext) -> SynthesizedPrompt:
        """
        Tổng hợp Prompt Payload đầy đủ bao gồm System Prompt, SQL Context và Vector Context
        phục vụ kiểm toán, gỡ lỗi hoặc cung cấp cho LLM:
        - Bắt buộc kiểm tra quyền truy cập dự án theo AuthContext.
        """
        if not auth_context.allowed_project_codes:
            return self.prompt_synthesizer.synthesize(
                question=question,
                intent=QueryIntent.UNSUPPORTED,
                allowed_project_codes=auth_context.allowed_project_codes,
                extra_metadata={"reasons": ["Người dùng không có quyền truy cập dự án (allowed_project_codes rỗng)"]},
            )

        plan: QueryPlan = self.router.route(
            question, allowed_project_codes=auth_context.allowed_project_codes
        )

        if plan.intent == QueryIntent.UNSUPPORTED:
            return self.prompt_synthesizer.synthesize(
                question=question,
                intent=QueryIntent.UNSUPPORTED,
                project_code=plan.project_code,
                allowed_project_codes=auth_context.allowed_project_codes,
                extra_metadata={"reasons": plan.reasons},
            )

        summary = None
        delayed_tasks = None
        progress_summaries = None
        vector_results = None

        if plan.intent in (QueryIntent.SQL, QueryIntent.HYBRID):
            if plan.project_code:
                summary = self.query_tool.get_project_summary(plan.project_code)
                if plan.sql_operation == "find_delayed_tasks":
                    delayed_tasks = self.query_tool.find_delayed_tasks(
                        project_code=plan.project_code, threshold=100.0
                    )
            else:
                progress_summaries = [
                    self.query_tool.get_progress_summary(project_code=p_code)
                    for p_code in sorted(auth_context.allowed_project_codes)
                ]

        if plan.intent in (QueryIntent.VECTOR_SEARCH, QueryIntent.HYBRID):
            query_text = plan.vector_query or plan.normalized_question
            target_projects = {plan.project_code} if plan.project_code else auth_context.allowed_project_codes
            query_vec = self.embedding_provider.embed([query_text])[0]
            vector_results = self.vector_store.search(query_vec, project_codes=target_projects, top_k=3)

        return self.prompt_synthesizer.synthesize(
            question=question,
            intent=plan.intent,
            summary=summary,
            delayed_tasks=delayed_tasks,
            progress_summaries=progress_summaries,
            vector_results=vector_results,
            project_code=plan.project_code,
            allowed_project_codes=auth_context.allowed_project_codes,
        )

    def _handle_sql_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        target_code = plan.project_code

        if target_code:
            summary = self.query_tool.get_project_summary(target_code)
            if not summary:
                return self.response_formatter.format_no_evidence(
                    f"Không tìm thấy dữ liệu phù hợp cho dự án {target_code}.",
                    intent=QueryIntent.SQL,
                )

            delayed = None
            if plan.sql_operation == "find_delayed_tasks":
                delayed = self.query_tool.find_delayed_tasks(project_code=target_code, threshold=100.0)

            return self.response_formatter.format_sql_project_summary(summary, delayed_tasks=delayed)
        else:
            # Truy vấn tiến độ tổng hợp - TUYỆT ĐỐI CHỈ tổng hợp trong allowed_project_codes
            progress_stats = []
            for p_code in sorted(auth_context.allowed_project_codes):
                proj_stat = self.query_tool.get_progress_summary(project_code=p_code)
                progress_stats.append(proj_stat)

            return self.response_formatter.format_sql_aggregate_progress(
                progress_stats,
                allowed_projects=auth_context.allowed_project_codes,
            )

    def _handle_vector_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        query_text = plan.vector_query or plan.normalized_question
        target_projects = {plan.project_code} if plan.project_code else auth_context.allowed_project_codes

        query_vec = self.embedding_provider.embed([query_text])[0]
        results = self.vector_store.search(query_vec, project_codes=target_projects, top_k=3)

        return self.response_formatter.format_vector_response(results)

    def _handle_hybrid_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        sql_res = self._handle_sql_intent(plan, auth_context)
        vec_res = self._handle_vector_intent(plan, auth_context)

        return self.response_formatter.format_hybrid_response(sql_res, vec_res)
