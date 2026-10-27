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


class OllamaLLMAdapter(StagingLLMAdapter):
    """
    Adapter LLM kết nối Ollama local:
    - Mô hình chính: qwen3:8b (mặc định từ cấu hình OLLAMA_PRIMARY_MODEL).
    - Mô hình dự phòng: qwen3:4b (tự động kích hoạt khi 8b không khả dụng hoặc lỗi).
    - Cấm tuyệt đối dùng bge-m3 để trò chuyện / sinh văn bản.
    - OLLAMA_BASE_URL: http://127.0.0.1:11434 (Chỉ kết nối local loopback, không gửi ra cloud/internet).
    - Ràng buộc bảo mật:
      + Prompt injection detection fail-closed.
      + ACL pre-filtered context.
      + Backend-driven sources & Citation Post-Validation.
      + Timeout & Error Fail-Closed: trả về has_evidence=False, không bịa đặt nguồn hoặc rò rỉ dữ liệu.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        primary_model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        timeout: Optional[float] = None,
        response_formatter: Optional[ResponseFormatter] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        target_base = base_url or settings.OLLAMA_BASE_URL or "http://127.0.0.1:11434"
        super().__init__(
            api_base=target_base,
            api_key=None,
            model_name=primary_model or settings.OLLAMA_PRIMARY_MODEL,
            timeout=timeout if timeout is not None else settings.OLLAMA_REQUEST_TIMEOUT,
            response_formatter=response_formatter,
            http_client=http_client,
        )
        self.primary_model = primary_model or settings.OLLAMA_PRIMARY_MODEL
        self.fallback_model = fallback_model or settings.OLLAMA_FALLBACK_MODEL
        self._validate_local_base_url()
        self._validate_chat_models()

    def _validate_local_base_url(self) -> None:
        from urllib.parse import urlparse
        parsed = urlparse(self.api_base or "")
        host = (parsed.hostname or "").lower()
        if host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            raise ValueError(
                f"LỖI BẢO MẬT: OLLAMA_BASE_URL '{self.api_base}' không phải là local loopback! Tuyệt đối không gửi dữ liệu ra cloud hay internet."
            )

    def _validate_chat_models(self) -> None:
        for m in (self.primary_model, self.fallback_model):
            if m and "bge-m3" in m.lower():
                raise ValueError(
                    f"LỖI BẢO MẬT: Mô hình '{m}' là embedding model (1024 dims), cấm tuyệt đối dùng để trò chuyện!"
                )

    def _call_ollama_single(
        self, client: httpx.Client, model: str, prompt: SynthesizedPrompt
    ) -> str:
        safe_full_prompt = LLMGuardrails.sanitize_untrusted_context(prompt.full_prompt)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": safe_full_prompt},
            ],
            "stream": False,
            "temperature": 0.0,
            "options": {"temperature": 0.0},
        }

        # 1. Thử gọi /api/chat (native Ollama endpoint)
        url = "/api/chat" if str(client.base_url) else f"{self.api_base.rstrip('/')}/api/chat"
        resp = client.post(url, json=payload)

        # 2. Nếu 404 (ví dụ endpoint OpenAI-compatible /chat/completions)
        if resp.status_code == 404:
            fallback_url = "/chat/completions" if str(client.base_url) else f"{self.api_base.rstrip('/')}/chat/completions"
            resp = client.post(fallback_url, json=payload)

        resp.raise_for_status()
        data = resp.json()

        if "message" in data and isinstance(data["message"], dict) and "content" in data["message"]:
            return data["message"]["content"]
        elif "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        else:
            raise ValueError(f"Định dạng phản hồi Ollama không hợp lệ: {data}")

    def generate(
        self,
        prompt: SynthesizedPrompt,
        backend_sources: List[ChatSource],
    ) -> ChatResponse:
        # 1. Guardrail phát hiện prompt injection trong câu hỏi
        is_inj, inj_msg = LLMGuardrails.detect_injection(prompt.user_prompt)
        if is_inj:
            return self.formatter.format_unsupported(
                f"Yêu cầu bị từ chối do vi phạm chính sách an toàn thông tin: {inj_msg}",
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

        client = self._get_client()
        raw_text: Optional[str] = None
        warnings: List[str] = []
        primary_failed = False

        # 3. Gọi Mô hình chính: qwen3:8b
        try:
            raw_text = self._call_ollama_single(client, self.primary_model, prompt)
        except Exception as e_primary:
            primary_failed = True
            err_msg = (
                f"Primary model '{self.primary_model}' error ({type(e_primary).__name__}: {str(e_primary)}). "
                f"Kích hoạt fallback sang '{self.fallback_model}'."
            )
            logger.warning(err_msg)
            warnings.append(f"Mô hình chính {self.primary_model} không khả dụng, đã chuyển sang fallback {self.fallback_model}")

        # 4. Fallback Model: qwen3:4b khi 8b lỗi hoặc không khả dụng
        if primary_failed:
            try:
                raw_text = self._call_ollama_single(client, self.fallback_model, prompt)
                warnings.append(f"Phản hồi được tạo bởi mô hình dự phòng: {self.fallback_model}")
            except httpx.TimeoutException as e_to:
                logger.error("Fallback model '%s' timeout: %s", self.fallback_model, str(e_to))
                warnings.append(f"Fallback model '{self.fallback_model}' Timeout")
                return self.formatter.format_no_evidence(
                    "Cả mô hình ngôn ngữ chính và mô hình dự phòng đều quá thời gian chờ (Timeout). Hệ thống kích hoạt trạng thái an toàn Fail-Closed.",
                    intent=prompt.intent,
                    warnings=warnings,
                )
            except Exception as e_fb:
                logger.error("Fallback model '%s' error: %s", self.fallback_model, str(e_fb))
                warnings.append(f"Fallback model '{self.fallback_model}' Error: {type(e_fb).__name__}")
                return self.formatter.format_no_evidence(
                    "Không thể kết nối đến mô hình ngôn ngữ Ollama (cả mô hình chính và mô hình dự phòng đều không khả dụng hoặc lỗi). Hệ thống kích hoạt trạng thái Fail-Closed.",
                    intent=prompt.intent,
                    warnings=warnings,
                )

        if raw_text is None:
            return self.formatter.format_no_evidence(
                "Không nhận được phản hồi hợp lệ từ mô hình ngôn ngữ. Hệ thống kích hoạt trạng thái Fail-Closed.",
                intent=prompt.intent,
                warnings=warnings or ["No response from LLM"],
            )

        # 5. Citation Post-Validation (Chống LLM bịa nguồn)
        validated_text, final_sources = LLMGuardrails.post_validate_citations(
            raw_text, backend_sources
        )

        return self.formatter.standardize_technical_answer(
            answer_text=validated_text,
            sources=final_sources,
            intent=prompt.intent,
            has_evidence=bool(final_sources),
            append_citations=True,
            warnings=warnings if warnings else None,
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
    - Staging mode sử dụng OllamaLLMAdapter (qwen3:8b với fallback qwen3:4b).
    """
    mode = (llm_mode or settings.LLM_MODE).lower()
    if mode in ("production", "prod"):
        raise ValueError("LỖI BẢO MẬT: Tuyệt đối không được kích hoạt LLM_MODE='production'!")
    elif mode == "staging":
        return OllamaLLMAdapter(
            response_formatter=response_formatter,
            http_client=http_client,
        )
    elif mode == "mock":
        return MockLLMAdapter(response_formatter=response_formatter)
    else:
        raise ValueError(f"Chế độ LLM không hợp lệ: '{mode}'. Chỉ chấp nhận 'mock' hoặc 'staging'.")
