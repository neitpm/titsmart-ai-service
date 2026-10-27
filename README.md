# Titsmart AI Service (Hybrid SQL + RAG)

Hệ thống AI Assistant chuyên dụng cho Titsmart, ứng dụng kiến trúc **Hybrid SQL + RAG**:
- **SQL Engine**: Xử lý các câu hỏi tính toán chính xác tuyệt đối (tiến độ, số lượng, ngày hạn, thống kê dự án).
- **RAG Engine (pgvector / In-Memory)**: Xử lý tìm kiếm ngữ nghĩa văn bản (nhật ký hiện trường, sự cố, nguyên nhân chậm tiến độ, hồ sơ pháp lý).

---

## 1. Cấu trúc thư mục

```text
titsmart-ai-service/
├── data/
│   └── sample/                          # Dữ liệu mẫu đã ẩn danh / che PII
│       ├── projects_sample.json
│       ├── tasks_sample.json
│       ├── field_logs_sample.json
│       ├── document_tracks_sample.json
│       └── issues_sample.json
├── src/
│   └── titsmart_ai/
│       ├── api/                         # FastAPI entry points & chat routes
│       ├── config.py                    # Cấu hình Pydantic Settings & kiểm tra bảo mật
│       ├── domain/                      # Domain models & ChatEngine điều phối
│       ├── ingestion/                   # Data loader, chunker & document builder
│       ├── llm/                         # LLM Adapters, FakeOllamaClient & Guardrails
│       ├── router/                      # Query Router (SQL vs Vector vs Hybrid)
│       ├── security/                    # AuthContext, JWT verification & ACL
│       ├── synthesis/                   # PromptSynthesizer & ResponseFormatter
│       └── tools/                       # QueryTool, VectorStore & OllamaEmbeddingProvider
├── tests/                               # Bộ kiểm thử đơn vị & tích hợp
├── .env.example                         # File mẫu cấu hình biến môi trường
└── README.md
```

---

## 2. Tích hợp Ollama Local

Hệ thống hỗ trợ tích hợp với dịch vụ mô hình cục bộ **Ollama Local**:

### 2.1. Cấu hình mô hình
- **Mô hình chính (Primary LLM)**: `qwen3:8b` – Sử dụng để tổng hợp và sinh câu trả lời kỹ thuật.
- **Mô hình dự phòng (Fallback LLM)**: `qwen3:4b` – Tự động kích hoạt khi `qwen3:8b` gặp sự cố, lỗi HTTP 500 hoặc timeout.
- **Mô hình Embedding (Vector Retrieval)**: `bge-m3:latest` (1024 dimensions) – Sử dụng cho tìm kiếm ngữ nghĩa (Semantic Search).

### 2.2. Ràng buộc an toàn
- **Chỉ kết nối Local Loopback**: `OLLAMA_BASE_URL` mặc định là `http://127.0.0.1:11434` (chỉ chấp nhận `127.0.0.1`, `localhost`, `::1`, `0.0.0.0`). Tuyệt đối cấm kết nối ra internet hoặc dịch vụ đám mây công cộng.
- **Cấm tuyệt đối dùng `bge-m3` để trò chuyện**: Mô hình `bge-m3:latest` là mô hình vector embedding chuyên biệt (1024 chiều), hệ thống sẽ từ chối ngay lập tức (HTTP 400 / ValueError) nếu cố tình cấu hình hoặc sử dụng `bge-m3` cho mục đích chat.
- **Timeout bảo vệ**: Cấu hình `OLLAMA_REQUEST_TIMEOUT` (mặc định 30.0s) kích hoạt cơ chế Fail-Closed khi quá thời gian phản hồi.

---

## 3. Chế độ hoạt động (LLM_MODE)

Biến môi trường `LLM_MODE` kiểm soát phương thức sinh phản hồi:

| Chế độ | Mô tả |
| :--- | :--- |
| `mock` (Mặc định) | Chạy hoàn toàn offline trong môi trường kiểm thử/phát triển. Sử dụng `DeterministicFakeEmbeddingProvider` và `MockLLMAdapter` không cần mở kết nối mạng hay cài Ollama. |
| `staging` | Kết nối trực tiếp tới Ollama cục bộ (`http://127.0.0.1:11434`) với `qwen3:8b` (fallback `qwen3:4b`) và `bge-m3:latest`. |
| `production` | **CẤM TUYỆT ĐỐI**: Hệ thống sẽ fail-fast và ném ngoại lệ bảo mật ngay khi khởi động nếu phát hiện `LLM_MODE=production`. |

---

## 4. Các cơ chế bảo mật & Guardrails

1. **ACL Fail-Closed (Kiểm soát truy cập)**:
   - Dữ liệu luôn được lọc trước bằng `allowed_project_codes` từ `AuthContext` trước khi đưa vào ngữ cảnh LLM.
   - Không bao giờ đưa dữ liệu của dự án ngoài thẩm quyền vào prompt.
2. **Bảo vệ chống Prompt Injection**:
   - Tài liệu kỹ thuật chỉ được xem là ngữ cảnh thô (untrusted context).
   - Quyền hạn, router phân loại, SQL query và vector search hoàn toàn do Backend kiểm soát độc lập.
   - Các chỉ thị độc hại bên trong câu hỏi hoặc tài liệu không thể vượt quyền hay kích hoạt tool.
3. **Citation Post-Validation (Chống LLM bịa nguồn)**:
   - Danh mục `sources` bắt buộc do Backend lập từ các bằng chứng (evidence) thực tế được trích xuất.
   - Hệ thống tự động hậu kiểm chéo câu trả lời của LLM; các trích dẫn `[Nguồn X]` giả mạo hoặc không có trong danh mục thực tế sẽ bị loại bỏ lập tức.
4. **Từ chối an toàn khi thiếu dữ liệu (Insufficient Evidence Fail-Closed)**:
   - Khi không tìm thấy đủ dữ kiện xác thực, hệ thống trả về thông báo từ chối minh bạch với cờ `has_evidence=False`, không suy đoán bừa bãi.
5. **Timeout & Lỗi Mạng Fail-Closed**:
   - Khi Ollama hoặc LLM gặp sự cố timeout hay mất kết nối, hệ thống kích hoạt trạng thái Fail-Closed an toàn, trả về lỗi kèm cờ cảnh báo mà không rò rỉ thông tin nội bộ.
6. **Không rò rỉ dữ liệu nhạy cảm**:
   - Không gửi PII, secret, mật khẩu hay JWT token của người dùng vào prompt của LLM.

---

## 5. Hướng dẫn cài đặt & Kiểm thử

### 5.1. Thiết lập biến môi trường
Sao chép cấu hình từ file mẫu `.env.example`:
```bash
cp .env.example .env
```

### 5.2. Chạy bộ kiểm thử (Unit & Integration Tests)
Toàn bộ test suite được thiết kế chạy offline độc lập thông qua `FakeOllamaClient` và không yêu cầu daemon Ollama thật:
```bash
python -m pytest tests -q
```
