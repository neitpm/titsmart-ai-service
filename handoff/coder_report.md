# Coder Report — Vòng 7: PromptSynthesizer & ResponseFormatter Chuẩn Hóa Kỹ Thuật

## 1. Tóm tắt mục tiêu & kết quả thực hiện
Đã hoàn thành toàn bộ yêu cầu Vòng 7 theo đúng phạm vi và nguyên tắc an toàn:
- Xây dựng module tổng hợp prompt có cấu trúc `PromptSynthesizer` và data contract `SynthesizedPrompt`.
- Xây dựng module chuẩn hóa câu trả lời kỹ thuật `ResponseFormatter` tích hợp danh mục trích dẫn minh bạch (citations catalog) và khử trùng lặp nguồn (source deduplication).
- Tích hợp liền mạch vào `ChatEngine`, hỗ trợ Dependency Injection và cung cấp phương thức `synthesize_prompt()` phục vụ kiểm toán / LLM integration với cơ chế Fail-Closed kiểm soát quyền truy cập theo `AuthContext`.
- Bổ sung bộ kiểm thử hồi quy và đơn vị toàn diện `tests/test_synthesis.py` (37 test cases mới).
- Toàn bộ test suite chạy thành công: **159 passed, 1 skipped** (1 skipped là test tích hợp live Supabase staging khi không có credentials thực tế).

---

## 2. Chi tiết các thành phần kỹ thuật đã xây dựng

### A. `src/titsmart_ai/synthesis/prompt_synthesizer.py`
- **`SynthesizedPrompt` (Pydantic Model)**:
  - Khóa nghiêm ngặt schema (`extra="forbid"`).
  - Bao gồm: `system_prompt`, `user_prompt`, `sql_context`, `vector_context`, `full_prompt`, `token_estimate`, `intent`, `metadata`.
- **`SYSTEM_PROMPT_TEMPLATE`**:
  - Thiết lập vai trò: Chuyên gia Phân tích Tiến độ & Quản lý Dự án Xây dựng.
  - 4 nguyên tắc bắt buộc:
    1. Zero Hallucination (tuyệt đối không bịa số liệu).
    2. Grounding & Citations (mọi kết luận/số liệu đều kèm nguồn [Nguồn X]).
    3. Văn phong kỹ thuật xây dựng (rõ ràng, phân tách rành mạch: tổng quan, số liệu, nhật ký/sự cố, kiến nghị).
    4. Fail-Closed (thiếu dữ liệu phải thông báo không tìm thấy, không phỏng đoán).
- **`PromptSynthesizer`**:
  - `build_system_prompt()`: Cung cấp system prompt mặc định hoặc tùy biến.
  - `format_sql_context()`: Chuẩn hóa dữ liệu SQL (project summary, task list, progress breakdown).
  - `format_vector_context()`: Chuẩn hóa dữ liệu ngữ nghĩa vector RAG kèm bảng nguồn, mã bản ghi, dự án và điểm tương đồng.
  - `estimate_tokens()`: Ước lượng token tất định cho tiếng Việt kỹ thuật (~3.5 chars/token).
  - `synthesize()`: Ghép nối hoàn chỉnh prompt payload và đính kèm metadata kiểm toán.

### B. `src/titsmart_ai/synthesis/response_formatter.py`
- **`ResponseFormatter`**:
  - `deduplicate_sources()`: Khử trùng lặp nguồn trích dẫn theo tuple `(source_type, source_table, record_id, project_code)`, ưu tiên giữ bản ghi có điểm tương quan cao nhất.
  - `format_citations_catalog()`: Tạo danh mục trích dẫn Markdown chuẩn mực:
    `- [Nguồn X] (TYPE: table/id | Dự án: code | Điểm tương quan: score): label`
  - `validate_citations()`: Xác thực cấu trúc dữ liệu `ChatSource`, source_type (`sql` / `vector`) và các trường bắt buộc.
  - `format_sql_project_summary()`: Định dạng kết quả tổng quan tiến độ 1 dự án và danh sách công việc chậm.
  - `format_sql_aggregate_progress()`: Định dạng thống kê tiến độ nhiều dự án trong phạm vi quyền hạn.
  - `format_vector_response()`: Định dạng trích xuất nhật ký / sự cố hiện trường.
  - `format_hybrid_response()`: Tổng hợp số liệu định lượng (SQL) và ngữ cảnh định tính (Vector RAG), loại bỏ trùng lặp citation ở từng phần để đính kèm 1 danh mục trích dẫn thống nhất.
  - `format_unsupported()` & `format_no_evidence()`: Chuẩn hóa phản hồi khi từ chối hoặc không có bằng chứng với `has_evidence=False`.
  - `standardize_technical_answer()`: Hàm tổng quát chuẩn hóa câu trả lời kỹ thuật và danh mục nguồn.

### C. Tích hợp `ChatEngine` (`src/titsmart_ai/domain/chat_engine.py`)
- Nhận `PromptSynthesizer` và `ResponseFormatter` qua constructor (hỗ trợ Dependency Injection).
- Cập nhật các luồng `_handle_sql_intent`, `_handle_vector_intent`, `_handle_hybrid_intent` ủy thác hoàn toàn việc định dạng và trích dẫn cho `ResponseFormatter`.
- Thêm method `synthesize_prompt(question, auth_context)`: Tự động trích xuất dữ liệu phù hợp theo intent và trả về `SynthesizedPrompt`, tuân thủ nghiêm ngặt nguyên tắc Fail-Closed (chặn ngay lập tức nếu user không có quyền truy cập dự án).

---

## 3. Kết quả kiểm thử & Kiểm chứng hồi quy
- Lệnh chạy test:
  ```bash
  python -m pytest tests -q
  ```
- Kết quả:
  ```text
  159 passed, 1 skipped in 0.50s
  ```
- Toàn bộ 37 test cases trong `tests/test_synthesis.py` bao phủ:
  - Unit tests cho `PromptSynthesizer` (system prompt, sql/vector context, token estimation, prompt synthesis theo từng intent).
  - Unit tests cho `ResponseFormatter` (deduplication, format citations catalog, validate citations, format sql/vector/hybrid, unsupported, idempotency).
  - Regression & Integration tests tích hợp `ChatEngine` (synthesize prompt, fail-closed khi không có quyền hoặc rỗng quyền, câu trả lời kèm citation minh bạch, dependency injection).
- Không ảnh hưởng hay làm vỡ bất kỳ test case nào đã có từ Vòng 1 đến Vòng 6.

---

## 4. Phạm vi sửa đổi (Diff Scope)
- **Thư mục mới:** `src/titsmart_ai/synthesis/` (`__init__.py`, `prompt_synthesizer.py`, `response_formatter.py`)
- **Tập tin mới:** `tests/test_synthesis.py`
- **Tập tin cập nhật trong src:**
  - `src/titsmart_ai/domain/__init__.py` (re-export PromptSynthesizer, SynthesizedPrompt, ResponseFormatter)
  - `src/titsmart_ai/domain/chat_engine.py` (tích hợp synthesis và formatting)
- **Handoff & trạng thái:**
  - `handoff/coder_report.md`
  - `handoff/live_progress.md`
  - `state.json`

Tuyệt đối không sửa ngoài phạm vi cho phép, không kết nối production, không đọc secret, không dùng Kafka.
