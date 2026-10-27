"""PromptSynthesizer for building grounded, structured prompts in TITSmart Hybrid SQL + RAG."""
from typing import Optional, List, Dict, Any, Set
from pydantic import BaseModel, Field, ConfigDict

from titsmart_ai.domain.documents import SearchResult
from titsmart_ai.domain.models import Task
from titsmart_ai.router.query_router import QueryIntent


class SynthesizedPrompt(BaseModel):
    """
    Kết quả tổng hợp Prompt kỹ thuật:
    - system_prompt: Chỉ dẫn kỹ thuật, chuẩn mực văn phong công trình, nguyên tắc Grounding & Citation.
    - user_prompt: Câu hỏi của người dùng kèm các chỉ dẫn truy vấn cụ thể.
    - sql_context: Khối dữ liệu sự thật có cấu trúc từ SQL (tiến độ, khối lượng, nhiệm vụ).
    - vector_context: Khối dữ liệu ngữ nghĩa từ Vector Store (nhật ký, sự cố, ghi chú).
    - full_prompt: Chuỗi prompt hoàn chỉnh kết hợp system, context và user question.
    - token_estimate: Ước tính số lượng token của full_prompt.
    - intent: Ý định truy vấn tương ứng.
    - metadata: Thông tin bổ trợ (dự án mục tiêu, danh sách quyền truy cập, v.v.).
    """
    system_prompt: str
    user_prompt: str
    sql_context: str = ""
    vector_context: str = ""
    full_prompt: str
    token_estimate: int = 0
    intent: QueryIntent
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


SYSTEM_PROMPT_TEMPLATE = """Bạn là Trợ lý AI Kỹ thuật cao cấp của hệ thống TITSmart (Chuyên gia Phân tích Tiến độ & Quản lý Dự án Xây dựng).

NGUYÊN TẮC BẮT BUỘC (FAIL-CLOSED & ZERO HALLUCINATION):
1. TUYỆT ĐỐI KHÔNG BỊA ĐẶT SỐ LIỆU (ZERO HALLUCINATION): Chỉ sử dụng dữ kiện được cung cấp trong phần CONTEXT dưới đây. Không suy đoán hay suy diễn ngoài dữ liệu thực tế.
2. NGUYÊN TẮC BẰNG CHỨNG (GROUNDING & CITATIONS): Mọi kết luận, số liệu phần trăm tiến độ, số lượng công việc, hay mô tả sự cố đều phải kèm nguồn tham chiếu xác thực dạng [Nguồn X].
3. VĂN PHONG KỸ THUẬT XÂY DỰNG: Rõ ràng, súc tích, chuẩn mực kỹ thuật công trình, phân tách rành mạch:
   - Tóm tắt tổng quan thực trạng
   - Chi tiết số liệu tiến độ / khối lượng thi công
   - Nhật ký hiện trường & nguyên nhân sự cố (nếu có)
   - Đánh giá kỹ thuật & Kiến nghị hành động
4. XỬ LÝ KHI THIẾU DỮ LIỆU (FAIL-CLOSED): Nếu trong CONTEXT không có số liệu hoặc tài liệu tương ứng, phải thông báo rõ ràng là không tìm thấy dữ liệu trong hệ thống thay vì phỏng đoán.
"""


