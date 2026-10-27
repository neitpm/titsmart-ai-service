"""LLM Adapter module supporting 'mock' and 'staging' modes with Fail-Closed behavior."""
import abc
import logging
from typing import Optional, List, Dict, Any

import httpx

from titsmart_ai.config import settings
from titsmart_ai.domain.chat import ChatResponse, ChatSource
from titsmart_ai.llm.guardrails import LLMGuardrails
from titsmart_ai.router.query_router import QueryIntent
from titsmart_ai.synthesis.prompt_synthesizer import SynthesizedPrompt
from titsmart_ai.synthesis.response_formatter import ResponseFormatter

logger = logging.getLogger(__name__)


class LLMAdapter(abc.ABC):
    """
    Abstract Base Class for LLM Adapters.
    Ràng buộc:
    - LLM_MODE in ('mock', 'staging') cấm 'production'.
    - Fail-closed an toàn: timeout hoặc lỗi mạng không rò rỉ dữ liệu hoặc suy đoán.
    - Citation Post-Validation kiểm tra chéo citation chống LLM bịa nguồn.
    - Không đủ bằng chứng -> has_evidence=False và thông báo từ chối.
    """

    @abc.abstractmethod
    def generate(
        self,
        prompt: SynthesizedPrompt,
        backend_sources: List[ChatSource],
    ) -> ChatResponse:
        """Sinh câu trả lời từ prompt đã tổng hợp và danh sách sources đã được Backend kiểm soát."""
        pass


class MockLLMAdapter(LLMAdapter):
    """
    Adapter LLM chạy chế độ Offline / Mock Deterministic.
    - Hoàn toàn tất định, bảo đảm kiểm tra chéo citation và cấu trúc báo cáo kỹ thuật.
    - Nếu không có evidence (backend_sources rỗng hoặc prompt metadata chỉ rõ thiếu evidence),
      từ chối an toàn với has_evidence=False.
    """

    def __init__(self, response_formatter: Optional[ResponseFormatter] = None):
        self.formatter = response_formatter or ResponseFormatter()

    def generate(
        self,
        prompt: SynthesizedPrompt,
        backend_sources: List[ChatSource],
    ) -> ChatResponse:
        # 1. Kiểm tra Guardrail: Prompt Injection trong câu hỏi
        is_injection, msg = LLMGuardrails.detect_injection(prompt.user_prompt)
        if is_injection:
            return self.formatter.format_unsupported(
                f"Yêu cầu bị từ chối do vi phạm chính sách an toàn thông tin: {msg}",
                warnings=[msg or "Prompt Injection Detected"],
            )

        # 2. Không đủ bằng chứng -> Fail-closed từ chối với has_evidence=False
        has_sql = prompt.metadata.get("has_sql_context", False)
        has_vec = prompt.metadata.get("has_vector_context", False)
        if not backend_sources and not has_sql and not has_vec:
            return self.formatter.format_no_evidence(
                "Hệ thống không tìm thấy đủ dữ kiện và bằng chứng xác thực trong cơ sở dữ liệu để trả lời câu hỏi này.",
                intent=prompt.intent,
                warnings=["Không đủ dữ liệu xác thực (has_evidence=False)"],
            )

        # 3. Giả lập tạo câu trả lời kỹ thuật có cấu trúc dựa trên ngữ cảnh đã xác thực
        answer_parts: List[str] = [
            f"[Báo cáo phân tích kỹ thuật - Intent: {prompt.intent.value.upper()}]",
            f"Về câu hỏi: \"{prompt.user_prompt}\"",
        ]

        if prompt.sql_context and "Không có dữ liệu" not in prompt.sql_context:
            answer_parts.append("\nSố liệu kỹ thuật và tiến độ ghi nhận từ hệ thống:")
            answer_parts.append(prompt.sql_context)

        if prompt.vector_context and "Không có tài liệu" not in prompt.vector_context:
            answer_parts.append("\nGhi nhận từ nhật ký hiện trường & hồ sơ kỹ thuật:")
            answer_parts.append(prompt.vector_context)

        # Đính kèm tham chiếu trích dẫn hợp lệ nếu có backend_sources
        if backend_sources:
            answer_parts.append("\nCăn cứ theo tài liệu tham chiếu:")
            for i, src in enumerate(backend_sources, 1):
                answer_parts.append(f"- Căn cứ [Nguồn {i}]: {src.label} (Dự án: {src.project_code})")

        raw_answer = "\n".join(answer_parts)

        # 4. Citation Post-Validation
        validated_text, final_sources = LLMGuardrails.post_validate_citations(
            raw_answer, backend_sources
        )

        return self.formatter.standardize_technical_answer(
            answer_text=validated_text,
            sources=final_sources,
            intent=prompt.intent,
            has_evidence=bool(final_sources),
            append_citations=True,
        )


