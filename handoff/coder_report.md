# Coder Report (Round 4 - Iteration 11 - Fail-Closed ACL & PII Sanitizer)

## Changed
- `src/titsmart_ai/tools/vector_store.py`:
  - **Fail-Closed ACL**: Thay đổi chữ ký phương thức `search(..., project_codes: Set[str], top_k: int = 5)`. Tham số `project_codes` bắt buộc phải là một `Set[str]` các dự án được phép. Nếu rỗng (`set()`) -> trả về `[]` ngay lập tức, không bao giờ lộ toàn bộ dữ liệu.
  - Thêm giới hạn `max_top_k` (mặc định 100), kiểm tra `0 < top_k <= max_top_k`.
  - Kiểm tra `project_code` không rỗng khi `upsert`.
- `src/titsmart_ai/ingestion/document_builder.py`:
  - Thêm `sanitize_text()` với Regex tự động che giấu số điện thoại (`[SỐ ĐIỆN THOẠI ĐÃ ẨN]`), số tài khoản ngân hàng (`[SỐ TÀI KHOẢN ĐÃ ẨN]`) và email, ngay cả khi người dùng gõ trực tiếp vào nội dung ghi chú (`note`/`notes`/`description`).
  - Xử lý edge cases trong `TextChunker`: văn bản ngắn hơn `overlap` trả về 1 chunk duy nhất mà không bị lặp vô tận, kiểm tra `chunk_size > overlap`, bảo toàn Unicode tiếng Việt và ký tự xuống dòng.
- `migrations/001_knowledge_vectors.sql`:
  - Thêm ràng buộc toàn vẹn: `check (source_table in ('field_logs', 'issues', 'tasks'))`, `check (length(trim(project_code)) > 0)`.
  - Thêm ràng buộc duy nhất: `constraint uq_knowledge_vectors_chunk unique (source_table, record_id, chunk_index)`.
  - Thêm chính sách RLS chi tiết:
    - Policy SELECT: chỉ cho phép `auth.uid()` đọc các vector thuộc dự án mà họ là thành viên (`project_members`).
    - Policy MUTATION: chỉ cho phép `service_role` thực hiện ghi/xóa vector.
- `tests/test_vector_rag.py`:
  - Thêm test `test_builder_sanitizes_pii_in_notes` (kiểm tra che SĐT và STK ngân hàng xuất hiện trong notes).
  - Thêm test `test_text_chunker_edge_cases` (văn bản siêu ngắn, Unicode tiếng Việt nhiều dòng, lỗi overlap >= chunk_size).
  - Thêm test `test_vector_store_fail_closed_acl` (xác nhận `project_codes=set()` trả về `[]`).
  - Thêm test `test_vector_store_top_k_limits` (`top_k=0` và `top_k=500` bị từ chối).

## Tests
- Command: `python -m pytest tests -q`
- Result: `.......................................................s [100%]` (55 passed, 1 skipped in 0.37s)

## Staging & Model Limitations
- Fake embeddings trong Vòng 4 chỉ chứng minh tính đúng đắn của Storage Contract, Determinism, Dimension Verification và ACL Project Isolation.
- Đánh giá chất lượng Semantic Search tiếng Việt thực tế sẽ được thực hiện sau khi tích hợp embedding model chính thức (OpenAI `text-embedding-3-small` hoặc Google `text-embedding-004`) kèm bộ benchmark.
