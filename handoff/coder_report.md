# Báo cáo Coder: Tích hợp Ollama Local (qwen3:8b, fallback qwen3:4b, bge-m3:latest) & Cập nhật Tài liệu

## 1. Mục tiêu và Phạm vi Hoàn thành
- **Tích hợp Ollama Local**:
  - LLM sinh câu trả lời: `qwen3:8b` (fallback tự động sang `qwen3:4b` khi gặp sự cố, timeout hoặc HTTP 500).
  - Embedding Model: `bge-m3:latest` (1024 dimensions) cho Semantic Search & Vector RAG.
  - Cấm tuyệt đối sử dụng `bge-m3` để sinh văn bản / trò chuyện (trả về HTTP 400).
- **Quy chuẩn Bảo mật & Guardrails**:
  - `LLM_MODE`: Chỉ chấp nhận `'mock'` hoặc `'staging'`. Cấm tuyệt đối `'production'`.
  - ACL Fail-Closed: Lọc dữ liệu trước khi ghép vào LLM prompt.
  - Citation Post-Validation: Hậu kiểm chéo citation với context thực tế, gỡ bỏ citation bịa.
  - Kháng Prompt Injection: Xử lý untrusted context, ngăn chặn thay đổi system instructions.
  - Fail-Closed: Không đủ evidence -> `has_evidence=False`. Timeout / network error -> Fail-closed an toàn.
- **Offline Testing**: `FakeOllamaClient` hỗ trợ giả lập 100% offline, không gọi mạng.
- **Khắc phục theo Review Feedback**:
  - `.env.example`: Cập nhật cấu hình Ollama local gồm `LLM_MODE`, `OLLAMA_BASE_URL`, `OLLAMA_PRIMARY_MODEL`, `OLLAMA_FALLBACK_MODEL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_EMBEDDING_DIMENSIONS` và `OLLAMA_REQUEST_TIMEOUT`. Loại bỏ hoàn toàn cấu hình embedding cũ `text-embedding-004`/768.
  - `README.md`: Bổ sung chi tiết tài liệu về kiến trúc Ollama local, cơ chế fallback qwen3:8b -> qwen3:4b, bge-m3:latest (1024 dimensions), ràng buộc local loopback và cấm chat bằng embedding model, giải thích các chế độ `mock`/`staging`, các cơ chế bảo mật guardrails (ACL, prompt injection, citation post-validation, timeout fail-closed), và hướng dẫn chạy test.

## 2. Kết quả Kiểm thử (Pytest)
```text
python -m pytest tests -q
221 passed, 1 skipped in 0.67s
```
Toàn bộ 221 test cases (bao gồm bộ test tích hợp `test_ollama_local_integration.py`) đều passed 100%.

## 3. Chuyển giao Trạng thái
- `state.json`: Cập nhật `state` thành `"REVIEW"` và `next_actor` thành `"CODEX"`.
