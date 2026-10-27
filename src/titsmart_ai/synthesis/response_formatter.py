"""ResponseFormatter for standardizing technical construction management answers with transparent citations."""
from typing import Optional, List, Dict, Any, Set
from titsmart_ai.domain.chat import ChatResponse, ChatSource
from titsmart_ai.domain.documents import SearchResult
from titsmart_ai.domain.models import Task
from titsmart_ai.router.query_router import QueryIntent


class ResponseFormatter:
    """
    Bộ chuẩn hóa câu trả lời kỹ thuật và bằng chứng trích dẫn (Citations Formatter):
    - Chuẩn hóa văn phong báo cáo kỹ thuật ngành xây dựng (executive summary, số liệu, sự cố, khuyến nghị).
    - Khử trùng lặp (deduplicate) và xác thực nguồn trích dẫn (ChatSource).
    - Tạo danh mục bằng chứng minh bạch (Footnote / Citation Catalog) đính kèm trong câu trả lời.
    - Đảm bảo tính tất định (deterministic), không ảo giác (zero hallucination).
    """

    CITATIONS_HEADER = "\n\n### Danh mục nguồn trích dẫn:"

    def deduplicate_sources(self, sources: List[ChatSource]) -> List[ChatSource]:
        """
        Loại bỏ các nguồn trích dẫn trùng lặp dựa trên tuple (source_type, source_table, record_id, project_code),
        ưu tiên giữ bản ghi có điểm tương quan (score) cao nhất nếu có.
        """
        best_by_key: Dict[tuple[str, str, str, str], ChatSource] = {}
        order: List[tuple[str, str, str, str]] = []
        for s in sources:
            key = (s.source_type, s.source_table, s.record_id, s.project_code)
            if key not in best_by_key:
                best_by_key[key] = s
                order.append(key)
            else:
                existing = best_by_key[key]
                if s.score is not None and (existing.score is None or s.score > existing.score):
                    best_by_key[key] = s
        return [best_by_key[k] for k in order]

    def format_citations_catalog(self, sources: List[ChatSource]) -> str:
        """
        Định dạng khối danh mục nguồn trích dẫn Markdown chuyên nghiệp và minh bạch:
        - [Nguồn X] (Loại nguồn: Bảng/ID | Dự án | Điểm tương đồng nếu có): Nhãn mô tả
        """
        if not sources:
            return ""

        lines: List[str] = [self.CITATIONS_HEADER]
        for idx, s in enumerate(sources, 1):
            score_info = f" | Điểm tương quan: {s.score:.4f}" if s.score is not None else ""
            lines.append(
                f"- [Nguồn {idx}] ({s.source_type.upper()}: {s.source_table}/{s.record_id} | Dự án: {s.project_code}{score_info}): {s.label}"
            )
        return "\n".join(lines)

    def _strip_citations_catalog(self, text: str) -> str:
        """Loại bỏ phần danh mục trích dẫn ở cuối chuỗi để tái sử dụng trong báo cáo tổng hợp."""
        if "### Danh mục nguồn trích dẫn:" in text:
            return text.split("### Danh mục nguồn trích dẫn:")[0].rstrip()
        return text.rstrip()

    def validate_citations(self, sources: List[ChatSource]) -> bool:
        """Xác thực tính hợp lệ của toàn bộ nguồn trích dẫn."""
        if not isinstance(sources, list):
            return False
        for s in sources:
            if not isinstance(s, ChatSource):
                return False
            if s.source_type not in ("sql", "vector"):
                return False
            if not s.source_table or not s.record_id or not s.project_code:
                return False
            if not s.label or not s.label.strip():
                return False
        return True

    def format_sql_project_summary(
        self,
        summary: Dict[str, Any],
        delayed_tasks: Optional[List[Task]] = None,
        append_citations: bool = True,
    ) -> ChatResponse:
        """Định dạng phản hồi SQL chi tiết cho một dự án cụ thể."""
        target_code = summary.get("project_code", "N/A")
        project_name = summary.get("project_name", "Không rõ")
        status = summary.get("status", "Chưa xác định")
        avg_progress = summary.get("average_progress") if summary.get("average_progress") is not None else 0.0
        total_tasks = summary.get("total_tasks") if summary.get("total_tasks") is not None else 0
        total_volume = summary.get("total_volume") if summary.get("total_volume") is not None else 0.0
        total_issues = summary.get("total_issues") if summary.get("total_issues") is not None else 0

        lines: List[str] = [
            f"Thông tin dự án {project_name} ({target_code}):",
            f"- Trạng thái: {status}",
            f"- Tiến độ trung bình: {avg_progress}%",
            f"- Tổng số công việc: {total_tasks}",
            f"- Tổng khối lượng thi công: {total_volume}",
            f"- Số sự cố phát sinh: {total_issues}",
        ]

        sources: List[ChatSource] = [
            ChatSource(
                source_type="sql",
                source_table="projects",
                record_id=target_code,
                project_code=target_code,
                label=f"Tổng quan dự án {target_code}",
            )
        ]

        if delayed_tasks:
            lines.append(f"\nDanh sách {len(delayed_tasks)} công việc chưa hoàn thành:")
            for t in delayed_tasks[:5]:
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

        unique_sources = self.deduplicate_sources(sources)
        answer = "\n".join(lines)
        if append_citations and unique_sources:
            answer += self.format_citations_catalog(unique_sources)

        return ChatResponse(
            answer=answer,
            intent=QueryIntent.SQL,
            sources=unique_sources,
            has_evidence=True,
        )

    def format_sql_aggregate_progress(
        self,
        progress_by_project: List[Dict[str, Any]],
        allowed_projects: Set[str],
        append_citations: bool = True,
    ) -> ChatResponse:
        """Định dạng phản hồi SQL tổng hợp tiến độ nhiều dự án trong phạm vi quyền hạn."""
        lines: List[str] = ["Thống kê tiến độ các dự án trong phạm vi quyền hạn:"]
        sources: List[ChatSource] = []

        total_tasks = 0
        completed_tasks = 0
        in_progress_tasks = 0
        not_started_tasks = 0

        for p_stat in progress_by_project:
            p_code = p_stat.get("project_code")
            p_total = p_stat.get("total_tasks", 0)
            if p_total > 0 and p_code:
                total_tasks += p_total
                completed_tasks += p_stat.get("completed_tasks", 0)
                in_progress_tasks += p_stat.get("in_progress_tasks", 0)
                not_started_tasks += p_stat.get("not_started_tasks", 0)
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

        unique_sources = self.deduplicate_sources(sources)
        answer = "\n".join(lines)
        if append_citations and unique_sources:
            answer += self.format_citations_catalog(unique_sources)

        return ChatResponse(
            answer=answer,
            intent=QueryIntent.SQL,
            sources=unique_sources,
            has_evidence=True,
        )

    def format_vector_response(
        self,
        results: List[SearchResult],
        append_citations: bool = True,
    ) -> ChatResponse:
        """Định dạng phản hồi tìm kiếm ngữ nghĩa văn bản hiện trường (Vector RAG)."""
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

        unique_sources = self.deduplicate_sources(sources)
        answer = "\n".join(lines)
        if append_citations and unique_sources:
            answer += self.format_citations_catalog(unique_sources)

        return ChatResponse(
            answer=answer,
            intent=QueryIntent.VECTOR_SEARCH,
            sources=unique_sources,
            has_evidence=True,
        )

    def format_hybrid_response(
        self,
        sql_res: ChatResponse,
        vec_res: ChatResponse,
        warnings: Optional[List[str]] = None,
        append_citations: bool = True,
    ) -> ChatResponse:
        """
        Định dạng báo cáo tổng hợp Hybrid SQL + RAG:
        - Kết hợp mạch lạc giữa số liệu định lượng (SQL) và ngữ cảnh định tính (Vector RAG).
        - Đính kèm một danh mục trích dẫn thống nhất đã khử trùng lặp ở cuối báo cáo.
        """
        combined_warnings: List[str] = list(warnings or [])
        for w in (sql_res.warnings or []):
            if w not in combined_warnings:
                combined_warnings.append(w)
        for w in (vec_res.warnings or []):
            if w not in combined_warnings:
                combined_warnings.append(w)

        if not sql_res.has_evidence and "Không tìm thấy số liệu tính toán từ SQL" not in combined_warnings:
            combined_warnings.append("Không tìm thấy số liệu tính toán từ SQL")
        if not vec_res.has_evidence and "Không tìm thấy nhật ký/sự cố liên quan từ Vector Store" not in combined_warnings:
            combined_warnings.append("Không tìm thấy nhật ký/sự cố liên quan từ Vector Store")

        # Làm sạch nội dung câu trả lời từng phần trước khi ghép nối
        sql_clean = self._strip_citations_catalog(sql_res.answer)
        vec_clean = self._strip_citations_catalog(vec_res.answer)

        lines: List[str] = [
            "=== BÁO CÁO TỔNG HỢP (HYBRID SQL + RAG) ===",
            "\n[1. Số liệu tiến độ & công việc]:",
            sql_clean,
            "\n[2. Nhật ký & nguyên nhân thực tế]:",
            vec_clean,
        ]

        combined_sources = self.deduplicate_sources(sql_res.sources + vec_res.sources)
        answer = "\n".join(lines)

        if append_citations and combined_sources:
            answer += self.format_citations_catalog(combined_sources)

        return ChatResponse(
            answer=answer,
            intent=QueryIntent.HYBRID,
            sources=combined_sources,
            has_evidence=(sql_res.has_evidence or vec_res.has_evidence),
            warnings=combined_warnings,
        )

    def format_unsupported(
        self,
        message: str,
        warnings: Optional[List[str]] = None,
    ) -> ChatResponse:
        """Định dạng phản hồi từ chối hoặc ngoài phạm vi quyền hạn (Fail-Closed)."""
        return ChatResponse(
            answer=message,
            intent=QueryIntent.UNSUPPORTED,
            sources=[],
            has_evidence=False,
            warnings=warnings or [],
        )

    def format_no_evidence(
        self,
        message: str,
        intent: QueryIntent = QueryIntent.SQL,
        warnings: Optional[List[str]] = None,
    ) -> ChatResponse:
        """Định dạng phản hồi khi không tìm thấy dữ liệu phù hợp."""
        return ChatResponse(
            answer=message,
            intent=intent,
            sources=[],
            has_evidence=False,
            warnings=warnings or [],
        )

    def standardize_technical_answer(
        self,
        answer_text: str,
        sources: List[ChatSource],
        intent: QueryIntent,
        *,
        has_evidence: Optional[bool] = None,
        warnings: Optional[List[str]] = None,
        append_citations: bool = True,
    ) -> ChatResponse:
        """
        Chuẩn hóa câu trả lời kỹ thuật tổng quát (dùng cho LLM output hoặc template tùy biến):
        - Làm sạch khoảng trắng thừa.
        - Khử trùng lặp nguồn trích dẫn.
        - Đính kèm bảng tra cứu nguồn nếu yêu cầu.
        """
        clean_text = answer_text.strip()
        unique_sources = self.deduplicate_sources(sources)

        if append_citations and unique_sources and "### Danh mục nguồn trích dẫn:" not in clean_text:
            clean_text += self.format_citations_catalog(unique_sources)

        evidence_flag = has_evidence if has_evidence is not None else (len(unique_sources) > 0)

        return ChatResponse(
            answer=clean_text,
            intent=intent,
            sources=unique_sources,
            has_evidence=evidence_flag,
            warnings=warnings or [],
        )
