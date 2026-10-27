# Kế hoạch Vòng 8: Đối chiếu Kiến trúc ProjectLens và Triển khai LLM Staging Adapter

## 1. Phân tích Repository ProjectLens (`https://github.com/neitpm/ProjectLens`)

### Điểm mạnh nổi bật của ProjectLens:
- **System Prompt chuẩn kỹ thuật TitSmart**: Có quy tắc trích xuất rõ ràng về bảng giá, khối lượng, vật tư, đơn giá và ràng buộc kiểm soát ảo giác (Anti-Hallucination): *"Nếu thiếu thông tin, nói rõ: Tài liệu hiện tại không đề cập đến thông tin này"*.
- **Structured Lookup tách biệt RAG ngữ nghĩa**: Tách hẳn phần tra cứu chi phí cao nhất (`highest_cost_answer`) và danh mục bản vẽ/phụ lục (`drawing_inventory_answer`) ra khỏi vector search để tránh ảo giác số liệu.
- **pgvector schema (384 dims)**: Sử dụng MiniLM-L12 384 dimensions tương thích hoàn toàn với schema pgvector chúng ta đã thiết kế ở Vòng 4 (`migrations/001_knowledge_vectors.sql`).

### Những phần KHÔNG sao chép để bảo vệ an toàn cho `titsmart-ai-service`:
- **KHÔNG dùng kết nối trực tiếp PostgreSQL raw connection string** (`postgresql://...`): `titsmart-ai-service` phải dùng `ReadOnlyDataClient` và Supabase PostgREST client với hostname allowlist và RLS `auth.uid()`.
- **KHÔNG bỏ qua ACL**: ProjectLens tìm kiếm toàn bộ `rag_chunks` không có bộ lọc `project_codes`. Ở `titsmart-ai-service`, bắt buộc giữ nguyên **Fail-Closed ACL**: lọc `project_codes` trước khi truy vấn và trước khi ghép vào prompt.
- **KHÔNG phụ thuộc Ollama local cứng**: Cần thiết kế `LLMClient(Protocol)` trừu tượng để hỗ trợ cả `FakeLLMClient` (offline unit test) và `StagingLLMClient` (khi kết nối staging).

---

## 2. Kế hoạch Triển khai Vòng 8 cho `titsmart-ai-service`

1. **LLM Client Contract & Staging Adapter (`src/titsmart_ai/llm/client.py`)**:
   - `LLMClient(Protocol)`: Phương thức `generate(system_prompt: str, user_prompt: str, timeout: float) -> str`.
   - `FakeLLMClient`: Phục vụ 100% offline tests tất định, giả lập phản hồi tuân thủ evidence hoặc phát hiện cố tình bịa citation.
   - `StagingLLMClient`: Chỉ cho phép kết nối endpoint staging được cấu hình trong `Settings`, cấm tuyệt đối khi `APP_ENV=production`.
   - `Settings.LLM_MODE`: Chỉ chấp nhận `"mock"` hoặc `"staging"`, từ chối `"production"`.

2. **Backend-Driven Citation & Anti-Hallucination Guardrails (`src/titsmart_ai/synthesis/response_formatter.py`)**:
   - Backend chuẩn bị danh mục `sources` từ records/chunks hợp lệ.
   - Hậu kiểm câu trả lời của LLM: Kiểm tra chéo mọi trích dẫn `[Nguon n]`. Nếu LLM tự bịa ID ngoài danh mục, backend tự động lọc bỏ.
   - Nếu không có evidence, hệ thống từ chối trả lời và gán `has_evidence = False`.

3. **Kháng Prompt Injection**:
   - Coi nội dung tài liệu là untrusted data trong sandbox, không cho phép thay đổi system prompt hoặc vượt quyền ACL.

4. **Bộ Test Suite Vòng 8**:
   - Test LLM mock mode, staging mode controls.
   - Test fail-closed ACL không lọt dữ liệu vào prompt.
   - Test loại bỏ citation giả.
   - Test prompt injection kháng đổi vai trò.
   - Test timeout và error handling.
