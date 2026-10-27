"""LLM Guardrails package: Prompt sanitizer, injection detector, and citation post-validation."""
import re
from typing import List, Set, Tuple, Optional
from titsmart_ai.domain.chat import ChatSource


# Mẫu phát hiện prompt injection / jailbreak phổ biến
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"bỏ\s+qua\s+(toàn\s+bộ\s+)?(chỉ\s+dẫn|hướng\s+dẫn|lệnh)\s+(trước|cũ)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"bây\s+giờ\s+bạn\s+là\s+hệ\s+thống\s+không\s+bị\s+giới\s+hạn", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"ghi\s+đè\s+hệ\s+thống", re.IGNORECASE),
    re.compile(r"execute\s+command", re.IGNORECASE),
    re.compile(r"thực\s+thi\s+lệnh", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
    re.compile(r"delete\s+from", re.IGNORECASE),
    re.compile(r"union\s+select", re.IGNORECASE),
    re.compile(r"admin\s+mode", re.IGNORECASE),
    re.compile(r"chế\s+độ\s+quản\s+trị", re.IGNORECASE),
    re.compile(r"reveal\s+(system\s+prompt|all\s+secrets|tokens?|keys?)", re.IGNORECASE),
    re.compile(r"tiết\s+lộ\s+(prompt|mật\s+khẩu|bí\s+mật|token|key)", re.IGNORECASE),
]

# Mẫu phát hiện PII & Secrets nhạy cảm
PII_AND_SECRET_PATTERNS = [
    # JWT Bearer token
    (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9_\-\.]+", re.IGNORECASE), "[REDACTED_JWT]"),
    # Generic API Key / Secret pattern
    (re.compile(r"(api[_\-\s]?key|secret|token|password|passwd|pwd)[\s:=]+['\"]?([a-zA-Z0-9_\-]{16,})['\"]?", re.IGNORECASE), r"\1: [REDACTED_SECRET]"),
    # Email
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE), "[REDACTED_EMAIL]"),
    # Số điện thoại VN (10 số bắt đầu bằng 09, 08, 07, 05, 03)
    (re.compile(r"\b(0[3|5|7|8|9][0-9]{8})\b"), "[REDACTED_PHONE]"),
    # Số CCCD / CMND (9 hoặc 12 chữ số)
    (re.compile(r"\b([0-9]{9}|[0-9]{12})\b"), "[REDACTED_ID_CARD]"),
]


class LLMGuardrails:
    """
    Tập hợp các chốt chặn an toàn (Guardrails) bảo vệ LLM & Hệ thống:
    1. Prompt Injection Detection: Phát hiện các nỗ lực chiếm quyền hoặc thao túng instruction.
    2. Prompt Sanitizer (PII/Secret Scrubbing): Lọc bỏ token, mật khẩu, PII trước khi đưa vào LLM context.
    3. Citation Post-Validation: Kiểm tra đối chiếu citation trong LLM response với catalog do Backend cấp,
       loại bỏ triệt để các nguồn do LLM tự bịa (anti-hallucination).
    """

    @classmethod
    def detect_injection(cls, text: str) -> Tuple[bool, Optional[str]]:
        """
        Kiểm tra xem văn bản có chứa mẫu prompt injection hoặc bypass chỉ dẫn không.
        Trả về: (is_injection, matched_pattern_description)
        """
        if not text:
            return False, None
        for pattern in INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, f"Phát hiện mẫu Prompt Injection tiềm ẩn: '{match.group(0)}'"
        return False, None

    @classmethod
    def sanitize_untrusted_context(cls, text: str) -> str:
        """
        Bọc văn bản từ nguồn không tin cậy (tài liệu, field logs, issues, user input)
        bằng các thẻ phân cách an toàn và khử trùng các secret, PII nếu có.
        """
        if not text:
            return ""

        sanitized = text
        for pattern, replacement in PII_AND_SECRET_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)

        return sanitized

    @classmethod
    def post_validate_citations(
        cls,
        llm_text: str,
        backend_sources: List[ChatSource],
    ) -> Tuple[str, List[ChatSource]]:
        """
        Citation Post-Validation (Backend-Driven):
        - backend_sources là danh sách ChatSource chuẩn do Backend thu thập và xác thực quyền.
        - Quét toàn bộ các tham chiếu [Nguồn X] trong llm_text.
        - Nếu số thứ tự X nằm ngoài khoảng 1..len(backend_sources), loại bỏ hoặc thay thế bằng thông báo nguồn không xác thực.
        - Trả về (văn bản đã chuẩn hóa, danh sách sources thực sự được trích dẫn hợp lệ).
        """
        if not backend_sources:
            # Không có nguồn nào được backend cấp -> LLM không được trích dẫn bất kỳ nguồn nào
            cleaned_text = re.sub(r"\[Nguồn\s*\d+\]", "[Nguồn không hợp lệ]", llm_text)
            return cleaned_text, []

        max_valid_idx = len(backend_sources)
        referenced_indices: Set[int] = set()

        def _citation_replacer(match: re.Match) -> str:
            full_ref = match.group(0)
            idx_str = match.group(1)
            try:
                idx = int(idx_str)
                if 1 <= idx <= max_valid_idx:
                    referenced_indices.add(idx)
                    return f"[Nguồn {idx}]"
                else:
                    return "[Nguồn không hợp lệ do LLM tự bịa]"
            except ValueError:
                return "[Nguồn không hợp lệ]"

        # Khử hoặc chuẩn hóa các mẫu [Nguồn X] hoặc [Nguồn: X]
        validated_text = re.sub(
            r"\[Nguồn\s*:?\s*(\d+)\]",
            _citation_replacer,
            llm_text,
            flags=re.IGNORECASE,
        )

        # Trả về các source tương ứng đã được Backend xác thực
        # Nếu LLM có trích dẫn hợp lệ, giữ theo thứ tự trích dẫn hoặc thứ tự backend
        if referenced_indices:
            valid_sources = [
                backend_sources[i - 1] for i in sorted(referenced_indices)
            ]
        else:
            # Nếu LLM không tham chiếu cụ thể nhưng Backend có sources, giữ toàn bộ sources của backend
            valid_sources = backend_sources

        return validated_text, valid_sources
