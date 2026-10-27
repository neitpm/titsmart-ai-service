"""Document builder and text chunker for converting structured data into searchable text chunks."""
import re
import hashlib
from typing import List, Optional
from titsmart_ai.domain.models import FieldLog, Issue, Task
from titsmart_ai.domain.documents import KnowledgeDocument, TextChunk

# Regex phát hiện và loại bỏ PII/thông tin nhạy cảm khỏi nội dung văn bản
# 1. Số điện thoại: 10 chữ số bắt đầu bằng 03, 05, 07, 08, 09 hoặc +84 (hỗ trợ dấu chấm/gạch ngang phân tách: 0912.345.678, 0912-345-678)
PHONE_PATTERN = re.compile(r'(?<!\d)(?:\+84|0)[35789](?:[\.\-\s]?\d){8}(?!\d)')

# 2. Số tài khoản ngân hàng: dãy 9-16 chữ số đứng độc lập hoặc sau các từ khóa STK/TK/tài khoản
BANK_CARD_PATTERN = re.compile(r'(?i)(?:stk|số tk|tài khoản|tk)\s*[:.]?\s*(\d{9,16})|(?<!\w)\b\d{12,16}\b(?!\w)')

# 3. Email
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')


def sanitize_text(text: str) -> str:
    """
    Loại bỏ số điện thoại, số tài khoản ngân hàng và email khỏi văn bản RAG.
    Đảm bảo không che nhầm: số tiền (10.000.000 VNĐ), mã hợp đồng (HD-2026/01), mã dự án (TITS-01).
    """
    if not text:
        return ""
    cleaned = PHONE_PATTERN.sub("[SỐ ĐIỆN THOẠI ĐÃ ẨN]", text)
    cleaned = BANK_CARD_PATTERN.sub("[SỐ TÀI KHOẢN ĐÃ ẨN]", cleaned)
    cleaned = EMAIL_PATTERN.sub("[EMAIL ĐÃ ẨN]", cleaned)
    return cleaned


class DocumentBuilder:
    """
    Xây dựng KnowledgeDocument từ các bản ghi thực tế:
    - field_logs: note / notes.
    - issues: title + description.
    - tasks: name + notes.
    - Làm sạch (sanitize) PII: tự động che số điện thoại, tài khoản ngân hàng, email.
    - Bỏ qua bản ghi nếu nội dung văn bản rỗng.
    """

    @staticmethod
    def build_from_field_log(log: FieldLog) -> Optional[KnowledgeDocument]:
        note_content = (log.note or log.notes or "").strip()
        if not note_content:
            return None

        note_sanitized = sanitize_text(note_content)
        content = (
            f"Dự án: {log.project_code}\n"
            f"Nguồn: field_logs\n"
            f"Thời điểm: {log.timestamp or 'Không xác định'}\n"
            f"Nội dung nhật ký hiện trường: {note_sanitized}"
        )
        return KnowledgeDocument(
            id=f"doc:field_logs:{log.id}",
            content=content,
            source_table="field_logs",
            record_id=log.id,
            project_code=log.project_code,
            title="Nhật ký hiện trường",
            source_timestamp=log.timestamp,
            metadata={"images_count": log.images_count or 0},
        )

    @staticmethod
    def build_from_issue(issue: Issue) -> Optional[KnowledgeDocument]:
        title = (issue.title or "").strip()
        desc = (issue.description or "").strip()
        if not title and not desc:
            return None

        title_sanitized = sanitize_text(title)
        desc_sanitized = sanitize_text(desc)
        content = (
            f"Dự án: {issue.project_code}\n"
            f"Nguồn: issues\n"
            f"Tiêu đề sự cố: {title_sanitized}\n"
            f"Mức độ ưu tiên: {issue.priority}\n"
            f"Trạng thái: {issue.status}\n"
            f"Mô tả chi tiết: {desc_sanitized if desc_sanitized else 'Không có mô tả chi tiết'}"
        )
        return KnowledgeDocument(
            id=f"doc:issues:{issue.id}",
            content=content,
            source_table="issues",
            record_id=issue.id,
            project_code=issue.project_code,
            title=title_sanitized,
            source_timestamp=issue.reported_time,
            metadata={"priority": issue.priority, "status": issue.status},
        )

    @staticmethod
    def build_from_task(task: Task) -> Optional[KnowledgeDocument]:
        name = (task.name or "").strip()
        notes = (task.notes or "").strip()
        if not name and not notes:
            return None

        name_sanitized = sanitize_text(name)
        notes_sanitized = sanitize_text(notes)
        content = (
            f"Dự án: {task.project_code}\n"
            f"Nguồn: tasks\n"
            f"Hạng mục công việc: {name_sanitized}\n"
            f"Tiến độ hiện tại: {task.progress or 0.0}%\n"
            f"Trạng thái: {task.status or 'Chưa xác định'}\n"
            f"Ghi chú kỹ thuật: {notes_sanitized if notes_sanitized else 'Không có ghi chú'}"
        )
        return KnowledgeDocument(
            id=f"doc:tasks:{task.id}",
            content=content,
            source_table="tasks",
            record_id=task.id,
            project_code=task.project_code,
            title=name_sanitized,
            source_timestamp=None,
            metadata={
                "stt": str(task.stt) if task.stt is not None else None,
                "volume": task.volume,
                "unit": task.unit,
                "progress": task.progress,
            },
        )


