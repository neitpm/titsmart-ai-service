"""Tests for DocumentBuilder, TextChunker, EmbeddingProvider, VectorStore, and ACL isolation."""
import pytest
from titsmart_ai.domain.models import FieldLog, Issue, Task
from titsmart_ai.domain.documents import KnowledgeDocument, TextChunk, SearchResult
from titsmart_ai.ingestion.document_builder import DocumentBuilder, TextChunker, sanitize_text
from titsmart_ai.tools.vector_store import (
    EmbeddingProvider,
    DeterministicFakeEmbeddingProvider,
    VectorStore,
    InMemoryVectorStore,
    cosine_similarity,
)


# 1. Test DocumentBuilder & PII Sanitization
def test_builder_from_field_log():
    log = FieldLog(
        id="fl-1",
        project_code="TITS-01",
        note="Đã thi công xong móng trụ T1",
        timestamp="2026-10-26T08:00:00",
        images_count=3,
    )
    doc = DocumentBuilder.build_from_field_log(log)
    assert doc is not None
    assert doc.id == "doc:field_logs:fl-1"
    assert doc.source_table == "field_logs"
    assert doc.project_code == "TITS-01"
    assert "Đã thi công xong móng trụ T1" in doc.content
    assert doc.metadata["images_count"] == 3


def test_builder_sanitizes_pii_in_notes():
    """Kiểm tra DocumentBuilder tự động che số điện thoại và số tài khoản trong nội dung ghi chú."""
    log = FieldLog(
        id="fl-pii",
        project_code="TITS-01",
        note="Liên hệ kỹ sư theo số 0912.345.678 hoặc +84987654321, chuyển tiền vào STK: 19036789123456 Techcombank",
    )
    doc = DocumentBuilder.build_from_field_log(log)
    assert doc is not None
    assert "0912.345.678" not in doc.content
    assert "+84987654321" not in doc.content
    assert "19036789123456" not in doc.content
    assert "[SỐ ĐIỆN THOẠI ĐÃ ẨN]" in doc.content
    assert "[SỐ TÀI KHOẢN ĐÃ ẨN]" in doc.content


def test_sanitizer_does_not_mask_contracts_or_money():
    """Kiểm tra không bị false positive: Mã hợp đồng, tiền tệ, mã dự án không bị che."""
    text = "Hợp đồng HD-2026/01, mã dự án TITS-01, tổng giá trị 500.000.000 VNĐ, khối lượng 1.500 m3"
    cleaned = sanitize_text(text)
    assert "HD-2026/01" in cleaned
    assert "TITS-01" in cleaned
    assert "500.000.000 VNĐ" in cleaned
    assert "1.500 m3" in cleaned


def test_builder_skips_empty_content():
    log_empty = FieldLog(id="fl-empty", project_code="TITS-01", note=None, notes=None)
    assert DocumentBuilder.build_from_field_log(log_empty) is None

    issue_empty = Issue(id="iss-empty", project_code="TITS-01", title="", description="")
    assert DocumentBuilder.build_from_issue(issue_empty) is None

    task_empty = Task(id="t-empty", project_code="TITS-01", name="", notes=None)
    assert DocumentBuilder.build_from_task(task_empty) is None


def test_builder_from_issue():
    issue = Issue(
        id="iss-1",
        project_code="TITS-01",
        title="Vướng mặt bằng hố móng",
        description="Chủ đầu tư chưa bàn giao tim mốc",
        priority="CRITICAL",
        status="OPEN",
        reported_time="2026-10-25T14:00:00",
    )
    doc = DocumentBuilder.build_from_issue(issue)
    assert doc is not None
    assert "Vướng mặt bằng hố móng" in doc.content
    assert "Chủ đầu tư chưa bàn giao" in doc.content
    assert doc.metadata["priority"] == "CRITICAL"


def test_builder_from_task():
    task = Task(
        id="t-1",
        project_code="TITS-01",
        name="Kéo rải cáp ngầm 22kV",
        notes="Lưu ý bán kính uốn cong của cáp",
        progress=50.0,
        volume=500.0,
        unit="m",
    )
    doc = DocumentBuilder.build_from_task(task)
    assert doc is not None
    assert "Kéo rải cáp ngầm" in doc.content
    assert "50.0%" in doc.content
    assert doc.metadata["volume"] == 500.0


# 2. Test TextChunker Edge Cases
def test_text_chunker_deterministic_id_and_metadata():
    chunker = TextChunker(chunk_size=100, overlap=20)
    doc = KnowledgeDocument(
        id="doc:issues:iss-1",
        content="Nội dung kiểm tra chia nhỏ văn bản " * 10,
        source_table="issues",
        record_id="iss-1",
        project_code="TITS-01",
        metadata={"priority": "HIGH"},
    )
    chunks1 = chunker.chunk_document(doc)
    chunks2 = chunker.chunk_document(doc)

    assert len(chunks1) > 1
    assert chunks1[0].id == chunks2[0].id
    assert chunks1[1].id == chunks2[1].id
    assert chunks1[0].project_code == "TITS-01"
    assert chunks1[0].metadata["priority"] == "HIGH"