class PromptSynthesizer:
    """
    Bộ tổng hợp prompt và ngữ cảnh kỹ thuật:
    - Định hình System Prompt với các ràng buộc khắt khe về kỹ thuật và trích dẫn.
    - Chuẩn hóa và đóng gói ngữ cảnh SQL (Project summary, Task list, Progress breakdown).
    - Chuẩn hóa và đóng gói ngữ cảnh Vector (Semantic chunks, Field logs, Issues).
    - Tính toán ước lượng token và bảo toàn tính tất định.
    """

    def __init__(self, system_template: Optional[str] = None):
        self._system_template = system_template or SYSTEM_PROMPT_TEMPLATE.strip()

    def build_system_prompt(self) -> str:
        """Trả về system prompt chuẩn kỹ thuật."""
        return self._system_template

    def format_sql_context(
        self,
        summary: Optional[Dict[str, Any]] = None,
        delayed_tasks: Optional[List[Task]] = None,
        progress_summaries: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Chuẩn hóa dữ liệu phân tích SQL thành khối văn bản cấu trúc phục vụ Grounding:
        - summary: Tổng quan 1 dự án cụ thể.
        - delayed_tasks: Danh sách task chậm hoặc chưa xong.
        - progress_summaries: Danh sách thống kê tiến độ theo từng dự án trong quyền hạn.
        """
        lines: List[str] = []

        if summary:
            target_code = summary.get("project_code", "N/A")
            project_name = summary.get("project_name", "Không rõ")
            lines.append(f"Dự án: {project_name} (Mã: {target_code})")
            lines.append(f"- Trạng thái dự án: {summary.get('status', 'Chưa xác định')}")
            lines.append(f"- Tiến độ trung bình: {summary.get('average_progress', 0.0)}%")
            lines.append(f"- Tổng số công việc: {summary.get('total_tasks', 0)}")
            lines.append(f"- Tổng khối lượng thi công: {summary.get('total_volume', 0.0)}")
            lines.append(f"- Số lượng sự cố ghi nhận: {summary.get('total_issues', 0)}")
            if "contract_value" in summary and summary["contract_value"]:
                lines.append(f"- Giá trị hợp đồng: {summary['contract_value']:,.2f}")

        if delayed_tasks:
            lines.append(f"\nDanh sách {len(delayed_tasks)} công việc chưa hoàn thành / chậm tiến độ:")
            for t in delayed_tasks:
                lines.append(
                    f"  + Task [{t.id}] '{t.name}': Tiến độ {t.progress or 0.0}% | Trạng thái: {t.status or 'Chưa hoàn thành'} | Khối lượng: {t.volume or 0.0}"
                )

        if progress_summaries:
            lines.append("Thống kê phân bổ tiến độ theo từng dự án được cấp quyền:")
            for p in progress_summaries:
                lines.append(
                    f"  + Dự án {p.get('project_code')}: Tổng tasks={p.get('total_tasks', 0)}, "
                    f"Hoàn thành={p.get('completed_tasks', 0)}, Đang làm={p.get('in_progress_tasks', 0)}, "
                    f"Chưa làm={p.get('not_started_tasks', 0)}, Tỉ lệ HT={p.get('overall_completion_rate', 0.0)}%"
                )

        if not lines:
            return "Không có dữ liệu số liệu SQL phù hợp."

        return "\n".join(lines)

    def format_vector_context(
        self,
        search_results: Optional[List[SearchResult]] = None,
    ) -> str:
        """
        Chuẩn hóa các đoạn trích xuất vector RAG thành khối văn bản cấu trúc có trích dẫn nguồn:
        - Bao gồm bảng nguồn, mã bản ghi, dự án và điểm tương đồng.
        """
        if not search_results:
            return "Không có tài liệu nhật ký hay sự cố nào được tìm thấy."

        lines: List[str] = ["Dữ liệu trích xuất từ nhật ký hiện trường và hồ sơ kỹ thuật:"]
        for idx, r in enumerate(search_results, 1):
            score_str = f" | Điểm tương đồng: {r.score:.4f}" if r.score is not None else ""
            lines.append(
                f"\n[Bằng chứng {idx}] (Bảng: {r.source_table} | Bản ghi: {r.record_id} | Dự án: {r.project_code}{score_str}):"
            )
            lines.append(r.content.strip())

        return "\n".join(lines)

    def estimate_tokens(self, text: str) -> int:
        """
        Ước tính số token của chuỗi văn bản theo nguyên tắc tất định:
        - Khoảng 3.5 ký tự mỗi token cho văn bản tiếng Việt/kỹ thuật.
        """
        if not text or not text.strip():
            return 0
        return max(1, int(len(text.strip()) / 3.5))

    def synthesize(
        self,
        question: str,
        intent: QueryIntent,
        *,
        summary: Optional[Dict[str, Any]] = None,
        delayed_tasks: Optional[List[Task]] = None,
        progress_summaries: Optional[List[Dict[str, Any]]] = None,
        vector_results: Optional[List[SearchResult]] = None,
        project_code: Optional[str] = None,
        allowed_project_codes: Optional[Set[str]] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> SynthesizedPrompt:
        """
        Tổng hợp toàn diện Prompt Payload bao gồm System Prompt, SQL Context, Vector Context và User Prompt.
        """
        system_prompt = self.build_system_prompt()
        sql_context = ""
        vector_context = ""

        if intent in (QueryIntent.SQL, QueryIntent.HYBRID):
            sql_context = self.format_sql_context(
                summary=summary,
                delayed_tasks=delayed_tasks,
                progress_summaries=progress_summaries,
            )

        if intent in (QueryIntent.VECTOR_SEARCH, QueryIntent.HYBRID):
            vector_context = self.format_vector_context(vector_results)

        prompt_blocks: List[str] = [
            "### SYSTEM INSTRUCTIONS ###",
            system_prompt,
            "\n### RETRIEVED CONTEXT ###",
        ]

        if sql_context:
            prompt_blocks.append("[KHỐI DỮ LIỆU SỐ LIỆU & TIẾN ĐỘ THI CÔNG (SQL)]:")
            prompt_blocks.append(sql_context)

        if vector_context:
            prompt_blocks.append("\n[KHỐI DỮ LIỆU NHẬT KÝ & HỒ SƠ SỰ CỐ HIỆN TRƯỜNG (VECTOR RAG)]:")
            prompt_blocks.append(vector_context)

        if not sql_context and not vector_context:
            prompt_blocks.append("Không có dữ liệu nào được trích xuất từ hệ thống.")

        prompt_blocks.append("\n### USER QUESTION ###")
        prompt_blocks.append(f"Câu hỏi: {question.strip()}")
        prompt_blocks.append(
            "\nHãy trả lời câu hỏi trên theo đúng chuẩn văn phong kỹ thuật, tuân thủ nghiêm ngặt dữ liệu trong CONTEXT và kèm trích dẫn nguồn."
        )

        full_prompt = "\n".join(prompt_blocks)
        token_estimate = self.estimate_tokens(full_prompt)

        metadata: Dict[str, Any] = {
            "intent": intent.value,
            "project_code": project_code,
            "allowed_project_codes": sorted(list(allowed_project_codes)) if allowed_project_codes else [],
            "has_sql_context": bool(sql_context and "Không có dữ liệu" not in sql_context),
            "has_vector_context": bool(vector_results),
            "vector_results_count": len(vector_results) if vector_results else 0,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        return SynthesizedPrompt(
            system_prompt=system_prompt,
            user_prompt=question.strip(),
            sql_context=sql_context,
            vector_context=vector_context,
            full_prompt=full_prompt,
            token_estimate=token_estimate,
            intent=intent,
            metadata=metadata,
        )