class TextChunker:
    """
    Chia nhỏ KnowledgeDocument thành TextChunk:
    - chunk_size: 800 - 1200 ký tự (mặc định 1000).
    - overlap: 100 - 200 ký tự (mặc định 150).
    - Deterministic Chunk ID: sha256(source_table + record_id + chunk_index + content).
    - Giữ nguyên toàn bộ metadata và project_code cho ACL filtering.
    """

    def __init__(self, chunk_size: int = 1000, overlap: int = 150):
        if chunk_size <= 0:
            raise ValueError("chunk_size phải lớn hơn 0")
        if overlap < 0:
            raise ValueError("overlap không được âm")
        if overlap >= chunk_size:
            raise ValueError(f"overlap ({overlap}) phải nhỏ hơn chunk_size ({chunk_size})")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, doc: KnowledgeDocument) -> List[TextChunk]:
        text = doc.content.strip()
        if not text:
            return []

        # Nếu văn bản ngắn hơn hoặc bằng chunk_size (kể cả ngắn hơn overlap)
        if len(text) <= self.chunk_size:
            id_raw = f"{doc.source_table}:{doc.record_id}:0:{text}"
            chunk_id = hashlib.sha256(id_raw.encode("utf-8")).hexdigest()[:32]
            return [
                TextChunk(
                    id=f"chk_{chunk_id}",
                    document_id=doc.id,
                    content=text,
                    source_table=doc.source_table,
                    record_id=doc.record_id,
                    project_code=doc.project_code,
                    chunk_index=0,
                    metadata=dict(doc.metadata),
                )
            ]

        chunks: List[TextChunk] = []
        start = 0
        text_len = len(text)
        chunk_idx = 0

        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            chunk_text = text[start:end].strip()

            if chunk_text:
                id_raw = f"{doc.source_table}:{doc.record_id}:{chunk_idx}:{chunk_text}"
                chunk_id = hashlib.sha256(id_raw.encode("utf-8")).hexdigest()[:32]

                chunks.append(
                    TextChunk(
                        id=f"chk_{chunk_id}",
                        document_id=doc.id,
                        content=chunk_text,
                        source_table=doc.source_table,
                        record_id=doc.record_id,
                        project_code=doc.project_code,
                        chunk_index=chunk_idx,
                        metadata=dict(doc.metadata),
                    )
                )
                chunk_idx += 1

            if end == text_len:
                break
            start += self.chunk_size - self.overlap

        return chunks