def test_text_chunker_edge_cases():
    chunker = TextChunker(chunk_size=500, overlap=100)

    # 1. Văn bản ngắn hơn cả overlap (ví dụ 50 ký tự)
    short_doc = KnowledgeDocument(
        id="doc:short",
        content="Văn bản rất ngắn dưới 50 ký tự.",
        source_table="field_logs",
        record_id="fl-short",
        project_code="TITS-01",
    )
    chunks = chunker.chunk_document(short_doc)
    assert len(chunks) == 1
    assert chunks[0].content == "Văn bản rất ngắn dưới 50 ký tự."

    # 2. Văn bản chứa nhiều dòng xuống dòng và Unicode tiếng Việt
    unicode_doc = KnowledgeDocument(
        id="doc:uni",
        content="Dòng 1: Đổ bê tông\n\nDòng 2: Nghiệm thu cốt thép cột trục A-B\n\nDòng 3: Đạt yêu cầu",
        source_table="field_logs",
        record_id="fl-uni",
        project_code="TITS-01",
    )
    u_chunks = chunker.chunk_document(unicode_doc)
    assert len(u_chunks) == 1
    assert "Nghiệm thu cốt thép" in u_chunks[0].content

    # 3. Lỗi cấu hình chunk_size <= overlap
    with pytest.raises(ValueError, match="overlap"):
        TextChunker(chunk_size=100, overlap=150)


# 3. Test EmbeddingProvider
def test_deterministic_fake_embedding_provider():
    provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimensions == 384

    texts = ["Xin chào Titsmart", "Báo cáo tiến độ công trình"]
    vecs1 = provider.embed(texts)
    vecs2 = provider.embed(texts)

    assert len(vecs1) == 2
    assert len(vecs1[0]) == 384
    assert vecs1[0] == vecs2[0]
    assert vecs1[1] == vecs2[1]
    assert vecs1[0] != vecs1[1]


# 4. Test VectorStore (Upsert, Deduplication, Rejection, Fail-Closed ACL)
@pytest.fixture
def vector_store():
    return InMemoryVectorStore(expected_dimensions=384)


@pytest.fixture
def sample_chunks():
    doc1 = KnowledgeDocument(
        id="doc:fl:1",
        content="Đổ bê tông sàn tầng 2 công trình TITS-01",
        source_table="field_logs",
        record_id="fl-1",
        project_code="TITS-01",
    )
    doc2 = KnowledgeDocument(
        id="doc:iss:2",
        content="Mất điện toàn trạm biến áp dự án TITS-02",
        source_table="issues",
        record_id="iss-2",
        project_code="TITS-02",
    )
    chunker = TextChunker(chunk_size=500, overlap=50)
    c1 = chunker.chunk_document(doc1)[0]
    c2 = chunker.chunk_document(doc2)[0]
    return [c1, c2]


def test_vector_store_rejects_wrong_dimension(vector_store, sample_chunks):
    c1 = sample_chunks[0]
    bad_dim_vec = [0.1] * 128
    with pytest.raises(ValueError, match="Vector dimension không hợp lệ"):
        vector_store.upsert([c1], [bad_dim_vec])


def test_vector_store_upsert_deduplication(vector_store, sample_chunks):
    provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    c1 = sample_chunks[0]
    vec1 = provider.embed([c1.content])

    vector_store.upsert([c1], vec1)
    assert vector_store.count() == 1

    vector_store.upsert([c1], vec1)
    assert vector_store.count() == 1


def test_vector_store_fail_closed_acl(vector_store, sample_chunks):
    """Kiểm tra ACL Fail-Closed: Không truyền hoặc truyền rỗng project_codes -> trả về [] ngay lập tức."""
    provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    c1, c2 = sample_chunks
    vecs = provider.embed([c1.content, c2.content])
    vector_store.upsert([c1, c2], vecs)

    query_vec = provider.embed(["Tìm thông tin công trình"])[0]

    # 1. FAIL-CLOSED: Truyền rỗng set() -> Trả về [] tuyệt đối
    res_empty = vector_store.search(query_vec, project_codes=set(), top_k=5)
    assert res_empty == []

    # 2. Truy vấn chỉ có quyền TITS-01 -> Tuyệt đối không thấy c2 (TITS-02)
    res_tits01 = vector_store.search(query_vec, project_codes={"TITS-01"}, top_k=5)
    assert len(res_tits01) == 1
    assert res_tits01[0].project_code == "TITS-01"
    assert res_tits01[0].id == c1.id

    # 3. Truy vấn với quyền cả 2 dự án -> Thấy cả 2
    res_both = vector_store.search(query_vec, project_codes={"TITS-01", "TITS-02"}, top_k=5)
    assert len(res_both) == 2


def test_vector_store_delete_by_record(vector_store, sample_chunks):
    provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    vecs = provider.embed([c.content for c in sample_chunks])
    vector_store.upsert(sample_chunks, vecs)
    assert vector_store.count() == 2

    deleted_count = vector_store.delete_by_record("field_logs", "fl-1")
    assert deleted_count == 1
    assert vector_store.count() == 1


def test_vector_store_top_k_limits(vector_store, sample_chunks):
    provider = DeterministicFakeEmbeddingProvider(dimensions=384)
    vecs = provider.embed([c.content for c in sample_chunks])
    vector_store.upsert(sample_chunks, vecs)

    query_vec = provider.embed(["test"])[0]

    # top_k <= 0 -> ném lỗi
    with pytest.raises(ValueError, match="top_k phải là số nguyên dương"):
        vector_store.search(query_vec, project_codes={"TITS-01"}, top_k=0)

    # top_k quá lớn (> max_top_k) -> ném lỗi
    with pytest.raises(ValueError, match="giới hạn tối đa"):
        vector_store.search(query_vec, project_codes={"TITS-01"}, top_k=500)
