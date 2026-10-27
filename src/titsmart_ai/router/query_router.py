"""Deterministic, rule-based QueryRouter for planning Hybrid SQL + RAG queries without calling LLM."""
import re
import unicodedata
from enum import Enum
from typing import Optional, Set, List
from pydantic import BaseModel, Field, ConfigDict


class QueryIntent(str, Enum):
    """Ý định truy vấn của người dùng."""
    SQL = "sql"
    VECTOR_SEARCH = "vector_search"
    HYBRID = "hybrid"
    UNSUPPORTED = "unsupported"


class QueryPlan(BaseModel):
    """
    Kế hoạch truy vấn do QueryRouter tạo ra:
    - Chỉ lập kế hoạch, không thực thi trực tiếp.
    - Chứa lý do phân loại (reasons) và độ tin cậy (confidence).
    """
    intent: QueryIntent
    normalized_question: str
    project_code: Optional[str] = None
    sql_operation: Optional[str] = None
    vector_query: Optional[str] = None
    requires_project_scope: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def strip_accents(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để hỗ trợ tìm kiếm không dấu."""
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.replace("đ", "d").replace("Đ", "D")
    return text


class QueryRouter:
    """
    Router phân loại câu hỏi tất định (Deterministic Rule-Based Router):
    - Không gọi LLM / Network.
    - Fail-Closed: Bắt buộc kiểm tra allowed_project_codes.
    - Ưu tiên: UNSUPPORTED > HYBRID > SQL / VECTOR_SEARCH.
    """

    # 1. Các mẫu yêu cầu không được hỗ trợ (sửa/xóa, SQL injection, ngoài phạm vi)
    UNSUPPORTED_PATTERNS = [
        re.compile(r"(?i)\b(insert|update|delete|drop|alter|truncate|create\s+table|grant|revoke)\b"),
        re.compile(r"(?i)\b(sửa|xóa|thêm mới|cập nhật dữ liệu|chèn|hủy bỏ|phá hủy)\b"),
        re.compile(r"(?i)\b(select\s+.*\s+from|union\s+select|exec\s*\(|execute\s*\()\b"),
        re.compile(r"(?i)(--|;|\b1=1\b|\bor\s+1=1\b)"),
        # Off-topic: thời tiết ngoài đời (ví dụ: thời tiết Hà Nội/TPHCM), chứng khoán, vàng, bóng đá, thơ ca
        re.compile(r"(?i)\b(thời tiết\s+(?:hà nội|hcm|tphcm|đà nẵng|hôm nay|ngày mai)|chứng khoán|bóng đá|giá vàng|tử vi|chiêm tinh|làm thơ|bài thơ|kể chuyện)\b"),
    ]

    # 2. Dấu hiệu số liệu (SQL Analytics)
    SQL_KEYWORDS = [
        "bao nhieu", "ti le", "phan tram", "khoi luong", "tong so", "so luong",
        "tien do", "cham tien do", "tre han", "hoan thanh", "chua lam", "dang lam",
        "chi phi", "ngan sach", "hop dong", "gia tri", "thong ke", "tong quan",
        "danh sach task", "danh sach cong viec", "stt", "bao cao so lieu",
        "co bao nhieu", "tong cong", "ton kho", "vat tu con", "don gia",
    ]

    # 3. Dấu hiệu ngữ nghĩa / văn bản (Vector Search)
    VECTOR_KEYWORDS = [
        "nguyen nhan", "vi sao", "tai sao", "tai vi sao", "ly do",
        "su co", "vung mac", "bien ban", "nhat ky", "hien truong",
        "dien bien", "tinh hinh", "nhu the nao", "ra sao", "huong xu ly",
        "chi dao", "giai phap", "mo ta", "noi dung ghi chu", "ghi chu ky thuat",
        "thao luan", "kien nghi", "tai nan", "thoi tiet mua", "ngap nuoc",
    ]

    # 4. Nhận diện Project Code (Ví dụ: TITS-01, PRJ-01, TRAM_BIEN_AP_500KV, DA-02)
    PROJECT_CODE_PATTERN = re.compile(r"\b([A-Z0-9]{2,10}(?:[-_][A-Z0-9]{2,15})+)\b")

    def __init__(self, known_projects: Optional[Set[str]] = None):
        self.known_projects = known_projects or set()

    def _normalize(self, text: str) -> str:
        text = text.strip()
        # Chuẩn hóa khoảng trắng
        text = re.sub(r"\s+", " ", text)
        return text

    def _extract_project_code(self, text: str, allowed_projects: Set[str]) -> Optional[str]:
        """
        Trích xuất project_code dựa trên ranh giới token (Word Boundary Regex),
        tuyệt đối không dùng substring 'code in text' để tránh prefix collision (như TITS-01 khớp TITS-010).
        Thứ tự ưu tiên được sắp xếp theo độ dài giảm dần (Longest Match First) và tất định.
        """
        # 1. Tập hợp các mã đã biết hoặc được cấp quyền, sắp xếp giảm dần theo độ dài để tránh prefix collision
        candidates = sorted(list(set(allowed_projects) | set(self.known_projects)), key=lambda x: len(x), reverse=True)
        for code in candidates:
            # Dùng regex boundary chính xác: không phải ký tự chữ số/gạch nối liền kề
            pattern = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(code.upper())}(?![A-Za-z0-9_-])")
            if pattern.search(text.upper()):
                return code

        # 2. Regex tìm mã dự án dạng chuẩn (ví dụ: TITS-01, PRJ-02, TRAM_BIEN_AP_500KV)
        matches = self.PROJECT_CODE_PATTERN.findall(text.upper())
        if matches:
            return matches[0]

        # 3. Kiểm tra tiền tố viết tắt: "DA 1", "DỰ ÁN 1", "DA-01"
        match_da = re.search(r"(?:dự án|du an|da)\s+([A-Za-z0-9_-]+)", text, re.IGNORECASE)
        if match_da:
            return match_da.group(1).upper()

        return None

    def route(
        self,
        question: str,
        *,
        allowed_project_codes: Set[str],
    ) -> QueryPlan:
        """
        Phân loại câu hỏi thành QueryPlan theo nguyên tắc Fail-Closed:
        - allowed_project_codes rỗng -> Trả về UNSUPPORTED ngay lập tức nếu cần scope.
        """
        normalized_q = self._normalize(question)

        # 1. Câu hỏi rỗng
        if not normalized_q:
            return QueryPlan(
                intent=QueryIntent.UNSUPPORTED,
                normalized_question="",
                requires_project_scope=False,
                confidence=1.0,
                reasons=["Câu hỏi rỗng"],
            )

        # 2. Kiểm tra các mẫu không được hỗ trợ (Malicious / Mutation / Raw SQL / Off-topic)
        for pattern in self.UNSUPPORTED_PATTERNS:
            if pattern.search(normalized_q):
                return QueryPlan(
                    intent=QueryIntent.UNSUPPORTED,
                    normalized_question=normalized_q,
                    requires_project_scope=False,
                    confidence=1.0,
                    reasons=["Yêu cầu sửa/xóa, chèn raw SQL, injection hoặc chủ đề ngoài phạm vi"],
                )

        # 3. FAIL-CLOSED: Kiểm tra quyền dự án
        if not allowed_project_codes:
            return QueryPlan(
                intent=QueryIntent.UNSUPPORTED,
                normalized_question=normalized_q,
                requires_project_scope=True,
                confidence=1.0,
                reasons=["Fail-closed: Người dùng không có quyền truy cập bất kỳ dự án nào (allowed_project_codes rỗng)"],
            )

        # 4. Trích xuất project_code trong câu hỏi
        found_project = self._extract_project_code(normalized_q, allowed_project_codes)
        reasons: List[str] = []

        if found_project:
            if found_project not in allowed_project_codes:
                return QueryPlan(
                    intent=QueryIntent.UNSUPPORTED,
                    normalized_question=normalized_q,
                    project_code=found_project,
                    requires_project_scope=True,
                    confidence=1.0,
                    reasons=[f"Không có quyền truy cập dự án '{found_project}' được nhắc đến trong câu hỏi"],
                )
            reasons.append(f"Nhận diện dự án '{found_project}' thuộc quyền truy cập")
        else:
            reasons.append("Không chỉ định dự án cụ thể (truy vấn tổng thể hoặc tìm kiếm rộng)")

        # 5. Phân tích ngữ nghĩa: So khớp dấu hiệu SQL vs VECTOR
        q_clean = strip_accents(normalized_q.lower())
        sql_hits = []
        vector_hits = []

        # Kiểm tra từ viết tắt ngành xây dựng
        if re.search(r"\b(nvl|vật tư|vat tu)\b", q_clean):
            sql_hits.append("nvl/vật tư")
        if re.search(r"\b(ht|hoàn thành|hoan thanh)\b", q_clean):
            sql_hits.append("ht/hoàn thành")

        for kw in self.SQL_KEYWORDS:
            kw_clean = strip_accents(kw)
            if kw_clean in q_clean:
                sql_hits.append(kw)

        for kw in self.VECTOR_KEYWORDS:
            kw_clean = strip_accents(kw)
            if kw_clean in q_clean:
                vector_hits.append(kw)

        has_sql = len(sql_hits) > 0
        has_vector = len(vector_hits) > 0

        # Ưu tiên: HYBRID > SQL / VECTOR
        if has_sql and has_vector:
            reasons.append(f"Dấu hiệu SQL: {sql_hits[:3]}; Dấu hiệu Vector: {vector_hits[:3]}")
            return QueryPlan(
                intent=QueryIntent.HYBRID,
                normalized_question=normalized_q,
                project_code=found_project,
                sql_operation="get_project_summary_or_delayed_tasks",
                vector_query=normalized_q,
                requires_project_scope=True,
                confidence=0.95,
                reasons=reasons,
            )

        if has_sql:
            reasons.append(f"Dấu hiệu SQL tính toán: {sql_hits[:3]}")
            op = "find_delayed_tasks" if ("cham" in q_clean or "tre" in q_clean) else "get_project_summary"
            return QueryPlan(
                intent=QueryIntent.SQL,
                normalized_question=normalized_q,
                project_code=found_project,
                sql_operation=op,
                vector_query=None,
                requires_project_scope=True,
                confidence=0.9,
                reasons=reasons,
            )

        if has_vector:
            reasons.append(f"Dấu hiệu Vector ngữ nghĩa: {vector_hits[:3]}")
            return QueryPlan(
                intent=QueryIntent.VECTOR_SEARCH,
                normalized_question=normalized_q,
                project_code=found_project,
                sql_operation=None,
                vector_query=normalized_q,
                requires_project_scope=True,
                confidence=0.9,
                reasons=reasons,
            )

        # Mặc định: nếu là câu hỏi văn bản thông thường không chứa từ khóa số liệu, đưa sang VECTOR_SEARCH
        reasons.append("Không có từ khóa số liệu đặc trưng, điều hướng sang tìm kiếm ngữ nghĩa văn bản")
        return QueryPlan(
            intent=QueryIntent.VECTOR_SEARCH,
            normalized_question=normalized_q,
            project_code=found_project,
            sql_operation=None,
            vector_query=normalized_q,
            requires_project_scope=True,
            confidence=0.7,
            reasons=reasons,
        )
