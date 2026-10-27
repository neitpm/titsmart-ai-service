"""Deterministic ChatEngine coordinating Router, DataQueryTool, VectorStore, and Evidence Formatter without LLM."""
from typing import Optional, List
from titsmart_ai.domain.chat import ChatResponse, ChatSource
from titsmart_ai.security.auth import AuthContext
from titsmart_ai.router.query_router import QueryRouter, QueryIntent, QueryPlan
from titsmart_ai.tools.query_tool import DataQueryTool
from titsmart_ai.tools.vector_store import VectorStore, EmbeddingProvider


class ChatEngine:
    """
    Bộ máy thực thi Chat Hybrid không gọi LLM:
    - Điều phối: AuthContext -> QueryRouter -> SQL Tool & Vector Tool -> Evidence Formatting.
    - Hoàn toàn tất định (Deterministic Template Engine), không suy đoán khi không có dữ liệu.
    - Bảo mật: Chỉ dùng allowed_project_codes từ AuthContext.
    """

    def __init__(
        self,
        router: QueryRouter,
        query_tool: DataQueryTool,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ):
        self.router = router
        self.query_tool = query_tool
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    def answer(self, question: str, auth_context: AuthContext) -> ChatResponse:
        # 1. FAIL-CLOSED: Kiểm tra quyền dự án của user
        if not auth_context.allowed_project_codes:
            return ChatResponse(
                answer="Bạn chưa được phân quyền truy cập vào bất kỳ dự án nào. Vui lòng liên hệ quản trị viên.",
                intent=QueryIntent.UNSUPPORTED,
                sources=[],
                has_evidence=False,
                warnings=["Người dùng không có quyền truy cập dự án (allowed_project_codes rỗng)"],
            )

        # 2. Định tuyến câu hỏi qua QueryRouter
        plan: QueryPlan = self.router.route(
            question, allowed_project_codes=auth_context.allowed_project_codes
        )

        if plan.intent == QueryIntent.UNSUPPORTED:
            return ChatResponse(
                answer=f"Yêu cầu không được hỗ trợ hoặc nằm ngoài phạm vi quyền hạn: {'; '.join(plan.reasons)}",
                intent=QueryIntent.UNSUPPORTED,
                sources=[],
                has_evidence=False,
                warnings=plan.reasons,
            )

        # 3. Phân luồng thực thi dựa trên Intent
        if plan.intent == QueryIntent.SQL:
            return self._handle_sql_intent(plan, auth_context)
        elif plan.intent == QueryIntent.VECTOR_SEARCH:
            return self._handle_vector_intent(plan, auth_context)
        elif plan.intent == QueryIntent.HYBRID:
            return self._handle_hybrid_intent(plan, auth_context)

        return ChatResponse(
            answer="Không tìm thấy dữ liệu phù hợp.",
            intent=plan.intent,
            sources=[],
            has_evidence=False,
        )

    def _handle_sql_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        target_code = plan.project_code
        sources: List[ChatSource] = []
        lines: List[str] = []

        if target_code:
            summary = self.query_tool.get_project_summary(target_code)
            if not summary:
                return ChatResponse(
                    answer=f"Không tìm thấy dữ liệu phù hợp cho dự án {target_code}.",
                    intent=QueryIntent.SQL,
                    sources=[],
                    has_evidence=False,
                )

            lines.append(f"Thông tin dự án {summary['project_name']} ({summary['project_code']}):")
            lines.append(f"- Trạng thái: {summary['status']}")
            lines.append(f"- Tiến độ trung bình: {summary['average_progress']}%")
            lines.append(f"- Tổng số công việc: {summary['total_tasks']}")
            lines.append(f"- Tổng khối lượng thi công: {summary['total_volume']}")
            lines.append(f"- Số sự cố phát sinh: {summary['total_issues']}")

            sources.append(
                ChatSource(
                    source_type="sql",
                    source_table="projects",
                    record_id=target_code,
                    project_code=target_code,
                    label=f"Tổng quan dự án {target_code}",
                )
            )

            # Nếu hỏi về task chậm
            if plan.sql_operation == "find_delayed_tasks":
                delayed = self.query_tool.find_delayed_tasks(project_code=target_code, threshold=100.0)
                if delayed:
                    lines.append(f"\nDanh sách {len(delayed)} công việc chưa hoàn thành:")
                    for t in delayed[:5]:
                        lines.append(f"  + {t.name}: {t.progress or 0.0}% ({t.status or 'Chưa xong'})")
                        sources.append(
                            ChatSource(
                                source_type="sql",
                                source_table="tasks",
                                record_id=t.id,
                                project_code=target_code,
                                label=f"Task: {t.name}",
                            )
                        )
        else:
            # Truy vấn tiến độ tổng hợp - TUYỆT ĐỐI CHỈ tổng hợp trong allowed_project_codes
            total_tasks = 0
            completed_tasks = 0
            in_progress_tasks = 0
            not_started_tasks = 0
            lines.append("Thống kê tiến độ các dự án trong phạm vi quyền hạn:")

            for p_code in sorted(auth_context.allowed_project_codes):
                proj_stat = self.query_tool.get_progress_summary(project_code=p_code)
                p_total = proj_stat.get("total_tasks", 0)
                if p_total > 0:
                    total_tasks += p_total
                    completed_tasks += proj_stat.get("completed_tasks", 0)
                    in_progress_tasks += proj_stat.get("in_progress_tasks", 0)
                    not_started_tasks += proj_stat.get("not_started_tasks", 0)
                    sources.append(
                        ChatSource(
                            source_type="sql",
                            source_table="tasks",
                            record_id=f"progress_summary_{p_code}",
                            project_code=p_code,
                            label=f"Thống kê tiến độ dự án {p_code}",
                        )
                    )

            if total_tasks > 0:
                overall_rate = round((completed_tasks / total_tasks) * 100.0, 2)
            else:
                overall_rate = 0.0

            lines.append(f"- Tổng số công việc: {total_tasks}")
            lines.append(f"- Đã hoàn thành: {completed_tasks}")
            lines.append(f"- Đang thực hiện: {in_progress_tasks}")
            lines.append(f"- Tỷ lệ hoàn thành chung: {overall_rate}%")

        return ChatResponse(
            answer="\n".join(lines),
            intent=QueryIntent.SQL,
            sources=sources,
            has_evidence=True,
        )

    def _handle_vector_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        query_text = plan.vector_query or plan.normalized_question
        target_projects = {plan.project_code} if plan.project_code else auth_context.allowed_project_codes

        query_vec = self.embedding_provider.embed([query_text])[0]
        results = self.vector_store.search(query_vec, project_codes=target_projects, top_k=3)

        if not results:
            return ChatResponse(
                answer="Không tìm thấy dữ liệu nhật ký hoặc sự cố phù hợp với câu hỏi.",
                intent=QueryIntent.VECTOR_SEARCH,
                sources=[],
                has_evidence=False,
            )

        lines: List[str] = ["Thông tin ghi nhận từ nhật ký và hồ sơ sự cố hiện trường:"]
        sources: List[ChatSource] = []

        for r in results:
            lines.append(f"\n[Dự án {r.project_code} - Nguồn {r.source_table}]:")
            lines.append(r.content)
            sources.append(
                ChatSource(
                    source_type="vector",
                    source_table=r.source_table,
                    record_id=r.record_id,
                    project_code=r.project_code,
                    label=f"Trích xuất {r.source_table} ({r.project_code})",
                    score=r.score,
                )
            )

        return ChatResponse(
            answer="\n".join(lines),
            intent=QueryIntent.VECTOR_SEARCH,
            sources=sources,
            has_evidence=True,
        )

    def _handle_hybrid_intent(self, plan: QueryPlan, auth_context: AuthContext) -> ChatResponse:
        sql_res = self._handle_sql_intent(plan, auth_context)
        vec_res = self._handle_vector_intent(plan, auth_context)

        combined_sources = sql_res.sources + vec_res.sources
        warnings: List[str] = []

        if not sql_res.has_evidence:
            warnings.append("Không tìm thấy số liệu tính toán từ SQL")
        if not vec_res.has_evidence:
            warnings.append("Không tìm thấy nhật ký/sự cố liên quan từ Vector Store")

        lines = [
            "=== BÁO CÁO TỔNG HỢP (HYBRID SQL + RAG) ===",
            "\n[1. Số liệu tiến độ & công việc]:",
            sql_res.answer,
            "\n[2. Nhật ký & nguyên nhân thực tế]:",
            vec_res.answer,
        ]

        return ChatResponse(
            answer="\n".join(lines),
            intent=QueryIntent.HYBRID,
            sources=combined_sources,
            has_evidence=(sql_res.has_evidence or vec_res.has_evidence),
            warnings=warnings,
        )