class StagingLLMAdapter(LLMAdapter):
    """
    Adapter LLM kết nối Staging Endpoint (ví dụ vLLM, Ollama, hoặc OpenAI-compatible API ở môi trường Staging).
    Tuân thủ các ràng buộc nghiêm ngặt:
    - Bắt buộc LLM_MODE == 'staging'.
    - Cấm tuyệt đối kết nối production.
    - Timeout fail-closed an toàn: khi timeout hoặc lỗi HTTP/mạng, trả về response fail-closed, không rò rỉ dữ liệu.
    - Citation Post-Validation: So khớp mọi [Nguồn X] trong LLM output với backend_sources. Nguồn nào ngoài danh mục do Backend cấp bị loại bỏ lập tức.
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout: Optional[float] = None,
        response_formatter: Optional[ResponseFormatter] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.api_base = api_base or settings.LLM_API_BASE
        self.api_key = api_key or settings.LLM_API_KEY
        self.model_name = model_name or settings.LLM_MODEL
        self.timeout = timeout if timeout is not None else settings.LLM_REQUEST_TIMEOUT
        self.formatter = response_formatter or ResponseFormatter()
        self._client = http_client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return httpx.Client(base_url=self.api_base, headers=headers, timeout=self.timeout)

    def generate(
        self,
        prompt: SynthesizedPrompt,
        backend_sources: List[ChatSource],
    ) -> ChatResponse:
        # 1. Guardrail phát hiện prompt injection trước khi gọi LLM
        is_inj, inj_msg = LLMGuardrails.detect_injection(prompt.user_prompt)
        if is_inj:
            return self.formatter.format_unsupported(
                f"Yêu cầu bị từ chối do vi phạm an toàn thông tin: {inj_msg}",
                warnings=[inj_msg or "Prompt Injection Detected"],
            )

        # 2. Guardrail không đủ bằng chứng
        has_sql = prompt.metadata.get("has_sql_context", False)
        has_vec = prompt.metadata.get("has_vector_context", False)
        if not backend_sources and not has_sql and not has_vec:
            return self.formatter.format_no_evidence(
                "Hệ thống không tìm thấy đủ dữ kiện và bằng chứng xác thực trong cơ sở dữ liệu để trả lời câu hỏi này.",
                intent=prompt.intent,
                warnings=["Không đủ dữ liệu xác thực (has_evidence=False)"],
            )

        # 3. Chuẩn bị payload và gọi LLM Staging với cơ chế Fail-Closed an toàn
        if not self.api_base:
            return self.formatter.format_no_evidence(
                "Lỗi cấu hình hệ thống: LLM Staging endpoint chưa được thiết lập. Hệ thống từ chối xử lý an toàn (Fail-Closed).",
                intent=prompt.intent,
                warnings=["LLM_API_BASE chưa được cấu hình cho Staging mode"],
            )

        # Sanitize prompt để loại bỏ PII và secret nhạy cảm
        safe_full_prompt = LLMGuardrails.sanitize_untrusted_context(prompt.full_prompt)

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": safe_full_prompt},
            ],
            "temperature": 0.0,  # Tất định
        }

        try:
            client = self._get_client()
            url = f"{self.api_base.rstrip('/')}/chat/completions" if not str(client.base_url) else "/chat/completions"
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
        except httpx.TimeoutException:
            logger.warning("LLM Staging timeout - Fail-closed activated.")
            return self.formatter.format_no_evidence(
                "Yêu cầu xử lý tới mô hình ngôn ngữ bị quá thời gian cho phép (Timeout). Hệ thống kích hoạt trạng thái an toàn Fail-Closed.",
                intent=prompt.intent,
                warnings=["LLM Staging Request Timeout"],
            )
        except Exception as e:
            logger.error("LLM Staging error: %s", str(e))
            return self.formatter.format_no_evidence(
                "Không thể kết nối đến mô hình ngôn ngữ Staging an toàn. Hệ thống kích hoạt trạng thái Fail-Closed.",
                intent=prompt.intent,
                warnings=[f"LLM Connection Error: {type(e).__name__}"],
            )

        # 4. Citation Post-Validation (Chống bịa nguồn)
        validated_text, final_sources = LLMGuardrails.post_validate_citations(
            raw_text, backend_sources
        )

        return self.formatter.standardize_technical_answer(
            answer_text=validated_text,
            sources=final_sources,
            intent=prompt.intent,
            has_evidence=bool(final_sources),
            append_citations=True,
        )


def get_llm_adapter(
    llm_mode: Optional[str] = None,
    response_formatter: Optional[ResponseFormatter] = None,
    http_client: Optional[httpx.Client] = None,
) -> LLMAdapter:
    """
    Factory tạo LLMAdapter tương ứng theo cấu hình:
    - Cấm tuyệt đối 'production'.
    - Hỗ trợ 'mock' và 'staging'.
    """
    mode = (llm_mode or settings.LLM_MODE).lower()
    if mode in ("production", "prod"):
        raise ValueError("LỖI BẢO MẬT: Tuyệt đối không được kích hoạt LLM_MODE='production'!")
    elif mode == "staging":
        return StagingLLMAdapter(
            response_formatter=response_formatter,
            http_client=http_client,
        )
    elif mode == "mock":
        return MockLLMAdapter(response_formatter=response_formatter)
    else:
        raise ValueError(f"Chế độ LLM không hợp lệ: '{mode}'. Chỉ chấp nhận 'mock' hoặc 'staging'.")
