"""Vector store protocols, deterministic fake embeddings, and in-memory vector store with ACL filtering."""
import math
import hashlib
from typing import Protocol, List, Optional, Set, Dict, runtime_checkable
from titsmart_ai.domain.documents import TextChunk, SearchResult


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Tính độ tương đồng Cosine giữa hai vector thực."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol cho dịch vụ tạo vector embedding."""
    dimensions: int

    def embed(self, texts: List[str]) -> List[List[float]]:
        ...


class DeterministicFakeEmbeddingProvider:
    """
    Fake Embedding Provider hoàn toàn offline phục vụ test contract:
    - Kích thước vector cố định (mặc định 384 theo migration schema).
    - Tạo vector tất định (cùng text -> luôn ra cùng vector).
    - Vector được chuẩn hóa L2 (L2 normalized: norm = 1.0).
    """

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed(self, texts: List[str]) -> List[List[float]]:
        results: List[List[float]] = []
        for text in texts:
            vec: List[float] = []
            # Sinh mảng float tất định từ sha256 hash của text
            for i in range(self.dimensions):
                seed = f"{text}:{i}"
                digest = hashlib.sha256(seed.encode("utf-8")).digest()
                # Lấy 4 bytes tạo float [-1.0, 1.0]
                int_val = int.from_bytes(digest[:4], byteorder="big", signed=True)
                vec.append(float(int_val) / (2**31))

            # Chuẩn hóa L2 vector
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            results.append(vec)
        return results


@runtime_checkable
class VectorStore(Protocol):
    """
    Protocol trừu tượng cho Vector Store (pgvector / in-memory):
    - Upsert: ghi đè nếu trùng ID.
    - Search: Bắt buộc truyền project_codes (Fail-Closed ACL).
    - Delete: xóa theo source_table và record_id khi bản ghi gốc bị xóa.
    """

    def upsert(self, chunks: List[TextChunk], embeddings: List[List[float]]) -> None:
        ...

    def search(
        self,
        embedding: List[float],
        *,
        project_codes: Set[str],
        top_k: int = 5,
    ) -> List[SearchResult]:
        ...

    def delete_by_record(self, source_table: str, record_id: str) -> int:
        ...


class InMemoryVectorStore:
    """
    Hiện thực VectorStore trên bộ nhớ trong:
    - Kiểm tra chặt chẽ dimensions (từ chối vector sai kích thước).
    - ACL Fail-Closed: Bắt buộc truyền project_codes hợp lệ, nếu rỗng hoặc None -> trả về [] ngay lập tức.
    - Giới hạn top_k an toàn trong khoảng [1, 100].
    """

    def __init__(self, expected_dimensions: int = 384, max_top_k: int = 100):
        self.expected_dimensions = expected_dimensions
        self.max_top_k = max_top_k
        self._store: Dict[str, tuple[TextChunk, List[float]]] = {}

    def upsert(self, chunks: List[TextChunk], embeddings: List[List[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError(f"Số lượng chunks ({len(chunks)}) không khớp với embeddings ({len(embeddings)})")

        for chunk, emb in zip(chunks, embeddings):
            if len(emb) != self.expected_dimensions:
                raise ValueError(
                    f"Vector dimension không hợp lệ: mong đợi {self.expected_dimensions}, nhận {len(emb)}"
                )
            if not chunk.project_code or not chunk.project_code.strip():
                raise ValueError("project_code không được để trống khi lưu trữ vector")

            self._store[chunk.id] = (chunk, list(emb))

    def search(
        self,
        embedding: List[float],
        *,
        project_codes: Set[str],
        top_k: int = 5,
    ) -> List[SearchResult]:
        if len(embedding) != self.expected_dimensions:
            raise ValueError(
                f"Query vector dimension không hợp lệ: mong đợi {self.expected_dimensions}, nhận {len(embedding)}"
            )
        if top_k <= 0:
            raise ValueError(f"top_k phải là số nguyên dương (> 0), nhận {top_k}")
        if top_k > self.max_top_k:
            raise ValueError(f"top_k vượt quá giới hạn tối đa cho phép ({self.max_top_k}), nhận {top_k}")

        # FAIL-CLOSED ACL: project_codes bắt buộc phải là tập hợp không rỗng
        if not project_codes:
            return []

        scored: List[SearchResult] = []

        for chunk_id, (chunk, emb) in self._store.items():
            # Chỉ xét các chunk thuộc danh sách project_codes được cấp quyền
            if chunk.project_code not in project_codes:
                continue

            score = cosine_similarity(embedding, emb)
            scored.append(
                SearchResult(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    content=chunk.content,
                    source_table=chunk.source_table,
                    record_id=chunk.record_id,
                    project_code=chunk.project_code,
                    score=round(score, 4),
                    metadata=dict(chunk.metadata),
                )
            )

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def delete_by_record(self, source_table: str, record_id: str) -> int:
        to_delete = [
            cid for cid, (chunk, _) in self._store.items()
            if chunk.source_table == source_table and chunk.record_id == record_id
        ]
        for cid in to_delete:
            del self._store[cid]
        return len(to_delete)

    def count(self) -> int:
        return len(self._store)
