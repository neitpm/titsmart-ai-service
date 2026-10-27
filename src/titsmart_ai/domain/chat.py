"""Chat contracts definition: ChatRequest, ChatSource, ChatResponse."""
from typing import Literal, List, Optional
from pydantic import BaseModel, Field, ConfigDict
from titsmart_ai.router.query_router import QueryIntent


class ChatRequest(BaseModel):
    """
    Yêu cầu chat từ người dùng:
    - Chỉ nhận duy nhất nội dung câu hỏi (1 -> 2000 ký tự).
    - Không nhận user_id hoặc project_codes từ body (bảo vệ quyền truy cập).
    """
    question: str = Field(min_length=1, max_length=2000, description="Nội dung câu hỏi của người dùng")

    model_config = ConfigDict(extra="forbid")


class ChatSource(BaseModel):
    """Bằng chứng / Nguồn trích dẫn minh bạch cho câu trả lời."""
    source_type: Literal["sql", "vector"]
    source_table: str
    record_id: str
    project_code: str
    label: str
    score: Optional[float] = None

    model_config = ConfigDict(extra="forbid")


class ChatResponse(BaseModel):
    """
    Phản hồi câu trả lời hoàn chỉnh:
    - answer: Nội dung trả lời (tất định, không hallucination).
    - sources: Danh sách bằng chứng trích dẫn cụ thể.
    - has_evidence: True nếu có bằng chứng từ SQL hoặc Vector; False nếu không tìm thấy dữ liệu.
    """
    answer: str
    intent: QueryIntent
    sources: List[ChatSource] = Field(default_factory=list)
    has_evidence: bool = False
    warnings: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")
