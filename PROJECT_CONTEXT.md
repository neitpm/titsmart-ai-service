# Project Context

## Goal
Xây dựng AI service Hybrid SQL + RAG cho Titsmart.

## Current scope
Vòng đầu chỉ dựng loader và data contract cho JSON mẫu.

## Constraints
- Không kết nối production.
- Không đọc secret.
- Không dùng Kafka.
- Chỉ sửa src/ và tests/.
- Vòng 8 Local Ollama & LLM Constraints:
  + LLM_MODE chỉ chấp nhận 'mock' hoặc 'staging'. Cấm tuyệt đối 'production'.
  + LLM sinh câu trả lời: `qwen3:8b` via Ollama local (fallback: `qwen3:4b` khi 8b không khả dụng hoặc lỗi).
  + Vector retrieval: `bge-m3:latest` (1024 dims). Không dùng bge-m3 để trò chuyện.
  + OLLAMA_BASE_URL: `http://127.0.0.1:11434`. Không gửi dữ liệu ra cloud hay internet.
  + ACL fail-closed: Lọc dữ liệu trước khi ghép vào LLM prompt, không đưa dữ liệu ngoài allowed_project_codes.
  + Không gửi PII, secret, user JWT vào LLM prompt.
  + Citation Post-Validation: Kiểm tra chéo citation trong câu trả lời với context thực tế, không tin LLM bịa nguồn.
  + Không đủ bằng chứng -> Trả về thông báo từ chối và has_evidence=False.
  + Kiến trúc bảo vệ Prompt Injection: Tài liệu chỉ là ngữ cảnh thô (untrusted data). Quyền hạn, router, SQL query và vector search hoàn toàn do Backend kiểm soát độc lập ngoài LLM. Prompt injection trong tài liệu không thể chiếm quyền hoặc kích hoạt tool.
  + Backend-Driven Citations: Danh mục `sources` bắt buộc do Backend tạo lập từ chính evidence hợp lệ đã trích xuất; LLM chỉ định dạng câu trả lời tham chiếu các ID hợp lệ, mọi ID giả do LLM tự sinh sẽ bị phát hiện và loại bỏ.
  + Timeout & Error Fail-Closed: Khi LLM/Ollama timeout hoặc lỗi mạng, hệ thống fail-closed an toàn, không rò rỉ dữ liệu hoặc suy diễn bừa bãi.
  + Test Suite: Viết FakeOllamaClient, không gọi model thật trong unit test để bảo đảm tốc độ và tính tất định. Cập nhật .env.example và README.md.

## Definition of Done
- Test chạy thật và pass.
- Không lỗi nghiêm trọng.
- Diff đúng phạm vi.
- Có báo cáo bàn giao ngắn.
