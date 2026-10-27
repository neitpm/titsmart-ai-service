"""Document models and vector representation schemas for RAG pipeline."""
from typing import Literal, Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class KnowledgeDocument(BaseModel):
    """
    Tài liệu văn bản chuẩn hóa được tạo từ các thực thể nguồn:
    - Bắt buộc có: id, content, source_table, record_id, project_code.
    - Không lưu trữ nếu content rỗng.
    """
    id: str
    content: str
    source_table: Literal["field_logs", "issues", "tasks"]
    record_id: str
    project_code: str
    title: Optional[str] = None
    source_timestamp: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class TextChunk(BaseModel):
    """Chunk văn bản sau khi chia nhỏ, gắn kèm metadata và deterministic ID."""
    id: str
    document_id: str
    content: str
    source_table: Literal["field_logs", "issues", "tasks"]
    record_id: str
    project_code: str
    chunk_index: int
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class SearchResult(BaseModel):
    """Kết quả tìm kiếm ngữ nghĩa từ vector store kèm điểm tương đồng (similarity score)."""
    id: str
    document_id: str
    content: str
    source_table: str
    record_id: str
    project_code: str
    score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")
